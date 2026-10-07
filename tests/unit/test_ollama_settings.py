"""Ollama AI settings: URL normalize, model list proxy, persist."""

from __future__ import annotations

import httpx
import pytest

from creopdm.config import AiConfig, AppSettings
from creopdm.exceptions import ValidationAppError
from creopdm.services.ollama_service import chat_ollama, list_ollama_models, normalize_ollama_base_url


def test_normalize_ollama_base_url_defaults_and_scheme():
    assert normalize_ollama_base_url("") == "http://127.0.0.1:11434"
    assert normalize_ollama_base_url("http://michael-desktop:11434/") == (
        "http://michael-desktop:11434"
    )
    assert normalize_ollama_base_url("michael-desktop:11434") == (
        "http://michael-desktop:11434"
    )
    with pytest.raises(ValueError):
        normalize_ollama_base_url("ftp://bad")


def test_ai_config_round_trip_in_app_settings():
    settings = AppSettings.model_validate(
        {
            "ai": {
                "ollama_base_url": "http://michael-desktop:11434",
                "ollama_model": "gemma4:latest",
            }
        }
    )
    assert settings.ai.ollama_base_url == "http://michael-desktop:11434"
    assert settings.ai.ollama_model == "gemma4:latest"
    # Missing ai block still loads.
    bare = AppSettings.model_validate({})
    assert isinstance(bare.ai, AiConfig)
    assert bare.ai.ollama_base_url == "http://127.0.0.1:11434"


def test_list_ollama_models_parses_tags(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "models": [
                    {"name": "gemma4:latest"},
                    {"name": "llama3.2:latest"},
                    {"name": "gemma4:latest"},
                ]
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url.endswith("/api/tags")
            return FakeResponse()

    monkeypatch.setattr("creopdm.services.ollama_service.httpx.Client", FakeClient)
    names = list_ollama_models("http://michael-desktop:11434")
    assert names == ["gemma4:latest", "llama3.2:latest"]


def test_list_ollama_models_unreachable(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            raise httpx.ConnectError(
                "refused",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr("creopdm.services.ollama_service.httpx.Client", FakeClient)
    with pytest.raises(ValidationAppError) as exc:
        list_ollama_models("http://127.0.0.1:11434")
    assert "Could not reach Ollama" in str(exc.value)


def test_chat_ollama_posts_messages(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"message": {"role": "assistant", "content": "  Diameter grew.  "}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, json=None):
            assert url.endswith("/api/chat")
            assert json["model"] == "gemma4:latest"
            assert json["stream"] is False
            assert json["options"]["temperature"] == 0
            assert json["messages"][0]["role"] == "system"
            return FakeResponse()

    monkeypatch.setattr("creopdm.services.ollama_service.httpx.Client", FakeClient)
    text = chat_ollama(
        "http://michael-desktop:11434",
        "gemma4:latest",
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
    )
    assert text == "Diameter grew."


def test_chat_ollama_requires_model():
    with pytest.raises(ValidationAppError) as exc:
        chat_ollama("http://127.0.0.1:11434", "", [{"role": "user", "content": "hi"}])
    assert "No Ollama model" in str(exc.value)


def test_settings_api_persists_ollama_fields(client):
    before = client.get("/api/settings")
    assert before.status_code == 200
    assert before.json()["ollama_base_url"] == "http://127.0.0.1:11434"
    assert before.json()["ollama_model"] == ""

    saved = client.put(
        "/api/settings",
        json={
            "ollama_base_url": "http://michael-desktop:11434",
            "ollama_model": "gemma4:latest",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["ollama_base_url"] == "http://michael-desktop:11434"
    assert body["ollama_model"] == "gemma4:latest"

    again = client.get("/api/settings")
    assert again.json()["ollama_base_url"] == "http://michael-desktop:11434"
    assert again.json()["ollama_model"] == "gemma4:latest"


def test_ollama_models_endpoint_uses_query_override(client, monkeypatch):
    def fake_list(base_url, *, timeout_s=5.0):
        assert base_url == "http://override:11434"
        return ["gemma4:latest"]

    monkeypatch.setattr("creopdm.api.settings.list_ollama_models", fake_list)
    response = client.get(
        "/api/settings/ai/ollama/models",
        params={"base_url": "http://override:11434"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["base_url"] == "http://override:11434"
    assert payload["models"] == ["gemma4:latest"]


def test_ai_settings_page_renders(client):
    page = client.get("/settings/ai")
    assert page.status_code == 200
    assert "Ollama host URL" in page.text
    assert 'name="ollama_base_url"' in page.text
    assert 'id="ollama-refresh-models"' in page.text
