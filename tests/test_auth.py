from __future__ import annotations

from w2p.api import signup
from w2p.app_models import SignupRequest
from w2p.storage import initialize_storage


def test_signup_defaults_name_from_email(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("W2P_DB_PATH", str(tmp_path / "auth.sqlite3"))
    initialize_storage()

    response = signup(
        SignupRequest(
            email="name-default@example.com",
            password="StrongPass123",
        )
    )

    assert response.user.name == "name-default"
    assert response.user.email == "name-default@example.com"
    assert response.token
