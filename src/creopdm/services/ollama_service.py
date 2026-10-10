"""Talk to a local or LAN Ollama server (list models; chat)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from creopdm.exceptions import ValidationAppError

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_CHAT_TIMEOUT_S = 300.0


def normalize_ollama_base_url(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return DEFAULT_OLLAMA_BASE_URL
    if "://" not in text:
        # Allow host:port without scheme (common when pasting from Ollama docs).
        text = f"http://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "Ollama host URL must look like http://127.0.0.1:11434 or http://hostname:11434."
        )
    return text.rstrip("/")


def list_ollama_models(base_url: str, *, timeout_s: float = 5.0) -> list[str]:
    """GET /api/tags on the Ollama host. Raises ValidationAppError when unreachable."""
    try:
        root = normalize_ollama_base_url(base_url)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc
    url = f"{root}/api/tags"
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise ValidationAppError(
            f"Could not reach Ollama at {root}. Is Ollama running and reachable from this CreoPDM server?",
            details={"url": url, "error": str(exc)},
        ) from exc
    if response.status_code >= 400:
        raise ValidationAppError(
            f"Ollama returned HTTP {response.status_code} for {url}.",
            details={"url": url, "status": response.status_code},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValidationAppError(
            "Ollama /api/tags did not return JSON.",
            details={"url": url},
        ) from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ValidationAppError(
            "Ollama /api/tags response was missing a models list.",
            details={"url": url},
        )
    names: list[str] = []
    seen: set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    names.sort(key=str.lower)
    return names


def chat_ollama(
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout_s: float = DEFAULT_OLLAMA_CHAT_TIMEOUT_S,
    num_predict: int = 256,
) -> str:
    """POST /api/chat (non-streaming). Returns the assistant message text.

    Default ``num_predict`` stays short for check-in comments. Snapshot
    Ask AI passes a higher limit so long component/dimension lists are not
    cut off mid-sentence.
    """
    try:
        root = normalize_ollama_base_url(base_url)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc
    model_name = str(model or "").strip()
    if not model_name:
        raise ValidationAppError(
            "No Ollama model selected. Open System Settings → AI, Refresh models, choose a model, and Save."
        )
    if not messages:
        raise ValidationAppError("Ollama chat requires at least one message.")
    predict = max(32, int(num_predict or 256))
    url = f"{root}/api/chat"
    body: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        # Check-in comments need a short answer, not a long think chain.
        "think": False,
        # Keep change notices factual; higher temperature drifts into generic fluff.
        "options": {"temperature": 0, "num_predict": predict},
    }
    timeout = httpx.Timeout(
        connect=min(30.0, float(timeout_s)),
        read=float(timeout_s),
        write=min(120.0, float(timeout_s)),
        pool=30.0,
    )
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, json=body)
    except httpx.HTTPError as exc:
        raise ValidationAppError(
            f"Could not reach Ollama at {root} for chat. Is Ollama running and reachable from this CreoPDM server?",
            details={"url": url, "error": str(exc)},
        ) from exc
    if response.status_code >= 400:
        detail = (response.text or "").strip()[:300]
        raise ValidationAppError(
            f"Ollama chat returned HTTP {response.status_code}."
            + (f" {detail}" if detail else ""),
            details={"url": url, "status": response.status_code},
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValidationAppError(
            "Ollama /api/chat did not return JSON.",
            details={"url": url},
        ) from exc
    message = payload.get("message") if isinstance(payload, dict) else None
    content = ""
    if isinstance(message, dict):
        content = str(message.get("content") or "").strip()
    if not content and isinstance(payload, dict):
        content = str(payload.get("response") or "").strip()
    if not content:
        raise ValidationAppError(
            "Ollama returned an empty chat response.",
            details={"url": url, "model": model_name},
        )
    return content
