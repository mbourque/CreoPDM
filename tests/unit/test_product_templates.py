"""Product templates: hidden from the regular lists, listed with a marker for templates.view, and a
new product can start from one (files, sub folders and empty folders)."""

from __future__ import annotations

from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users, auth_client, auth_ctx  # noqa: F401


def _make_template(client, name="Starter"):
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        template = ctx.products.create_product(db, name=name, is_template=True)
        return template.uuid


def _fill(client, template_uuid):
    files = [
        ("files", ("readme.txt", b"hello", "application/octet-stream")),
        ("files", ("part.prt", b"part-bytes", "application/octet-stream")),
    ]
    done = client.post(
        f"/api/products/{template_uuid}/objects/from-uploads",
        files=files,
        data={"relative_paths": ["docs/readme.txt", "models/sub/part.prt"], "comment": "seed"},
    )
    assert done.status_code == 200, done.text
    assert client.post(
        f"/api/products/{template_uuid}/folders", json={"name": "empty", "parent_folder": "models"}
    ).status_code in (200, 201)


@requires_git
def test_a_template_is_marked_in_the_product_list_when_you_may_view_templates(client):
    _make_template(client)
    client.post("/api/products", json={"name": "Regular"})
    rows = {row["name"]: row for row in client.get("/api/products").json()}
    assert rows["Starter"]["is_template"] is True
    assert rows["Regular"]["is_template"] is False


@requires_git
def test_a_product_can_start_from_a_template_with_folders_and_empty_folders(client):
    template_uuid = _make_template(client)
    _fill(client, template_uuid)
    made = client.post("/api/products", json={"name": "From Starter", "template_id": template_uuid})
    assert made.status_code == 201, made.text
    product = made.json()
    assert product["is_template"] is False
    listed = client.get(f"/api/products/{product['uuid']}/objects").json()
    paths = sorted(row["relative_path"] for row in listed)
    # the .gitkeep placeholder of the empty folder is not copied as a file
    assert paths == ["docs/readme.txt", "models/sub/part.prt"]
    vault = client.app.state.ctx.workspaces.vault_for(
        client.app.state.ctx.products.get_product(client.app.state.ctx.session_factory(), product["uuid"])
    )
    assert (vault / "models" / "empty").is_dir()
    # the template itself is unchanged
    again = client.get(f"/api/products/{template_uuid}/objects").json()
    assert len([row for row in again if not row["relative_path"].endswith(".gitkeep")]) == 2


@requires_git
def test_a_regular_product_cannot_be_used_as_a_template(client):
    source = client.post("/api/products", json={"name": "Regular"}).json()
    made = client.post("/api/products", json={"name": "Copy", "template_id": source["uuid"]})
    assert made.status_code == 400


@requires_git
def test_templates_are_offered_in_the_new_product_dialog_only_when_they_exist(client):
    assert 'id="product-template"' not in client.get("/").text
    _make_template(client, "Offered Template")
    page = client.get("/")
    assert 'id="product-template"' in page.text and "Offered Template" in page.text


@requires_git
def test_template_permissions_gate_creating_and_deleting_templates(auth_client, auth_ctx):  # noqa: F811
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    page = auth_client.get("/admin/templates/new")
    assert page.status_code == 200 and "Create template" in page.text
    created = auth_client.post(
        "/admin/templates/new",
        data={"name": "Admin Template", "vault_folder": ""},
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    listing = auth_client.get("/admin/templates")
    assert "Admin Template" in listing.text and "Template" in listing.text
    hidden = auth_client.get("/admin/products/edit")
    assert "Admin Template" not in hidden.text
    assert "Create template" in hidden.text
    hub = auth_client.get("/admin/products")
    assert 'href="/admin/templates"' in hub.text
    uuid = next(p["uuid"] for p in auth_client.get("/api/products").json() if p["name"] == "Admin Template")
    deleted = auth_client.post(f"/admin/templates/{uuid}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert "Admin Template" not in auth_client.get("/admin/templates").text


@requires_git
def test_admin_add_product_can_start_from_a_template(auth_client, auth_ctx):  # noqa: F811
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    assert "Start from template" not in auth_client.get("/admin/products/new").text
    auth_client.post("/admin/templates/new", data={"name": "Base Template", "vault_folder": ""}, follow_redirects=False)
    template_uuid = next(p["uuid"] for p in auth_client.get("/api/products").json() if p["name"] == "Base Template")
    form = auth_client.get("/admin/products/new")
    assert "Start from template" in form.text and "Base Template" in form.text
    made = auth_client.post(
        "/admin/products/new",
        data={"name": "From Admin", "vault_folder": "", "template_id": template_uuid, "state": "IN_WORK"},
        follow_redirects=False,
    )
    assert made.status_code == 303, made.text
    rows = {p["name"]: p for p in auth_client.get("/api/products").json()}
    assert rows["From Admin"]["is_template"] is False and rows["Base Template"]["is_template"] is True


@requires_git
def test_the_product_folders_including_empty_ones_are_listed_for_the_local_workspace(client):
    template_uuid = _make_template(client)
    _fill(client, template_uuid)
    folders = client.get(f"/api/products/{template_uuid}/vault-folders")
    assert folders.status_code == 200, folders.text
    assert folders.json() == ["docs", "models", "models/empty", "models/sub"]
