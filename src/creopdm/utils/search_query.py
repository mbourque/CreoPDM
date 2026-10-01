"""Convert product Search box text into SQL ILIKE patterns.

Plain text stays a substring match (``pin`` → ``%pin%``).
When the query includes ``*`` or ``?``, treat it as a common glob:
``*.prt``, ``*``, ``*.*``, ``*.prt.*``, ``shaft?``.

Optional anchors (not full regex):
``^CAD/`` starts with, ``.prt$`` ends with, ``^shaft.prt$`` exact.
"""

from __future__ import annotations


def sql_like_from_search_query(query: str | None) -> str | None:
    """Return an ILIKE pattern, or None when there is nothing to search for.

    Use with ``column.ilike(pattern, escape="\\\\")``.
    """
    text = str(query or "").strip()
    if not text:
        return None

    anchored_start = text.startswith("^")
    body = text[1:] if anchored_start else text
    anchored_end = body.endswith("$")
    if anchored_end:
        body = body[:-1]
    if not body:
        return None

    def escape_like(chunk: str) -> str:
        return (
            chunk.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

    if "*" in body or "?" in body:
        parts: list[str] = []
        for ch in body:
            if ch == "*":
                parts.append("%")
            elif ch == "?":
                parts.append("_")
            elif ch in {"%", "_", "\\"}:
                parts.append("\\" + ch)
            else:
                parts.append(ch)
        return "".join(parts)

    escaped = escape_like(body)
    if anchored_start and anchored_end:
        return escaped
    if anchored_start:
        return f"{escaped}%"
    if anchored_end:
        return f"%{escaped}"
    return f"%{escaped}%"
