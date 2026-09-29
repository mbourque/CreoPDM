from pathlib import Path
import os
import shutil

import pytest
from sqlalchemy import select

from creopdm.models.product import Product
from creopdm.utils.files import remove_tree
from tests.conftest import requires_git


def _create_product(client, repo_parent: Path, name: str = "Robot Arm", number: str = "PRJ-0027"):
    files_dir = repo_parent / name.replace(" ", "")
    files_dir.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/products",
        json={
            "name": name,
            "number": number,
            "description": "Prototype robotic arm",
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), files_dir


def _attach_legacy_location(app, product_uuid: str, location: Path) -> None:
    location.mkdir(parents=True, exist_ok=True)
    with app.state.ctx.session_factory() as session:
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        assert product is not None
        product.repository_path = str(location.resolve())
        session.commit()


@requires_git
def test_create_list_and_get_product(client, repo_parent, data_dir):
    payload, location = _create_product(client, repo_parent)
    assert payload["name"] == "Robot Arm"
    assert payload["number"] == "PRJ-0027"
    assert payload["default_branch"] == "main"
    assert payload["remote_mode"] == "LOCAL_ONLY"
    assert payload["repository_path"] == ""
    vault = data_dir / "vaults" / payload["uuid"]
    assert (vault / ".git").exists()
    assert (vault / ".creopdm" / "product.json").exists()
    if os.name == "nt":
        from creopdm.utils.files import is_hidden

        assert is_hidden(vault / ".creopdm")
        assert is_hidden(vault / ".gitignore")
    ignore = (vault / ".gitignore").read_text(encoding="utf-8")
    assert "*.tst" in ignore
    assert "trail.txt*" in ignore
    assert "proimpex.errors" in ignore
    assert "regen_backup_model*.mrd.*" in ignore
    assert "traceback.log" in ignore
    assert "config.pro" in ignore
    assert "creo_parametric_customization.ui" in ignore
    assert "Thumbs.db" in ignore
    for ext in (".inf", ".idx", ".log", ".crc", ".dat", ".out"):
        assert f"*{ext}\n" not in ignore and not ignore.endswith(f"*{ext}")

    listing = client.get("/api/products")
    assert listing.status_code == 200
    assert any(item["uuid"] == payload["uuid"] for item in listing.json())

    fetched = client.get(f"/api/products/{payload['uuid']}")
    assert fetched.status_code == 200
    assert fetched.json()["repository_path"] == ""
    home = client.get(f"/?product={payload['uuid']}")
    assert home.status_code == 200
    assert payload["name"] in home.text
    assert payload["uuid"] in home.text
    assert 'class="muted product-meta"' in home.text
    assert "PRJ-0027" in home.text
    assert "Prototype robotic arm" in home.text
    assert 'title="PRJ-0027 — Prototype robotic arm"' in home.text
    assert home.text.count('title="PRJ-0027 — Prototype robotic arm"') >= 2
    script = client.get("/static/js/app.js")
    assert "function leavePage" in script.text
    assert "function closeOpenDialogs" in script.text
    assert "leavePage(`/?product=${encodeURIComponent(product.uuid)}`)" in script.text


@requires_git
def test_sync_gitignore_hides_existing_bookkeeping(client, app, repo_parent, data_dir):
    payload, _ = _create_product(client, repo_parent, name="Hide Bookkeeping")
    vault = data_dir / "vaults" / payload["uuid"]
    from creopdm.utils.files import is_hidden, set_hidden

    set_hidden(vault / ".gitignore", False)
    set_hidden(vault / ".creopdm", False)
    if os.name == "nt":
        assert not is_hidden(vault / ".gitignore")
        assert not is_hidden(vault / ".creopdm")
    app.state.ctx.workspaces.sync_gitignore()
    if os.name == "nt":
        assert is_hidden(vault / ".creopdm")
        assert is_hidden(vault / ".gitignore")


@requires_git
def test_create_product_requires_name(client):
    blank = client.post("/api/products", json={"name": "   "})
    assert blank.status_code in {400, 422}


@requires_git
def test_product_number_and_description_limits(client):
    too_long_number = client.post(
        "/api/products",
        json={"name": "Limits", "number": "X" * 26, "description": "ok"},
    )
    assert too_long_number.status_code == 422, too_long_number.text
    too_long_description = client.post(
        "/api/products",
        json={"name": "Limits", "number": "PRJ-1", "description": "d" * 257},
    )
    assert too_long_description.status_code == 422, too_long_description.text
    ok = client.post(
        "/api/products",
        json={"name": "Limits", "number": "N" * 25, "description": "d" * 256},
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["number"] == "N" * 25
    assert body["description"] == "d" * 256
    home = client.get(f"/?product={body['uuid']}")
    assert home.status_code == 200
    assert 'maxlength="25"' in home.text
    assert 'maxlength="256"' in home.text


@requires_git
def test_create_product_rejects_duplicate_name_case_insensitive(client, repo_parent):
    first, _ = _create_product(client, repo_parent, name="Robot Arm")
    same = client.post("/api/products", json={"name": "Robot Arm"})
    assert same.status_code == 409, same.text
    assert "already exists" in same.json()["error"]["message"].lower()
    folded = client.post("/api/products", json={"name": "robot arm"})
    assert folded.status_code == 409, folded.text
    listing = client.get("/api/products").json()
    names = [item["name"] for item in listing]
    assert names.count("Robot Arm") == 1
    assert "robot arm" not in names


@requires_git
def test_create_product_custom_vault_folder(client, repo_parent, data_dir):
    response = client.post(
        "/api/products",
        json={"name": "Custom Vault", "vault_folder": "Robot-Arm"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["vault_folder"] == "Robot-Arm"
    assert body["uuid"] != "Robot-Arm"
    assert (data_dir / "vaults" / "Robot-Arm" / ".git").is_dir()
    assert not (data_dir / "vaults" / body["uuid"]).exists()


@requires_git
def test_create_product_rejects_vault_folder_with_spaces(client):
    response = client.post(
        "/api/products",
        json={"name": "Spaced", "vault_folder": "Robot Arm"},
    )
    assert response.status_code == 400, response.text
    assert "space" in response.json()["error"]["message"].lower()


@requires_git
def test_create_product_rejects_duplicate_vault_folder(client, repo_parent):
    first = client.post(
        "/api/products",
        json={"name": "First", "vault_folder": "Shared-Vault"},
    )
    assert first.status_code == 201, first.text
    again = client.post(
        "/api/products",
        json={"name": "Second", "vault_folder": "shared-vault"},
    )
    assert again.status_code == 409, again.text
    assert "vault" in again.json()["error"]["message"].lower()


@requires_git
def test_create_product_use_hash_uuid_as_folder(client, repo_parent, data_dir):
    uid = "11111111-2222-4333-8444-555555555555"
    response = client.post(
        "/api/products",
        json={"name": "Hashed", "vault_folder": uid},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["uuid"] == uid
    assert body["vault_folder"] == uid
    assert (data_dir / "vaults" / uid / ".git").is_dir()


@requires_git
def test_rename_product_rejects_duplicate_name_case_insensitive(client, repo_parent):
    first, _ = _create_product(client, repo_parent, name="Alpha Cell")
    second, _ = _create_product(client, repo_parent, name="Beta Cell")
    taken = client.patch(
        f"/api/products/{second['uuid']}",
        json={"name": "alpha cell"},
    )
    assert taken.status_code == 409, taken.text
    assert "already exists" in taken.json()["error"]["message"].lower()
    kept = client.patch(
        f"/api/products/{second['uuid']}",
        json={"name": "Beta Cell"},
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["name"] == "Beta Cell"
    renamed = client.patch(
        f"/api/products/{second['uuid']}",
        json={"name": "Gamma Cell"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Gamma Cell"
    assert first["name"] == "Alpha Cell"


@requires_git
def test_rename_product_keeps_folder(client, repo_parent, data_dir):
    payload, location = _create_product(client, repo_parent)
    renamed = client.patch(
        f"/api/products/{payload['uuid']}",
        json={"name": "Robot Arm Mk2", "number": "PRJ-0099", "description": "Second build"},
    )
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "Robot Arm Mk2"
    assert body["number"] == "PRJ-0099"
    assert body["description"] == "Second build"
    assert body["repository_path"] == ""
    marker = (data_dir / "vaults" / payload["uuid"] / ".creopdm" / "product.json").read_text(
        encoding="utf-8"
    )
    assert "Robot Arm Mk2" in marker
    listing = client.get("/api/products").json()
    names = {item["name"] for item in listing if item["uuid"] == payload["uuid"]}
    assert names == {"Robot Arm Mk2"}


@requires_git
def test_home_remembers_last_opened_product(client, repo_parent):
    first, _location = _create_product(client, repo_parent, name="First Arm")
    second, _other = _create_product(client, repo_parent, name="Second Arm")
    opened = client.get(f"/?product={second['uuid']}")
    assert opened.status_code == 200, opened.text
    assert f'<h1 title="' in opened.text
    assert ">Second Arm</h1>" in opened.text
    assert second["uuid"] in opened.text[opened.text.index("<h1 title="):opened.text.index(">Second Arm</h1>")]
    home = client.get("/")
    assert home.status_code == 200, home.text
    assert ">Second Arm</h1>" in home.text
    assert first["name"] in home.text
    assert f'href="/?product={second["uuid"]}"' in home.text
    assert 'id="product-menu-btn"' in home.text
    assert "sidebar-menu-btn" in home.text
    css = client.get("/static/css/app.css").text
    media = css.split("@media (max-width: 860px)", 1)[-1]
    assert ".workspace .sidebar-menu-btn { display: flex; }" in media
    assert ".workspace .sidebar-collapse-btn { display: none; }" in media
    assert 'id="sidebar-collapse-btn"' in home.text
    assert 'id="search-input"' in home.text
    assert "Search all files in product" in home.text
    assert "Workspace:" not in home.text


@requires_git
def test_rename_rejects_location_change(client, repo_parent):
    payload, location = _create_product(client, repo_parent, name="Stay Put")
    elsewhere = repo_parent / "MovedVault"
    elsewhere.mkdir()
    rejected = client.patch(
        f"/api/products/{payload['uuid']}",
        json={
            "name": "Stay Put Mk2",
            "repository_path": str(elsewhere),
        },
    )
    assert rejected.status_code == 422, rejected.text
    fetched = client.get(f"/api/products/{payload['uuid']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["name"] == "Stay Put"
    assert body["repository_path"] == ""
    assert not (elsewhere / ".git").exists()


@requires_git
def test_rename_rejects_vault_folder_change(client, repo_parent, data_dir):
    """vault_folder is immutable after create — API must refuse and leave disk alone."""
    created = client.post(
        "/api/products",
        json={"name": "Fixed Vault", "vault_folder": "Fixed-Vault"},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["vault_folder"] == "Fixed-Vault"
    vault_path = data_dir / "vaults" / "Fixed-Vault"
    assert vault_path.is_dir()

    rejected = client.patch(
        f"/api/products/{payload['uuid']}",
        json={
            "name": "Fixed Vault Mk2",
            "vault_folder": "Renamed-Vault",
        },
    )
    assert rejected.status_code == 422, rejected.text

    fetched = client.get(f"/api/products/{payload['uuid']}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["name"] == "Fixed Vault"
    assert body["vault_folder"] == "Fixed-Vault"
    assert vault_path.is_dir()
    assert not (data_dir / "vaults" / "Renamed-Vault").exists()

    renamed = client.patch(
        f"/api/products/{payload['uuid']}",
        json={"name": "Fixed Vault Mk2"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["vault_folder"] == "Fixed-Vault"
    assert vault_path.is_dir()


@requires_git
def test_product_orm_blocks_vault_folder_assignment(app, client, repo_parent, data_dir):
    """ORM before_update must stop any code path from rewriting vault_folder."""
    created = client.post(
        "/api/products",
        json={"name": "ORM Guard", "vault_folder": "Orm-Guard"},
    )
    assert created.status_code == 201, created.text
    product_uuid = created.json()["uuid"]

    from creopdm.exceptions import ValidationAppError
    from creopdm.models.product import Product
    from creopdm.utils.vault_folder import VAULT_FOLDER_IMMUTABLE_MESSAGE

    with app.state.ctx.session_factory() as session:
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        assert product is not None
        product.vault_folder = "Hacked-Vault"
        with pytest.raises(ValidationAppError, match="cannot be changed") as exc:
            session.flush()
        assert exc.value.message == VAULT_FOLDER_IMMUTABLE_MESSAGE
        session.rollback()

    fetched = client.get(f"/api/products/{product_uuid}").json()
    assert fetched["vault_folder"] == "Orm-Guard"
    assert (data_dir / "vaults" / "Orm-Guard").is_dir()
    assert not (data_dir / "vaults" / "Hacked-Vault").exists()


@requires_git
def test_rename_product_requires_name(client, repo_parent):
    payload, _location = _create_product(client, repo_parent)
    blank = client.patch(f"/api/products/{payload['uuid']}", json={"name": "   "})
    assert blank.status_code == 400


@requires_git
def test_open_workspace_launches_explorer(client, repo_parent, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr(
        "creopdm.api.products.open_windows_folder",
        lambda path: opened.append(path),
    )
    payload, _location = _create_product(client, repo_parent)
    response = client.post(f"/api/products/{payload['uuid']}/workspace/open")
    assert response.status_code == 204, response.text
    assert len(opened) == 1
    assert opened[0].is_dir()
    assert payload["uuid"] in str(opened[0])


@requires_git
def test_open_workspace_opens_current_files_folder(client, repo_parent, data_dir, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr(
        "creopdm.api.products.open_windows_folder",
        lambda path: opened.append(path),
    )
    payload, location = _create_product(client, repo_parent)
    picked = location / "html_tutorials"
    nested = picked / "css"
    nested.mkdir(parents=True)
    (picked / "index.html").write_bytes(b"home")
    (nested / "site.css").write_bytes(b"body{}")
    added = client.post(
        f"/api/products/{payload['uuid']}/objects/from-disk",
        json={
            "paths": [str(picked / "index.html"), str(nested / "site.css")],
            "comment": "Tutorials",
            "base_folder": str(picked),
        },
    )
    assert added.status_code == 200, added.text
    workspace = data_dir / "vaults" / payload["uuid"]
    nested_open = client.post(
        f"/api/products/{payload['uuid']}/workspace/open",
        params={"folder": "html_tutorials/css"},
    )
    assert nested_open.status_code == 204, nested_open.text
    assert opened[-1].resolve() == (workspace / "html_tutorials" / "css").resolve()
    root_open = client.post(f"/api/products/{payload['uuid']}/workspace/open")
    assert root_open.status_code == 204, root_open.text
    assert opened[-1].resolve() == workspace.resolve()
    missing = client.post(
        f"/api/products/{payload['uuid']}/workspace/open",
        params={"folder": "html_tutorials/missing"},
    )
    assert missing.status_code == 204, missing.text
    assert opened[-1].resolve() == workspace.resolve()
    traversal = client.post(
        f"/api/products/{payload['uuid']}/workspace/open",
        params={"folder": "../secret"},
    )
    assert traversal.status_code == 204, traversal.text
    assert opened[-1].resolve() == workspace.resolve()


@requires_git
def test_delete_product_is_soft(client, repo_parent, data_dir):
    payload, location = _create_product(client, repo_parent, name="Pump")
    deleted = client.delete(f"/api/products/{payload['uuid']}")
    assert deleted.status_code == 204
    listing = client.get("/api/products")
    assert all(item["uuid"] != payload["uuid"] for item in listing.json())
    assert (data_dir / "vaults" / payload["uuid"] / ".git").exists()


@requires_git
def test_forget_product_strips_git_and_keeps_models(client, app, repo_parent, data_dir):
    payload, location = _create_product(client, repo_parent, name="Ribbed")
    _attach_legacy_location(app, payload["uuid"], location)
    model = location / "vise.prt.1"
    model.write_bytes(b"keep-this-model")
    leftover = location / "README.md"
    leftover.write_text(
        "# Ribbed\n\nManaged by CreoPDM.\n\nDo not edit the `.git` directory. Use CreoPDM to add files and record versions.\n",
        encoding="utf-8",
    )
    added = client.post(
        f"/api/products/{payload['uuid']}/objects/from-disk",
        json={"paths": [str(model)], "comment": "Test model"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["ok"]

    denied = client.post(
        f"/api/products/{payload['uuid']}/forget",
        json={"confirm_name": "wrong"},
    )
    assert denied.status_code == 400
    assert "delete" in denied.json()["error"]["message"].lower()
    assert not (location / ".git").exists()
    assert model.is_file()

    forgotten = client.post(
        f"/api/products/{payload['uuid']}/forget",
        json={"confirm_name": "Ribbed"},
    )
    assert forgotten.status_code == 200, forgotten.text
    listing = client.get("/api/products")
    assert all(item["uuid"] != payload["uuid"] for item in listing.json())
    assert model.is_file()
    assert model.read_bytes() == b"keep-this-model"
    assert not (location / ".git").exists()
    assert not (location / ".gitignore").exists()
    assert not (location / ".creopdm").exists()
    assert not (location / "README.md").exists()
    assert not (data_dir / "vaults" / payload["uuid"]).exists()

    again = client.post("/api/products", json={"name": "Ribbed again"})
    assert again.status_code == 201, again.text
    assert model.is_file()


@requires_git
def test_open_moves_git_from_location_into_workspace(client, app, repo_parent, data_dir):
    payload, location = _create_product(client, repo_parent, name="Legacy Git")
    _attach_legacy_location(app, payload["uuid"], location)
    vault = data_dir / "vaults" / payload["uuid"]
    assert (vault / ".git").exists()
    shutil.copytree(vault / ".git", location / ".git")
    (location / ".gitignore").write_text("*.tst\n", encoding="utf-8")
    (location / ".creopdm").mkdir()
    (location / ".creopdm" / "product.json").write_text("{}\n", encoding="utf-8")
    assert remove_tree(vault / ".git")
    opened = client.get(f"/api/products/{payload['uuid']}")
    assert opened.status_code == 200, opened.text
    assert (vault / ".git").exists()
    assert not (location / ".git").exists()
    assert not (location / ".gitignore").exists()
    assert not (location / ".creopdm").exists()


@requires_git
def test_open_strips_leftover_location_git_when_workspace_already_has_it(client, app, repo_parent, data_dir):
    payload, location = _create_product(client, repo_parent, name="Both Git")
    _attach_legacy_location(app, payload["uuid"], location)
    vault = data_dir / "vaults" / payload["uuid"]
    shutil.copytree(vault / ".git", location / ".git")
    (location / ".gitignore").write_text("*.tst\n", encoding="utf-8")
    opened = client.get(f"/api/products/{payload['uuid']}")
    assert opened.status_code == 200, opened.text
    assert (vault / ".git").exists()
    assert not (location / ".git").exists()
    assert not (location / ".gitignore").exists()

