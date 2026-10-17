"""Deploy stamp for the client scripts.

Soft-nav keeps the in-memory ``/client/app.js`` and only swaps it when the script ``src``
(its ``?v=``) changes. That string used to be the static app version, so after a deploy a
hard reload was still needed. The stamp below is a content hash of ``static/js/*.js`` taken
when the process starts, baked into the page, so every deploy changes the ``src`` and the
page (and its lazy modules, which reuse the ``?v=``) picks up the new code on the next
soft-nav.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_client_js_stamp(js_dir: Path) -> str:
    """Short content hash of every top-level ``*.js`` in ``js_dir`` ("0" when unreadable)."""
    digest = hashlib.sha1()
    try:
        files = sorted(Path(js_dir).glob("*.js"))
    except OSError:
        return "0"
    if not files:
        return "0"
    for path in files:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha1(data).digest())
    return digest.hexdigest()[:10]


CLIENT_JS_STAMP = compute_client_js_stamp(Path(__file__).resolve().parent / "static" / "js")
