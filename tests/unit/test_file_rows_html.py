"""The Files list rows are built as strings; this pins the exact markup the page scripts rely on.

The expected HTML was produced by the Jinja template these rows used to come from, for rows that
cover every branch (folders, checked out by me / by someone else, modified, released, missing
data, special characters). Times are written as @TOKENS@ and filled in with this PC's clock.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from creopdm.utils.file_rows_html import render_file_rows
from creopdm.utils.timefmt import format_local, format_local_pretty

STAMP = datetime(2026, 7, 23, 17, 30, 5, tzinfo=timezone.utc)
FOLDER_STAMP = datetime(2026, 6, 1, 8, 15, 0, tzinfo=timezone.utc)


def _obj(**kw):
    base = dict(
        uuid="u-1", object_type="CREO_PART", extension=".prt", filename="shaft.prt", number="N-1",
        model_role="", model_type="PART", lifecycle_state="IN_WORK", display_revision="A.1",
        revision="A", iteration=1, creo_release="Creo 10", relative_path="shaft.prt",
        can_checkout=True, can_checkin=False, can_revise=True, owned_by_me=False, checkout_user=None,
        checkout_status="Available", modified_locally=False, in_workspace=True, type_label="Part",
        type_icon="part.png", updated_at=STAMP,
        current_version=SimpleNamespace(content_hash="abc123"),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _file(folder="", **kw):
    return {"kind": "file", "object": _obj(**kw), "folder": folder, "depth": 0}


CASES = {
    "plain_file": ([_file()], dict(show_checkout=True, show_revise=True), False, []),
    "mine_modified": (
        [_file(uuid="u-2", filename="gear.prt", relative_path="sub/gear.prt", owned_by_me=True,
                    checkout_user="me", checkout_status="Checked out by me", modified_locally=True,
                    can_checkin=True, can_checkout=False, iteration=12, display_revision="A.12",
                    folder="sub")],
        dict(show_checkout=True, show_revise=False), False, []),
    "other_released_odd_name": (
        [_file(uuid="u-3", filename='a&b <x> "q" \'z\'.prt', relative_path="odd/a&b <x> \"q\" 'z'.prt",
                    lifecycle_state="RELEASED", checkout_user="sam", checkout_status="Checked out by sam",
                    can_checkout=False, number=None, model_role="SHEETMETAL", model_type="PART",
                    type_label="Sheet <metal>", folder="odd")],
        dict(show_checkout=False, show_revise=True), False, []),
    "bare_assembly_top_level": (
        [_file(uuid="u-4", object_type="CREO_ASSEMBLY", extension=".asm", filename="plate.asm.3",
                    relative_path="plate.asm.3", lifecycle_state="OBSOLETE", can_checkout=False,
                    checkout_status="Obsolete", type_label="Assembly", type_icon="", creo_release=None,
                    updated_at=None, current_version=None, in_workspace=False, can_revise=False)],
        dict(show_checkout=True, show_revise=True), True, ["u-4"]),
    "under_change_locked": (
        [_file(uuid="u-5", lifecycle_state="UNDER_CHANGE", can_checkout=False,
                    checkout_status="In Review", display_revision="B.2", revision="B", iteration=2)],
        dict(show_checkout=True, show_revise=True), True, ["someone-else"]),
    "folders": (
        [
            {"kind": "folder", "name": "Ünï cödé", "path": "Ünï cödé", "depth": 0, "count": 3,
             "modified": FOLDER_STAMP, "object_ids": ["a", "b", "c"]},
            {"kind": "folder", "name": "a&b", "path": "x/a&b", "depth": 0, "count": 1,
             "modified": None, "object_ids": []},
        ],
        dict(show_checkout=True, show_revise=False), False, []),
    "folders_no_checkout_flag": (
        [{"kind": "folder", "name": "docs", "path": "docs", "depth": 0, "count": 2,
          "modified": FOLDER_STAMP, "object_ids": ["a", "b"]}],
        dict(show_checkout=False, show_revise=False), False, []),
    "mixed_order": (
        [{"kind": "folder", "name": "docs", "path": "docs", "depth": 0, "count": 2,
          "modified": FOLDER_STAMP, "object_ids": ["a"]},
         _file(uuid="u-6", filename="b.prt"), _file(uuid="u-7", filename="c.prt")],
        dict(show_checkout=True, show_revise=True), False, []),
}

EXPECTED = {
    'plain_file': (
        '<tr data-uuid="u-1" data-object-type="CREO_PART" data-extension=".prt" data-filename="shaft.prt" dat'
        'a-number="N-1" data-subtype="" data-model="PART" data-lifecycle="IN_WORK" data-rev="A.1" data-creo="'
        'Creo 10" data-content-hash="abc123" data-relative-path="shaft.prt" data-can-checkout="1" data-can-ch'
        'eckin="0" data-can-revise="1" data-owned="0" data-checked-out="0" data-modified-locally="0" data-in-'
        'workspace="1" data-top-level-assembly="0" data-tree="" data-sort-name="shaft.prt" data-sort-rev="/A-'
        '000001" data-sort-state="/1-IN_WORK" data-sort-type="/Part" data-sort-creo="/Creo 10" data-sort-modi'
        'fied="@SORT@" data-sort-checkout="/Available" data-detail="/products/prod-1/objects/u-1" class="obje'
        'ct-row" style="--depth: 0"><td><span class="name-with-icon"><img class="type-icon" src="/static/icon'
        's/part.png" alt="Part" title="Part" width="14" height="14" decoding="async"><button type="button" cl'
        'ass="object-open" data-uuid="u-1" data-filename="shaft.prt" data-extension=".prt">shaft.prt</button>'
        '</span></td><td title="A.1">A.1</td><td title="In Work"><span class="state" data-state="IN_WORK" dat'
        'a-lifecycle-state="IN_WORK">In Work</span></td><td title="Part">Part</td><td title="Creo 10">Creo 10'
        '</td><td title="@TITLE@">@TEXT@</td><td title="Available"><span class="checkout-state" data-state="a'
        'vailable">Available</span></td></tr>'
    ),
    'mine_modified': (
        '<tr data-uuid="u-2" data-object-type="CREO_PART" data-extension=".prt" data-filename="gear.prt" data'
        '-number="N-1" data-subtype="" data-model="PART" data-lifecycle="IN_WORK" data-rev="A.12" data-creo="'
        'Creo 10" data-content-hash="abc123" data-relative-path="sub/gear.prt" data-can-checkout="0" data-can'
        '-checkin="1" data-can-revise="0" data-owned="1" data-checked-out="1" data-modified-locally="1" data-'
        'in-workspace="1" data-top-level-assembly="0" data-tree="sub" data-sort-name="sub/gear.prt" data-sort'
        '-rev="sub/A-000012" data-sort-state="sub/0-MODIFIED" data-sort-type="sub/Part" data-sort-creo="sub/C'
        'reo 10" data-sort-modified="@SORT@" data-sort-checkout="sub/Checked out by me" data-detail="/product'
        's/prod-1/objects/u-2" class="object-row" style="--depth: 0"><td><span class="name-with-icon"><img cl'
        'ass="type-icon" src="/static/icons/part.png" alt="Part" title="Part" width="14" height="14" decoding'
        '="async"><button type="button" class="object-open" data-uuid="u-2" data-filename="gear.prt" data-ext'
        'ension=".prt">gear.prt</button></span></td><td title="A.12">A.12</td><td title="Modified"><span clas'
        's="state" data-state="MODIFIED" data-lifecycle-state="IN_WORK">Modified</span></td><td title="Part">'
        'Part</td><td title="Creo 10">Creo 10</td><td title="@TITLE@">@TEXT@</td><td title="Checked out by me'
        '"><span class="checkout-state" data-state="mine">Checked out by me</span></td></tr>'
    ),
    'other_released_odd_name': (
        '<tr data-uuid="u-3" data-object-type="CREO_PART" data-extension=".prt" data-filename="a&amp;b &lt;x&'
        'gt; &#34;q&#34; &#39;z&#39;.prt" data-number="" data-subtype="SHEETMETAL" data-model="PART" data-lif'
        'ecycle="RELEASED" data-rev="A.1" data-creo="Creo 10" data-content-hash="abc123" data-relative-path="'
        'odd/a&amp;b &lt;x&gt; &#34;q&#34; &#39;z&#39;.prt" data-can-checkout="0" data-can-checkin="0" data-c'
        'an-revise="1" data-owned="0" data-checked-out="1" data-modified-locally="0" data-in-workspace="1" da'
        'ta-top-level-assembly="0" data-tree="odd" data-sort-name="odd/a&amp;b &lt;x&gt; &#34;q&#34; &#39;z&#'
        '39;.prt" data-sort-rev="odd/A-000001" data-sort-state="odd/2-RELEASED" data-sort-type="odd/Sheet &lt'
        ';metal&gt;" data-sort-creo="odd/Creo 10" data-sort-modified="@SORT@" data-sort-checkout="odd/Checked'
        ' out by sam" data-detail="/products/prod-1/objects/u-3" class="object-row" style="--depth: 0"><td><s'
        'pan class="name-with-icon"><img class="type-icon" src="/static/icons/part.png" alt="Sheet &lt;metal&'
        'gt;" title="Sheet &lt;metal&gt;" width="14" height="14" decoding="async"><button type="button" class'
        '="object-open" data-uuid="u-3" data-filename="a&amp;b &lt;x&gt; &#34;q&#34; &#39;z&#39;.prt" data-ex'
        'tension=".prt">a&amp;b &lt;x&gt; &#34;q&#34; &#39;z&#39;.prt</button></span></td><td title="A.1">A.1'
        '</td><td title="Released"><span class="state" data-state="RELEASED" data-lifecycle-state="RELEASED">'
        'Released</span></td><td title="Sheet &lt;metal&gt;">Sheet &lt;metal&gt;</td><td title="Creo 10">Creo'
        ' 10</td><td title="@TITLE@">@TEXT@</td><td title="Checked out by sam"><span class="checkout-state" d'
        'ata-state="other">Checked out by sam</span></td></tr>'
    ),
    'bare_assembly_top_level': (
        '<tr data-uuid="u-4" data-object-type="CREO_ASSEMBLY" data-extension=".asm" data-filename="plate.asm.'
        '3" data-number="N-1" data-subtype="" data-model="PART" data-lifecycle="OBSOLETE" data-rev="A.1" data'
        '-creo="" data-content-hash="" data-relative-path="plate.asm.3" data-can-checkout="0" data-can-checki'
        'n="0" data-can-revise="0" data-owned="0" data-checked-out="0" data-modified-locally="0" data-in-work'
        'space="0" data-top-level-assembly="1" data-tree="" data-sort-name="plate.asm.3" data-sort-rev="/A-00'
        '0001" data-sort-state="/2-OBSOLETE" data-sort-type="/Assembly" data-sort-creo="/" data-sort-modified'
        '="" data-sort-checkout="/Obsolete" data-detail="/products/prod-1/objects/u-4" class="object-row" sty'
        'le="--depth: 0"><td><span class="name-with-icon"><button type="button" class="object-open" data-uuid'
        '="u-4" data-filename="plate.asm.3" data-extension=".asm">plate.asm.3</button></span></td><td title="'
        'A.1">A.1</td><td title="Obsolete"><span class="state" data-state="OBSOLETE" data-lifecycle-state="OB'
        'SOLETE">Obsolete</span></td><td title="Assembly">Assembly</td><td title=""></td><td title="">—</td><'
        'td title="Obsolete"><span class="checkout-state" data-state="locked">Obsolete</span></td></tr>'
    ),
    'under_change_locked': (
        '<tr data-uuid="u-5" data-object-type="CREO_PART" data-extension=".prt" data-filename="shaft.prt" dat'
        'a-number="N-1" data-subtype="" data-model="PART" data-lifecycle="UNDER_CHANGE" data-rev="B.2" data-c'
        'reo="Creo 10" data-content-hash="abc123" data-relative-path="shaft.prt" data-can-checkout="0" data-c'
        'an-checkin="0" data-can-revise="1" data-owned="0" data-checked-out="0" data-modified-locally="0" dat'
        'a-in-workspace="1" data-top-level-assembly="0" data-tree="" data-sort-name="shaft.prt" data-sort-rev'
        '="/B-000002" data-sort-state="/2-UNDER_CHANGE" data-sort-type="/Part" data-sort-creo="/Creo 10" data'
        '-sort-modified="@SORT@" data-sort-checkout="/In Review" data-detail="/products/prod-1/objects/u-5" c'
        'lass="object-row" style="--depth: 0"><td><span class="name-with-icon"><img class="type-icon" src="/s'
        'tatic/icons/part.png" alt="Part" title="Part" width="14" height="14" decoding="async"><button type="'
        'button" class="object-open" data-uuid="u-5" data-filename="shaft.prt" data-extension=".prt">shaft.pr'
        't</button></span></td><td title="B.2">B.2</td><td title="Under Change"><span class="state" data-stat'
        'e="UNDER_CHANGE" data-lifecycle-state="UNDER_CHANGE">Under Change</span></td><td title="Part">Part</'
        'td><td title="Creo 10">Creo 10</td><td title="@TITLE@">@TEXT@</td><td title="In Review"><span class='
        '"checkout-state" data-state="locked">In Review</span></td></tr>'
    ),
    'folders': (
        '<tr class="folder-row" data-folder="Ünï cödé" data-object-ids="a,b,c" data-can-checkout="1" data-can'
        '-checkin="0" data-owned="0" data-checked-out="0" data-in-workspace="mixed" data-depth="0" data-sort-'
        'name="Ünï cödé/" data-sort-rev="Ünï cödé/" data-sort-state="Ünï cödé/" data-sort-type="Ünï cödé/" da'
        'ta-sort-creo="Ünï cödé/" data-sort-modified="@FSORT@" data-sort-checkout="Ünï cödé/" style="--depth:'
        ' 0" title="Click the folder name to open. Click elsewhere to select. Double-click to open."><td titl'
        'e="Ünï cödé"><a class="folder-open" href="/?product=prod-1&amp;folder=%C3%9Cn%C3%AF%20c%C3%B6d%C3%A9'
        '" data-folder="Ünï cödé" title="Open Ünï cödé"><span class="folder-label"><svg class="folder-icon" v'
        'iewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.2A2.2 2.2 0 0 1 5.7 5h4.1c.4 0 .8.2 1 .5l1.3 1'
        '.4c.3.3.6.5 1 .5h5.2A2.2 2.2 0 0 1 20.5 9.6v8.2a2.2 2.2 0 0 1-2.2 2.2H5.7A2.2 2.2 0 0 1 3.5 17.8V7.2'
        'Z"/></svg><span class="folder-name">Ünï cödé</span></span></a><div class="muted small folder-count">'
        '3 files</div></td><td></td><td></td><td title="Folder">Folder</td><td></td><td title="@FTITLE@">@FTE'
        'XT@</td><td></td></tr><tr class="folder-row" data-folder="x/a&amp;b" data-object-ids="" data-can-che'
        'ckout="0" data-can-checkin="0" data-owned="0" data-checked-out="0" data-in-workspace="mixed" data-de'
        'pth="0" data-sort-name="x/a&amp;b/" data-sort-rev="x/a&amp;b/" data-sort-state="x/a&amp;b/" data-sor'
        't-type="x/a&amp;b/" data-sort-creo="x/a&amp;b/" data-sort-modified="" data-sort-checkout="x/a&amp;b/'
        '" style="--depth: 0" title="Click the folder name to open. Click elsewhere to select. Double-click t'
        'o open."><td title="a&amp;b"><a class="folder-open" href="/?product=prod-1&amp;folder=x/a%26b" data-'
        'folder="x/a&amp;b" title="Open a&amp;b"><span class="folder-label"><svg class="folder-icon" viewBox='
        '"0 0 24 24" aria-hidden="true"><path d="M3.5 7.2A2.2 2.2 0 0 1 5.7 5h4.1c.4 0 .8.2 1 .5l1.3 1.4c.3.3'
        '.6.5 1 .5h5.2A2.2 2.2 0 0 1 20.5 9.6v8.2a2.2 2.2 0 0 1-2.2 2.2H5.7A2.2 2.2 0 0 1 3.5 17.8V7.2Z"/></s'
        'vg><span class="folder-name">a&amp;b</span></span></a><div class="muted small folder-count">1 file</'
        'div></td><td></td><td></td><td title="Folder">Folder</td><td></td><td title="">—</td><td></td></tr>'
    ),
    'folders_no_checkout_flag': (
        '<tr class="folder-row" data-folder="docs" data-object-ids="a,b" data-can-checkout="0" data-can-check'
        'in="0" data-owned="0" data-checked-out="0" data-in-workspace="mixed" data-depth="0" data-sort-name="'
        'docs/" data-sort-rev="docs/" data-sort-state="docs/" data-sort-type="docs/" data-sort-creo="docs/" d'
        'ata-sort-modified="@FSORT@" data-sort-checkout="docs/" style="--depth: 0" title="Click the folder na'
        'me to open. Click elsewhere to select. Double-click to open."><td title="docs"><a class="folder-open'
        '" href="/?product=prod-1&amp;folder=docs" data-folder="docs" title="Open docs"><span class="folder-l'
        'abel"><svg class="folder-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.2A2.2 2.2 0 0 '
        '1 5.7 5h4.1c.4 0 .8.2 1 .5l1.3 1.4c.3.3.6.5 1 .5h5.2A2.2 2.2 0 0 1 20.5 9.6v8.2a2.2 2.2 0 0 1-2.2 2.'
        '2H5.7A2.2 2.2 0 0 1 3.5 17.8V7.2Z"/></svg><span class="folder-name">docs</span></span></a><div class'
        '="muted small folder-count">2 files</div></td><td></td><td></td><td title="Folder">Folder</td><td></'
        'td><td title="@FTITLE@">@FTEXT@</td><td></td></tr>'
    ),
    'mixed_order': (
        '<tr class="folder-row" data-folder="docs" data-object-ids="a" data-can-checkout="1" data-can-checkin'
        '="0" data-owned="0" data-checked-out="0" data-in-workspace="mixed" data-depth="0" data-sort-name="do'
        'cs/" data-sort-rev="docs/" data-sort-state="docs/" data-sort-type="docs/" data-sort-creo="docs/" dat'
        'a-sort-modified="@FSORT@" data-sort-checkout="docs/" style="--depth: 0" title="Click the folder name'
        ' to open. Click elsewhere to select. Double-click to open."><td title="docs"><a class="folder-open" '
        'href="/?product=prod-1&amp;folder=docs" data-folder="docs" title="Open docs"><span class="folder-lab'
        'el"><svg class="folder-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 7.2A2.2 2.2 0 0 1 '
        '5.7 5h4.1c.4 0 .8.2 1 .5l1.3 1.4c.3.3.6.5 1 .5h5.2A2.2 2.2 0 0 1 20.5 9.6v8.2a2.2 2.2 0 0 1-2.2 2.2H'
        '5.7A2.2 2.2 0 0 1 3.5 17.8V7.2Z"/></svg><span class="folder-name">docs</span></span></a><div class="'
        'muted small folder-count">2 files</div></td><td></td><td></td><td title="Folder">Folder</td><td></td'
        '><td title="@FTITLE@">@FTEXT@</td><td></td></tr><tr data-uuid="u-6" data-object-type="CREO_PART" dat'
        'a-extension=".prt" data-filename="b.prt" data-number="N-1" data-subtype="" data-model="PART" data-li'
        'fecycle="IN_WORK" data-rev="A.1" data-creo="Creo 10" data-content-hash="abc123" data-relative-path="'
        'shaft.prt" data-can-checkout="1" data-can-checkin="0" data-can-revise="1" data-owned="0" data-checke'
        'd-out="0" data-modified-locally="0" data-in-workspace="1" data-top-level-assembly="0" data-tree="" d'
        'ata-sort-name="shaft.prt" data-sort-rev="/A-000001" data-sort-state="/1-IN_WORK" data-sort-type="/Pa'
        'rt" data-sort-creo="/Creo 10" data-sort-modified="@SORT@" data-sort-checkout="/Available" data-detai'
        'l="/products/prod-1/objects/u-6" class="object-row" style="--depth: 0"><td><span class="name-with-ic'
        'on"><img class="type-icon" src="/static/icons/part.png" alt="Part" title="Part" width="14" height="1'
        '4" decoding="async"><button type="button" class="object-open" data-uuid="u-6" data-filename="b.prt" '
        'data-extension=".prt">b.prt</button></span></td><td title="A.1">A.1</td><td title="In Work"><span cl'
        'ass="state" data-state="IN_WORK" data-lifecycle-state="IN_WORK">In Work</span></td><td title="Part">'
        'Part</td><td title="Creo 10">Creo 10</td><td title="@TITLE@">@TEXT@</td><td title="Available"><span '
        'class="checkout-state" data-state="available">Available</span></td></tr><tr data-uuid="u-7" data-obj'
        'ect-type="CREO_PART" data-extension=".prt" data-filename="c.prt" data-number="N-1" data-subtype="" d'
        'ata-model="PART" data-lifecycle="IN_WORK" data-rev="A.1" data-creo="Creo 10" data-content-hash="abc1'
        '23" data-relative-path="shaft.prt" data-can-checkout="1" data-can-checkin="0" data-can-revise="1" da'
        'ta-owned="0" data-checked-out="0" data-modified-locally="0" data-in-workspace="1" data-top-level-ass'
        'embly="0" data-tree="" data-sort-name="shaft.prt" data-sort-rev="/A-000001" data-sort-state="/1-IN_W'
        'ORK" data-sort-type="/Part" data-sort-creo="/Creo 10" data-sort-modified="@SORT@" data-sort-checkout'
        '="/Available" data-detail="/products/prod-1/objects/u-7" class="object-row" style="--depth: 0"><td><'
        'span class="name-with-icon"><img class="type-icon" src="/static/icons/part.png" alt="Part" title="Pa'
        'rt" width="14" height="14" decoding="async"><button type="button" class="object-open" data-uuid="u-7'
        '" data-filename="c.prt" data-extension=".prt">c.prt</button></span></td><td title="A.1">A.1</td><td '
        'title="In Work"><span class="state" data-state="IN_WORK" data-lifecycle-state="IN_WORK">In Work</spa'
        'n></td><td title="Part">Part</td><td title="Creo 10">Creo 10</td><td title="@TITLE@">@TEXT@</td><td '
        'title="Available"><span class="checkout-state" data-state="available">Available</span></td></tr>'
    ),
}


def _norm(html: str) -> str:
    html = re.sub(r"\s+", " ", str(html))
    return re.sub(r">\s+<", "><", html).strip()


def _fill(text: str) -> str:
    return (
        text.replace("@SORT@", format_local(STAMP, "%Y%m%d%H%M%S"))
        .replace("@TITLE@", format_local_pretty(STAMP))
        .replace("@TEXT@", format_local(STAMP))
        .replace("@FSORT@", format_local(FOLDER_STAMP, "%Y%m%d%H%M%S"))
        .replace("@FTITLE@", format_local_pretty(FOLDER_STAMP))
        .replace("@FTEXT@", format_local(FOLDER_STAMP))
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_rows_match_the_markup_the_old_template_produced(name):
    entries, ui, where_used, top_level = CASES[name]
    html = render_file_rows(
        entries,
        selected_uuid="prod-1",
        product_ui=ui,
        where_used_present=where_used,
        top_level_assembly_uuids=top_level,
    )
    assert _norm(html) == _fill(EXPECTED[name])


def test_product_ui_can_be_an_object_and_missing_flags_mean_off():
    entries = [{"kind": "folder", "name": "d", "path": "d", "depth": 0, "count": 1, "modified": None, "object_ids": ["a"]}]
    on = render_file_rows(entries, selected_uuid="p", product_ui=SimpleNamespace(show_checkout=True))
    off = render_file_rows(entries, selected_uuid="p", product_ui={})
    assert 'data-can-checkout="1"' in on and 'data-can-checkout="0"' in off


def test_an_empty_list_is_an_empty_string():
    assert str(render_file_rows([], selected_uuid="p", product_ui={})) == ""


def test_text_with_markup_characters_is_escaped_everywhere_it_appears():
    entries, ui, where_used, top_level = CASES["other_released_odd_name"]
    html = str(render_file_rows(entries, selected_uuid="p", product_ui=ui))
    assert "<x>" not in html and "&lt;x&gt;" in html
    assert "&#34;q&#34;" in html and "&#39;z&#39;" in html and "a&amp;b" in html

