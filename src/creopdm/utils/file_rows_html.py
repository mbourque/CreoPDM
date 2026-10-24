"""The Files list rows (folders first, then files) as HTML.

Built here, not in a template: a big product's list is thousands of rows of ~30 attributes each, and
filling them through Jinja costs several times more than building the strings directly. The markup
is what the page scripts, the sort and the search read (``data-*`` keys, cell order) — change it
only together with ``tests/unit/test_file_rows_html.py``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from markupsafe import Markup, escape

from creopdm.utils.timefmt import as_utc, format_local_pretty

_FOLDER_ICON = (
    '<svg class="folder-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.2A2.2 2.2 0 0 1 '
    "5.7 5h4.1c.4 0 .8.2 1 .5l1.3 1.4c.3.3.6.5 1 .5h5.2A2.2 2.2 0 0 1 20.5 9.6v8.2a2.2 2.2 0 0 1-2.2 "
    '2.2H5.7A2.2 2.2 0 0 1 3.5 17.8V7.2Z"/></svg>'
)


def _e(value: Any) -> str:
    """Escape like ``{{ value }}`` does (None shows as ``None``, as it does in a template).

    The same entities as markupsafe; a plain string takes the faster replace chain.
    """
    if value.__class__ is not str:
        return escape(value)
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&#34;")


def _flag(source: Any, name: str) -> bool:
    if isinstance(source, dict):
        return bool(source.get(name))
    return bool(getattr(source, name, False))


def _local(value: Any):
    utc = as_utc(value)
    return utc.astimezone() if utc is not None else None


def _folder_row(entry: dict, selected_uuid: str, show_checkout: bool) -> str:
    path = entry["path"]
    name = entry["name"]
    object_ids = entry.get("object_ids") or ()
    depth = entry.get("depth", 0)
    modified = entry.get("modified")
    local = _local(modified) if modified else None
    sort_modified = local.strftime("%Y%m%d%H%M%S") if local is not None else ""
    modified_title = format_local_pretty(modified) if modified else ""
    if modified:
        modified_text = local.strftime("%Y-%m-%d %H:%M") if local is not None else ""
    else:
        modified_text = "—"
    count = entry.get("count", 0)
    path_e = _e(path)
    ids_text = ",".join(str(item) for item in object_ids)
    can_checkout = "1" if show_checkout and object_ids else "0"
    plural = "" if count == 1 else "s"
    href = f"/?product={_e(selected_uuid)}&amp;folder={_e(quote(path, safe='/'))}"
    return (
        f'<tr class="folder-row" data-folder="{path_e}" data-object-ids="{_e(ids_text)}"'
        f' data-can-checkout="{can_checkout}" data-can-checkin="0" data-owned="0"'
        f' data-checked-out="0" data-in-workspace="mixed" data-depth="{_e(depth)}"'
        f' data-sort-name="{path_e}/" data-sort-rev="{path_e}/" data-sort-state="{path_e}/"'
        f' data-sort-type="{path_e}/" data-sort-creo="{path_e}/" data-sort-modified="{sort_modified}"'
        f' data-sort-checkout="{path_e}/" style="--depth: {_e(depth)}"'
        ' title="Click the folder name to open. Click elsewhere to select. Double-click to open.">'
        f'<td title="{_e(name)}"><a class="folder-open" href="{href}"'
        f' data-folder="{path_e}" title="Open {_e(name)}"><span class="folder-label">{_FOLDER_ICON}'
        f'<span class="folder-name">{_e(name)}</span></span></a>'
        f'<div class="muted small folder-count">{_e(count)} file{plural}</div></td>'
        f'<td></td><td></td><td title="Folder">Folder</td><td></td>'
        f'<td title="{_e(modified_title)}">{_e(modified_text)}</td><td></td></tr>'
    )


def _file_row(
    entry: dict,
    selected_uuid: str,
    show_revise: bool,
    where_used_present: bool,
    top_level: frozenset,
) -> str:
    obj = entry["object"]
    folder_e = _e(entry["folder"])
    depth = entry["depth"]
    uuid = obj.uuid
    state = obj.lifecycle_state
    version = obj.current_version
    # Values that appear more than once in the row are escaped once.
    uuid_e = _e(uuid)
    filename_e = _e(obj.filename)
    extension_e = _e(obj.extension)
    state_e = _e(state)
    revision_e = _e(obj.display_revision)
    creo_e = _e(obj.creo_release or "")
    type_label_e = _e(obj.type_label)
    checkout_status_e = _e(obj.checkout_status)
    relative_e = _e(obj.relative_path)
    updated = obj.updated_at
    if updated:
        local = _local(updated)
        sort_modified = local.strftime("%Y%m%d%H%M%S")
        modified_title = format_local_pretty(updated)
        modified_text = local.strftime("%Y-%m-%d %H:%M")
    else:
        sort_modified = modified_title = ""
        modified_text = "—"
    # Modified shows for any file that is not held by someone else (checked out or not).
    state_modified = bool(obj.modified_locally and (obj.owned_by_me or obj.can_checkin or not obj.checkout_user))
    if state_modified:
        sort_state = "0-MODIFIED"
        shown_state = "Modified"
        data_state = "MODIFIED"
    else:
        sort_state = "1-IN_WORK" if state == "IN_WORK" else f"2-{_e(state)}"
        shown_state = _e(state.replace("_", " ").title())
        data_state = state_e
    if obj.owned_by_me:
        checkout_kind = "mine"
    elif obj.checkout_user:
        checkout_kind = "other"
    elif obj.can_checkout:
        checkout_kind = "available"
    else:
        checkout_kind = "locked"
    if obj.type_icon:
        icon = (
            f'<img class="type-icon" src="/static/icons/{_e(obj.type_icon)}" alt="{type_label_e}"'
            f' title="{type_label_e}" width="14" height="14" decoding="async">'
        )
    else:
        icon = ""
    content_hash = version.content_hash if version else ""
    can_revise = "1" if show_revise and obj.can_revise else "0"
    top = "1" if where_used_present and uuid in top_level else "0"
    return (
        f'<tr data-uuid="{uuid_e}" data-object-type="{_e(obj.object_type)}" data-extension="{extension_e}"'
        f' data-filename="{filename_e}" data-number="{_e(obj.number or "")}" data-subtype="{_e(obj.model_role)}"'
        f' data-model="{_e(obj.model_type)}" data-lifecycle="{state_e}" data-rev="{revision_e}"'
        f' data-creo="{creo_e}" data-content-hash="{_e(content_hash)}"'
        f' data-relative-path="{relative_e}" data-can-checkout="{"1" if obj.can_checkout else "0"}"'
        f' data-can-checkin="{"1" if obj.can_checkin else "0"}" data-can-revise="{can_revise}"'
        f' data-owned="{"1" if obj.owned_by_me else "0"}"'
        f' data-checked-out="{"1" if obj.owned_by_me or obj.checkout_user else "0"}"'
        f' data-modified-locally="{"1" if obj.modified_locally else "0"}"'
        f' data-in-workspace="{"1" if obj.in_workspace else "0"}"'
        f' data-top-level-assembly="{top}"'
        f' data-tree="{folder_e}" data-sort-name="{relative_e}"'
        f' data-sort-rev="{folder_e}/{_e(obj.revision)}-{obj.iteration:06d}"'
        f' data-sort-state="{folder_e}/{sort_state}" data-sort-type="{folder_e}/{type_label_e}"'
        f' data-sort-creo="{folder_e}/{creo_e}" data-sort-modified="{sort_modified}"'
        f' data-sort-checkout="{folder_e}/{checkout_status_e}"'
        f' data-detail="/products/{_e(selected_uuid)}/objects/{uuid_e}" class="object-row"'
        f' style="--depth: {_e(depth)}"><td><span class="name-with-icon">{icon}'
        f'<button type="button" class="object-open" data-uuid="{uuid_e}" data-filename="{filename_e}"'
        f' data-extension="{extension_e}">{filename_e}</button></span></td>'
        f'<td title="{revision_e}">{revision_e}</td>'
        f'<td title="{shown_state}"><span class="state" data-state="{data_state}"'
        f' data-lifecycle-state="{state_e}">{shown_state}</span></td>'
        f'<td title="{type_label_e}">{type_label_e}</td>'
        f'<td title="{creo_e}">{creo_e}</td>'
        f'<td title="{_e(modified_title)}">{modified_text}</td>'
        f'<td title="{checkout_status_e}"><span class="checkout-state" data-state="{checkout_kind}">'
        f"{checkout_status_e}</span></td></tr>"
    )


def render_file_rows(
    entries: list[dict],
    *,
    selected_uuid: str,
    product_ui: Any,
    where_used_present: bool = False,
    top_level_assembly_uuids: Any = (),
) -> Markup:
    """Rows for folder and file entries, in order (see ``folder_list_entries``)."""
    show_checkout = _flag(product_ui, "show_checkout")
    show_revise = _flag(product_ui, "show_revise")
    top_level = frozenset(top_level_assembly_uuids or ())
    parts: list[str] = []
    for entry in entries:
        if entry.get("kind") == "folder":
            parts.append(_folder_row(entry, selected_uuid, show_checkout))
        else:
            parts.append(_file_row(entry, selected_uuid, show_revise, where_used_present, top_level))
    return Markup("\n".join(parts))
