from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .app_models import AgentNote, TerraformValidationResult
from .auth import hash_password, hash_token, new_session_token, session_expires_at, verify_password
from .models import CompileResponse, TopologySpec


def db_path() -> Path:
    return Path(os.getenv("W2P_DB_PATH", ".w2p/w2p.sqlite3"))


def initialize_storage() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            create table if not exists users (
              id text primary key,
              email text not null unique,
              name text not null,
              password_hash text not null,
              created_at text not null default current_timestamp
            );

            create table if not exists sessions (
              token_hash text primary key,
              user_id text not null references users(id) on delete cascade,
              expires_at text not null,
              created_at text not null default current_timestamp
            );

            create table if not exists codebases (
              id text primary key,
              user_id text not null references users(id) on delete cascade,
              name text not null,
              provider text not null,
              model text not null,
              status text not null,
              topology_hash text not null,
              topology_json text not null,
              policy_issues_json text not null,
              validation_json text not null,
              generated_files_json text not null,
              agent_notes_json text not null,
              created_at text not null default current_timestamp,
              updated_at text not null default current_timestamp
            );
            """
        )


def create_user(email: str, name: str, password: str) -> dict[str, Any]:
    user_id = uuid.uuid4().hex
    try:
        with _connect() as conn:
            conn.execute(
                "insert into users (id, email, name, password_hash) values (?, ?, ?, ?)",
                (user_id, email.lower(), name, hash_password(password)),
            )
            row = conn.execute(
                "select id, email, name, created_at from users where id = ?",
                (user_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise ValueError("email is already registered") from exc
    return dict(row)


def authenticate_user(email: str, password: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "select id, email, name, password_hash, created_at from users where email = ?",
            (email.lower(),),
        ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return {key: row[key] for key in ["id", "email", "name", "created_at"]}


def create_session(user_id: str) -> str:
    token = new_session_token()
    with _connect() as conn:
        conn.execute(
            "insert into sessions (token_hash, user_id, expires_at) values (?, ?, ?)",
            (hash_token(token), user_id, session_expires_at()),
        )
    return token


def get_user_for_token(token: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            select users.id, users.email, users.name, users.created_at
            from sessions
            join users on users.id = sessions.user_id
            where sessions.token_hash = ?
              and sessions.expires_at > current_timestamp
            """,
            (hash_token(token),),
        ).fetchone()
    return dict(row) if row is not None else None


def create_codebase(
    *,
    user_id: str,
    name: str,
    provider: str,
    model: str,
    compile_response: CompileResponse,
    topology: TopologySpec,
    validation: TerraformValidationResult,
    agent_notes: list[AgentNote],
) -> dict[str, Any]:
    codebase_id = uuid.uuid4().hex
    payload = (
        codebase_id,
        user_id,
        name,
        provider,
        model,
        compile_response.status,
        compile_response.topology_hash,
        topology.model_dump_json(by_alias=True, exclude_none=True),
        json.dumps([issue.model_dump(mode="json") for issue in compile_response.policy_issues]),
        validation.model_dump_json(),
        json.dumps([item.model_dump(mode="json") for item in compile_response.generated_files]),
        json.dumps([note.model_dump(mode="json") for note in agent_notes]),
    )
    with _connect() as conn:
        conn.execute(
            """
            insert into codebases (
              id, user_id, name, provider, model, status, topology_hash, topology_json,
              policy_issues_json, validation_json, generated_files_json, agent_notes_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        return _get_codebase(conn, user_id, codebase_id)


def list_codebases(user_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            select id, name, provider, model, status, created_at, updated_at
            from codebases
            where user_id = ?
            order by updated_at desc, created_at desc
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_codebase(user_id: str, codebase_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "select * from codebases where user_id = ? and id = ?",
            (user_id, codebase_id),
        ).fetchone()
    return dict(row) if row is not None else None


def delete_codebase(user_id: str, codebase_id: str) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "delete from codebases where user_id = ? and id = ?",
            (user_id, codebase_id),
        )
        return cursor.rowcount > 0


def _get_codebase(conn: sqlite3.Connection, user_id: str, codebase_id: str) -> dict[str, Any]:
    row = conn.execute(
        "select * from codebases where user_id = ? and id = ?",
        (user_id, codebase_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("codebase was not created")
    return dict(row)


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn

