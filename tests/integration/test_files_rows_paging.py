"""A big folder sends its first rows in the page and the rest from /files-rows (same row markup)."""

from __future__ import annotations

import re

from creopdm.api.pages import FILES_FIRST_PAGE
from tests.conftest import requires_git

TOTAL = FILES_FIRST_PAGE + 20


def _product_with_files(client, count: int) -> dict:
    product = client.post("/api/products", json={"name": "Paging"}).json()
    names = [f"part{i:04d}.prt" for i in range(count)]
    for start in range(0, count, 100):
        chunk = names[start : start + 100]
        added = client.post(
            f"/api/products/{product['uuid']}/objects/from-uploads",
            files=[("files", (n, f"{n}-v1".encode(), "application/octet-stream")) for n in chunk],
            data={"relative_paths": chunk, "comment": "bulk"},
        )
        assert added.status_code == 200, added.text
        assert added.json()["failed"] == []
    return product


def _row_files(html: str) -> list[str]:
    return re.findall(r'<tr data-uuid="[^"]+"[^>]*? data-filename="([^"]+)"', html)


@requires_git
def test_a_big_folder_sends_the_first_rows_and_the_rest_from_files_rows(client):
    product = _product_with_files(client, TOTAL)
    page = client.get(f"/?product={product['uuid']}").text
    first = _row_files(page)
    assert len(first) == FILES_FIRST_PAGE
    table = page.split('id="object-table"', 1)[1].split(">", 1)[0]
    assert f'data-rows-total="{TOTAL}"' in table and f'data-rows-rendered="{FILES_FIRST_PAGE}"' in table
    tail_url = re.search(r'data-rows-tail-url="([^"]+)"', table).group(1).replace("&amp;", "&")
    assert tail_url.startswith(f"/products/{product['uuid']}/files-rows?") and f"offset={FILES_FIRST_PAGE}" in tail_url
    # Counts always describe the whole folder, not the rows sent so far.
    assert f'data-folder-count="{TOTAL}"' in page or f">{TOTAL}</strong>" in page

    tail = client.get(tail_url)
    assert tail.status_code == 200, tail.text
    assert tail.headers["x-rows-total"] == str(TOTAL) and tail.headers["x-rows-offset"] == str(FILES_FIRST_PAGE)
    rest = _row_files(tail.text)
    assert len(rest) == TOTAL - FILES_FIRST_PAGE
    assert set(first).isdisjoint(rest) and len(set(first) | set(rest)) == TOTAL
    # The same markup as the page rows (the partial is shared): same attributes on every row.
    page_row = re.search(r'<tr data-uuid="[^"]+"[^>]*>', page).group(0)
    tail_row = re.search(r'<tr data-uuid="[^"]+"[^>]*>', tail.text).group(0)
    assert re.findall(r'(data-[a-z-]+)=', page_row) == re.findall(r'(data-[a-z-]+)=', tail_row)
    assert 'class="object-row"' in tail_row


@requires_git
def test_a_small_folder_sends_everything_in_the_page(client):
    product = _product_with_files(client, 5)
    page = client.get(f"/?product={product['uuid']}").text
    assert len(_row_files(page)) == 5
    table = page.split('id="object-table"', 1)[1].split(">", 1)[0]
    assert "data-rows-tail-url" not in table


@requires_git
def test_files_rows_needs_a_product_you_can_open(client):
    reply = client.get("/products/00000000-0000-4000-8000-000000000000/files-rows?offset=0")
    assert reply.status_code == 404
