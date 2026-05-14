from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from ..app_models import TerraformValidationResult
from ..models import TopologySpec


@dataclass(frozen=True)
class ChatbotReply:
    answer: str
    suggestions: list[str]
    engine: str


SYSTEM_INSTRUCTIONS = """You are W2P Copilot, a production engineering assistant embedded inside W2P.
Answer from the provided workspace context, not from generic guesses.
Distinguish clearly between:
- the W2P product itself;
- a user's selected generated codebase;
- the final cloud app that the generated code would deploy.
If the context is incomplete, say exactly what is missing and what the user should select or generate next.
Do not repeat a greeting unless the user is greeting you.
Keep answers direct, practical, and technically specific."""


def generate_chat_reply(
    *,
    message: str,
    user: dict[str, Any],
    codebase: dict[str, Any] | None,
    codebases: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> ChatbotReply:
    suggestions = _suggestions(codebase)
    context = _build_workspace_context(
        user=user,
        codebase=codebase,
        codebases=codebases,
        history=history,
    )
    prompt = f"""Workspace context:
{context}

User question:
{message}

Answer as W2P Copilot."""

    provider = _configured_provider()
    if provider == "openai":
        model = _chat_model()
        try:
            answer = _openai_response_text(
                prompt=prompt,
                api_key=os.environ["OPENAI_API_KEY"],
                model=model,
                instructions=SYSTEM_INSTRUCTIONS,
            )
            return ChatbotReply(answer=answer, suggestions=suggestions, engine=f"openai:{model}")
        except Exception:
            fallback = _local_workspace_answer(message=message, user=user, codebase=codebase, codebases=codebases)
            answer = f"{fallback}\n\nLive AI was configured but unavailable, so I answered from the local workspace context."
            return ChatbotReply(answer=answer, suggestions=suggestions, engine="local-fallback")

    return ChatbotReply(
        answer=_local_workspace_answer(message=message, user=user, codebase=codebase, codebases=codebases),
        suggestions=suggestions,
        engine="local-context",
    )


def _configured_provider() -> str:
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "local"


def _chat_model() -> str:
    return (
        os.getenv("W2P_CHAT_MODEL")
        or os.getenv("W2P_OPENAI_CHAT_MODEL")
        or os.getenv("OPENAI_CHAT_MODEL")
        or "gpt-5.2"
    )


def _openai_response_text(*, api_key: str, model: str, prompt: str, instructions: str) -> str:
    payload = {
        "model": model,
        "instructions": instructions,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
        "max_output_tokens": _int_env("W2P_CHAT_MAX_OUTPUT_TOKENS", 1000),
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_int_env("W2P_CHAT_TIMEOUT_SECONDS", 30)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI chat provider returned {exc.code}: {detail[:300]}") from exc

    text = data.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                value = content.get("text")
                if isinstance(value, str):
                    chunks.append(value)
    answer = "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
    if not answer:
        raise RuntimeError("OpenAI chat provider returned no text output")
    return answer


def _build_workspace_context(
    *,
    user: dict[str, Any],
    codebase: dict[str, Any] | None,
    codebases: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> str:
    parts = [
        "W2P app context:",
        "- W2P is a whiteboard-to-production engineering workbench.",
        "- Frontend: static HTML/CSS/JavaScript served by FastAPI.",
        "- Backend: Python FastAPI API with local SQLite persistence for users, sessions, codebases, and chat messages.",
        "- Core workflow: login, upload or camera-frame an architecture diagram, choose AWS/Azure/GCP, generate Terraform/backend/container/policy/schema artifacts, validate, save, inspect, and export Terraform.",
        "- Product model: SaaS-style authenticated developer workbench today; not yet a full hosted multi-tenant SaaS platform with billing, teams, quotas, or organization administration.",
        f"- Chat engine: {_engine_description()}.",
        "",
        f"Current user display name: {user.get('name', 'user')}",
        f"Saved codebases: {len(codebases)}",
    ]
    for item in codebases[:8]:
        parts.append(
            f"- {item['name']} | status={item['status']} | provider={item['provider']} | model={item['model']} | updated={item['updated_at']}"
        )

    if codebase is None:
        parts.extend(
            [
                "",
                "Active codebase: none selected.",
                "When no active codebase is selected, answer from the W2P app context and saved-codebase summaries only.",
            ]
        )
    else:
        parts.extend(["", _active_codebase_context(codebase)])

    if history:
        parts.extend(["", "Recent chat history:"])
        for item in history[-12:]:
            parts.append(f"- {item['role']}: {_compact(item['content'], 700)}")

    return _compact("\n".join(parts), _int_env("W2P_CHAT_CONTEXT_CHARS", 24000))


def _active_codebase_context(codebase: dict[str, Any]) -> str:
    topology = TopologySpec.model_validate_json(codebase["topology_json"])
    validation = TerraformValidationResult.model_validate_json(codebase["validation_json"])
    policy_issues = json.loads(codebase["policy_issues_json"])
    files = json.loads(codebase["generated_files_json"])

    parts = [
        f"Active codebase: {codebase['name']}",
        f"- Extraction provider: {codebase['provider']}",
        f"- Extraction model: {codebase['model']}",
        f"- Compile status: {codebase['status']}",
        f"- Topology hash: {codebase['topology_hash']}",
        f"- Deployment: {topology.deployment.provider.upper()} / {topology.deployment.region} / {topology.deployment.environment}",
        "",
        "Topology:",
    ]
    for service in topology.services:
        ports = ", ".join(f"{port.name}:{port.port}/{port.protocol}" for port in service.ports) or "none"
        parts.append(
            "- service "
            f"{service.id}: name={service.name}, kind={service.kind}, runtime={service.runtime}, "
            f"replicas={service.replicas}, ports={ports}, public={service.security.public}, "
            f"auth={service.security.require_auth}, tls={service.security.tls_required}, zone={service.trust_zone}"
        )
    for datastore in topology.datastores:
        parts.append(
            "- datastore "
            f"{datastore.id}: name={datastore.name}, kind={datastore.kind}, encrypted={datastore.encrypted_at_rest}, "
            f"backups={datastore.backups_enabled}, public_access={datastore.public_access}, zone={datastore.trust_zone}"
        )
    for external in topology.external_systems:
        parts.append(f"- external {external.id}: name={external.name}, trusted={external.trusted}, zone={external.trust_zone}")
    for edge in topology.edges:
        parts.append(
            "- edge "
            f"{edge.id}: {edge.from_node} -> {edge.to_node}, protocol={edge.protocol}, "
            f"purpose={edge.purpose}, encrypted={edge.encrypted}, auth={edge.auth_required}"
        )

    parts.extend(["", f"Validation: {validation.status}"])
    for finding in validation.findings:
        parts.append(f"- {finding.severity} {finding.code} on {finding.target}: {finding.message}")
    for check in validation.tool_checks:
        parts.append(f"- tool {check.tool}: {check.status} - {check.summary}")
    if not validation.findings and not validation.tool_checks:
        parts.append("- no validation findings or tool checks recorded")

    parts.extend(["", "Policy issues:"])
    if policy_issues:
        for issue in policy_issues:
            parts.append(f"- {issue['severity']} {issue['code']} on {issue['target']}: {issue['message']}")
    else:
        parts.append("- none")

    parts.extend(["", "Generated files:"])
    for file in sorted(files, key=_file_priority):
        parts.append(f"- {file['path']} ({len(file['content'])} chars)")

    parts.extend(["", "Relevant generated file excerpts:"])
    budget = _int_env("W2P_CHAT_FILE_CONTEXT_CHARS", 12000)
    used = 0
    for file in sorted(files, key=_file_priority):
        remaining = budget - used
        if remaining <= 0:
            break
        excerpt = _compact(file["content"].strip(), min(2200, remaining))
        if not excerpt:
            continue
        parts.append(f"\n--- {file['path']} ---\n{excerpt}")
        used += len(excerpt)

    return "\n".join(parts)


def _local_workspace_answer(
    *,
    message: str,
    user: dict[str, Any],
    codebase: dict[str, Any] | None,
    codebases: list[dict[str, Any]],
) -> str:
    normalized = message.lower()
    engine = _engine_description()

    if codebase is None:
        if any(token in normalized for token in ["model", "saas", "software", "app", "business", "product"]):
            return (
                "There are two models here.\n\n"
                f"AI model: {engine}. Set OPENAI_API_KEY and optionally W2P_CHAT_MODEL to use the live LLM path.\n\n"
                "Product model: W2P is a SaaS-style authenticated developer workbench: users sign in, generate codebases, "
                "save history, inspect Terraform/backend/container/policy/schema files, and chat over that workspace. "
                "In this repo it is still a local/dev workbench, not a complete hosted SaaS business system yet. "
                "Missing SaaS-production pieces include organizations/teams, billing, quotas, admin roles, hosted tenant isolation, "
                "observability, and deployment automation."
            )
        if any(token in normalized for token in ["analy", "architecture", "built", "stack", "how it works"]):
            return (
                "W2P is built as a FastAPI-backed workbench with a static frontend and SQLite persistence. "
                "The main software flow is: authenticate, choose a deployment target, upload a diagram, extract topology, "
                "compile Terraform/backend/container/policy/schema artifacts, validate Terraform, save the codebase, then inspect or export it. "
                f"You currently have {len(codebases)} saved codebase(s). Select one and I can analyze its generated files in detail."
            )
        return (
            f"I can analyze the W2P workspace, but no codebase is selected right now. {engine}. "
            "Ask about the W2P product model, or select a saved codebase so I can inspect its topology, Terraform, generated files, and validation findings."
        )

    topology = TopologySpec.model_validate_json(codebase["topology_json"])
    validation = TerraformValidationResult.model_validate_json(codebase["validation_json"])
    files = json.loads(codebase["generated_files_json"])
    terraform_files = [file for file in files if file["path"].startswith("terraform/")]

    if any(token in normalized for token in ["model", "saas", "software", "app", "product"]):
        return (
            f"{codebase['name']} is generated as a cloud-native application scaffold, not a full SaaS platform by itself. "
            f"It currently has {len(topology.services)} service(s), {len(topology.datastores)} datastore(s), "
            f"{len(topology.edges)} connection(s), and targets {topology.deployment.provider.upper()} in {topology.deployment.region}. "
            "To become a true SaaS app, the generated topology would need explicit tenant/user/billing/admin services or modules. "
            f"The chat engine answering this is: {engine}."
        )
    if any(token in normalized for token in ["fix", "risk", "validation", "error", "issue", "secure"]):
        error_count = sum(1 for item in validation.findings if item.severity == "error")
        warning_count = sum(1 for item in validation.findings if item.severity == "warning")
        return (
            f"{codebase['name']} validation is {validation.status}: {error_count} error(s) and {warning_count} warning(s). "
            "Review the verification panel first, then inspect Terraform variables/secrets/networking before production. "
            "For a deeper answer, configure OPENAI_API_KEY so the assistant can reason over the generated file excerpts."
        )
    return (
        f"I analyzed the selected codebase: {codebase['name']}. It targets {topology.deployment.provider.upper()} "
        f"/ {topology.deployment.region} / {topology.deployment.environment}, includes {len(files)} generated artifact(s), "
        f"and has {len(terraform_files)} Terraform file(s). Validation status is {validation.status}. "
        "Ask me about architecture, SaaS readiness, Terraform, risks, or production gaps for this codebase."
    )


def _engine_description() -> str:
    if os.getenv("OPENAI_API_KEY"):
        return f"OpenAI Responses API using {_chat_model()}"
    return "local workspace analyzer because OPENAI_API_KEY is not configured"


def _suggestions(codebase: dict[str, Any] | None) -> list[str]:
    if codebase is None:
        return [
            "What model does W2P follow?",
            "Analyze this software architecture",
            "What is missing for SaaS production?",
        ]
    return [
        "Is this SaaS-ready?",
        "Review architecture risks",
        "Explain the Terraform output",
    ]


def _file_priority(file: dict[str, Any]) -> tuple[int, str]:
    path = file["path"]
    if path.startswith("terraform/") and path.endswith(".tf"):
        return (0, path)
    if path.startswith("backend/"):
        return (1, path)
    if path.startswith("container/"):
        return (2, path)
    if path.startswith("policy/"):
        return (3, path)
    if path.startswith("schema/"):
        return (4, path)
    return (5, path)


def _compact(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: max(0, limit - 80)].rstrip()}\n...[truncated {len(value) - limit} chars]"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
