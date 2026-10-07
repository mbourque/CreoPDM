"""Talk to a local or LAN Ollama server (list models; chat comes later)."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from creopdm.exceptions import ValidationAppError

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


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
