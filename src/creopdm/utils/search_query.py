"""Convert product Search box text into SQL ILIKE patterns.

Plain text stays a substring match (``pin`` → ``%pin%``).
When the query includes ``*`` or ``?``, treat it as a common glob:
``*.prt``, ``*``, ``*.*``, ``*.prt.*``, ``shaft?``.

Optional anchors (not full regex):
``^CAD/`` starts with, ``.prt$`` ends with, ``^shaft.prt$`` exact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


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


# --------------------------------------------------------------------------- field search
# The Files search box understands ``field=value`` terms next to plain text:
#   type=bulk   subtype=bulk   name=*shaft*   state=released   rev=A.2   param.MATERIAL=steel*
# Terms are separated by spaces and ALL must match; double quotes keep spaces (name="my part").
# ``=`` is an exact match (case-insensitive); ``*`` / ``?`` make a partial match. A plain term (no field)
# is a substring match on the file name, number, path, Type label and Subtype label only.
# files_search_match.js implements the same grammar for the rows already on screen.

SEARCH_FIELDS = ("name", "number", "path", "type", "subtype", "model", "state", "rev", "creo")
PARAM_PREFIX = "param."


@dataclass(frozen=True)
class SearchTerm:
    """One search term: a plain substring (``field`` is None) or ``field=value``."""

    field: str | None
    value: str
    param_name: str = ""


def split_search_terms(text: str | None) -> list[str]:
    """Split on spaces; double quotes keep spaces inside a term (the quotes themselves are dropped)."""
    terms: list[str] = []
    current: list[str] = []
    quoted = False
    started = False
    for ch in str(text or ""):
        if ch == '"':
            quoted = not quoted
            started = True
            continue
        if ch.isspace() and not quoted:
            if started:
                terms.append("".join(current))
                current = []
                started = False
            continue
        current.append(ch)
        started = True
    if started:
        terms.append("".join(current))
    return [term for term in terms if term != ""]


def parse_search_query(text: str | None) -> list[SearchTerm]:
    """Terms of a search box text. A ``field=`` with nothing after it is ignored while it is typed."""
    terms: list[SearchTerm] = []
    for token in split_search_terms(text):
        index = token.find("=")
        if index > 0:
            field = token[:index].strip().lower()
            value = token[index + 1 :]
            if field in SEARCH_FIELDS:
                if value.strip():
                    terms.append(SearchTerm(field=field, value=value.strip()))
                continue
            if field.startswith(PARAM_PREFIX) and len(field) > len(PARAM_PREFIX):
                if value.strip():
                    terms.append(
                        SearchTerm(
                            field="param",
                            value=value.strip(),
                            param_name=token[:index].strip()[len(PARAM_PREFIX) :],
                        )
                    )
                continue
        terms.append(SearchTerm(field=None, value=token))
    return terms


def _anchors(raw: str) -> tuple[str, bool, bool]:
    body = raw
    start = body.startswith("^")
    if start:
        body = body[1:]
    end = body.endswith("$")
    if end:
        body = body[:-1]
    return body, start, end


def _glob_regex(body: str) -> re.Pattern[str]:
    pattern = "".join(
        ".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in body
    )
    return re.compile(f"^{pattern}$", re.IGNORECASE | re.DOTALL)


def text_matches(candidate: str | None, raw: str, *, exact: bool) -> bool:
    """One value against one pattern: ``exact`` for a ``field=value`` term, substring for plain text."""
    body, start, end = _anchors(str(raw or "").strip())
    if not body:
        return True
    text = str(candidate or "")
    if "*" in body or "?" in body:
        return bool(_glob_regex(body).match(text))
    text = text.lower()
    needle = body.lower()
    if start and end:
        return text == needle
    if start:
        return text.startswith(needle)
    if end:
        return text.endswith(needle)
    return text == needle if exact else needle in text


def object_search_fields(obj, type_label: str) -> dict[str, list[str]]:
    """The values a search term can look at, per field (several spellings for state / revision)."""
    from creopdm.utils.creo_model_class import model_fields_from_identity_json

    version = getattr(obj, "current_version", None)
    model, subtype = model_fields_from_identity_json(
        getattr(version, "identity_json", None) if version is not None else None
    )
    state = str(getattr(obj, "lifecycle_state", "") or "")
    revision = str(getattr(obj, "revision", "") or "")
    iteration = getattr(obj, "iteration", None)
    return {
        "name": [str(getattr(obj, "filename", "") or ""), str(getattr(obj, "name", "") or "")],
        "number": [str(getattr(obj, "number", "") or "")],
        "path": [str(getattr(obj, "relative_path", "") or "")],
        "type": [str(type_label or "")],
        "subtype": [subtype],
        "model": [model],
        "state": [state, state.replace("_", " ")],
        "rev": [revision, f"{revision}.{iteration}" if iteration is not None else revision],
        "creo": [str(getattr(version, "creo_release", "") or "") if version is not None else ""],
    }


def object_matches_search(
    terms: list[SearchTerm],
    fields: dict[str, list[str]],
    params: dict[str, str] | None = None,
) -> bool:
    """Every term must match. ``params`` is {parameter name: value} of the file's current version."""
    for term in terms:
        if term.field is None:
            haystack = (
                fields["name"] + fields["number"] + fields["path"] + fields["type"] + fields["subtype"]
            )
            if not any(text_matches(item, term.value, exact=False) for item in haystack if item):
                return False
        elif term.field == "param":
            hit = False
            for name, value in (params or {}).items():
                if text_matches(name, term.param_name, exact=True) and text_matches(
                    value, term.value, exact=True
                ):
                    hit = True
                    break
            if not hit:
                return False
        else:
            if not any(text_matches(item, term.value, exact=True) for item in fields.get(term.field, [])):
                return False
    return True
