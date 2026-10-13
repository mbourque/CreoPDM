"""GET thumbnail by hash / object tip."""

from __future__ import annotations

from creopdm.models.thumbnail import Thumbnail
from creopdm.utils.creo_thumbnail import MARKER
from tests.conftest import requires_git
from tests.unit.test_creo_thumbnail import _minimal_jpeg


@requires_git
def test_get_thumbnail_by_hash_and_object(client, app, repo_parent):
    location = repo_parent / "ThumbProd"
    location.mkdir(parents=True, exist_ok=True)
    product = client.post(
        "/api/products",
        json={"name": "Thumb Prod", "number": "TH-1"},
    )
    assert product.status_code == 201, product.text
    pid = product.json()["uuid"]

    jpeg = _minimal_jpeg()
    added = client.post(
        f"/api/products/{pid}/objects/from-uploads",
        files=[
            (
                "files",
                ("shaft.prt", b"UGC" + MARKER + b"\x00" + jpeg, "application/octet-stream"),
            )
        ],
        data={"relative_paths": ["shaft.prt"], "comment": "thumb tip"},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["failed"] == []
    obj_uuid = body["ok"][0]["uuid"]

    detail = client.get(f"/api/objects/{obj_uuid}")
    assert detail.status_code == 200
    digest = detail.json()["current_version"]["content_hash"]
    assert digest

    ctx = app.state.ctx
    session = ctx.session_factory()
    try:
        if session.get(Thumbnail, digest) is None:
            session.add(
                Thumbnail(
                    content_hash=digest,
                    mime="image/jpeg",
                    width=16,
                    height=16,
                    bytes=jpeg,
                )
            )
            session.commit()
    finally:
        session.close()

    by_hash = client.get(f"/api/thumbnails/{digest}")
    assert by_hash.status_code == 200, by_hash.text
    assert by_hash.headers["content-type"].startswith("image/jpeg")
    assert by_hash.headers.get("etag") == f'"{digest}"'
    assert "immutable" in by_hash.headers.get("cache-control", "")
    assert by_hash.content == jpeg

    by_obj = client.get(f"/api/objects/{obj_uuid}/thumbnail")
    assert by_obj.status_code == 200
    assert by_obj.content == jpeg

    missing = client.get(f"/api/thumbnails/{'c' * 64}")
    assert missing.status_code == 404
