"""Convert product Search box text into SQL ILIKE patterns.

Plain text stays a substring match (``pin`` → ``%pin%``).
When the query includes ``*`` or ``?``, treat it as a common glob:
``*.prt``, ``*``, ``*.*``, ``*.prt.*``, ``shaft?``.
"""

from __future__ import annotations


def sql_like_from_search_query(query: str | None) -> str | None:
    """Return an ILIKE pattern, or None when there is nothing to search for.

    Use with ``column.ilike(pattern, escape="\\\\")``.
    """
    text = str(query or "").strip()
    if not text:
        return None

    def escape_like(chunk: str) -> str:
        return (
            chunk.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )

    if "*" in text or "?" in text:
        parts: list[str] = []
        for ch in text:
            if ch == "*":
                parts.append("%")
            elif ch == "?":
                parts.append("_")
            elif ch in {"%", "_", "\\"}:
                parts.append("\\" + ch)
            else:
                parts.append(ch)
        return "".join(parts)
    return f"%{escape_like(text)}%"
