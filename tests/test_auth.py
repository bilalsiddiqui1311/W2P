from __future__ import annotations

from w2p.api import (
    assistant_query,
    chat_history,
    clear_chat_history,
    send_chat_message,
    signup,
    update_profile,
)
from w2p.app_models import AssistantQueryRequest, ChatRequest, ProfileUpdateRequest, SignupRequest
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


def test_profile_update_changes_name_and_email(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("W2P_DB_PATH", str(tmp_path / "profile.sqlite3"))
    initialize_storage()
    response = signup(SignupRequest(email="profile@example.com", password="StrongPass123"))

    updated = update_profile(
        ProfileUpdateRequest(email="updated@example.com", name="Updated User"),
        user=response.user.model_dump(),
    )

    assert updated.name == "Updated User"
    assert updated.email == "updated@example.com"


def test_assistant_query_returns_local_answer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("W2P_DB_PATH", str(tmp_path / "assistant.sqlite3"))
    initialize_storage()
    response = signup(SignupRequest(email="assistant@example.com", password="StrongPass123"))

    answer = assistant_query(
        AssistantQueryRequest(message="Which model is active?"),
        user=response.user.model_dump(),
    )

    assert "local deterministic" in answer.answer


def test_authenticated_chat_persists_and_clears_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("W2P_DB_PATH", str(tmp_path / "chat.sqlite3"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    initialize_storage()
    response = signup(SignupRequest(email="chat@example.com", name="Ada", password="StrongPass123"))
    user = response.user.model_dump()

    result = send_chat_message(ChatRequest(message="which model it follows? SaaS or what?"), user=user)

    assert result.user_message.role == "user"
    assert result.assistant_message.role == "assistant"
    assert "SaaS-style" in result.assistant_message.content
    assert "OPENAI_API_KEY" in result.assistant_message.content
    assert result.suggestions

    history = chat_history(user=user)
    assert [item.role for item in history] == ["user", "assistant"]
    assert history[0].content == "which model it follows? SaaS or what?"

    clear_chat_history(user=user)
    assert chat_history(user=user) == []


def test_chat_uses_configured_llm_with_workspace_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("W2P_DB_PATH", str(tmp_path / "chat-llm.sqlite3"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("W2P_CHAT_MODEL", "test-chat-model")
    initialize_storage()
    response = signup(SignupRequest(email="llm-chat@example.com", name="Grace", password="StrongPass123"))
    user = response.user.model_dump()
    captured: dict[str, str] = {}

    def fake_openai_response_text(*, api_key: str, model: str, prompt: str, instructions: str) -> str:
        captured["api_key"] = api_key
        captured["model"] = model
        captured["prompt"] = prompt
        captured["instructions"] = instructions
        return "LLM answer based on workspace context."

    monkeypatch.setattr("w2p.ai.chatbot._openai_response_text", fake_openai_response_text)

    result = send_chat_message(ChatRequest(message="Analyze this software"), user=user)

    assert result.assistant_message.content == "LLM answer based on workspace context."
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "test-chat-model"
    assert "W2P app context" in captured["prompt"]
    assert "Analyze this software" in captured["prompt"]
