"""Top-level assemblies = not used by another assembly (drawings ignored)."""

from __future__ import annotations

from pathlib import Path

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.constants import DependencyType
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.utils.identity import StaticUserProvider


def _obj(
    product_id: int,
    *,
    filename: str,
    object_type: str,
    uuid: str,
) -> EngineeringObject:
    return EngineeringObject(
        uuid=uuid,
        product_id=product_id,
        name=filename,
        filename=filename,
        extension=filename.rsplit(".", 1)[-1],
        object_type=object_type,
        relative_path=filename,
        revision="A",
        iteration=1,
        lifecycle_state="IN_WORK",
    )


def test_top_level_assemblies_ignore_drawing_parents(data_dir, identity: StaticUserProvider):
    """Where Used present; sub-asm not top-level; drawing-only refs still are."""
    ctx = build_context(ConfigManager(), users=identity)
    with ctx.session_factory() as db:
        product = Product(
            uuid="prod-top-1",
            name="TopAsm",
            vault_folder="top-asm",
            repository_path=str(Path(data_dir) / "vaults" / "top-asm"),
            default_branch="main",
        )
        db.add(product)
        db.flush()

        root = _obj(
            product.id,
            filename="root.asm",
            object_type="CREO_ASSEMBLY",
            uuid="asm-root",
        )
        child = _obj(
            product.id,
            filename="child.asm",
            object_type="CREO_ASSEMBLY",
            uuid="asm-child",
        )
        drawing = _obj(
            product.id,
            filename="root.drw",
            object_type="CREO_DRAWING",
            uuid="drw-root",
        )
        lone = _obj(
            product.id,
            filename="spare.asm",
            object_type="CREO_ASSEMBLY",
            uuid="asm-spare",
        )
        db.add_all([root, child, drawing, lone])
        db.flush()
        db.add_all(
            [
                Dependency(
                    product_id=product.id,
                    parent_object_id=root.id,
                    child_object_id=child.id,
                    dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
                    quantity=1.0,
                ),
                Dependency(
                    product_id=product.id,
                    parent_object_id=drawing.id,
                    child_object_id=root.id,
                    dependency_type=DependencyType.DRAWING_MODEL.value,
                    quantity=1.0,
                ),
                Dependency(
                    product_id=product.id,
                    parent_object_id=drawing.id,
                    child_object_id=lone.id,
                    dependency_type=DependencyType.DRAWING_MODEL.value,
                    quantity=1.0,
                ),
            ]
        )
        db.commit()
        product_id = product.id

        assert ctx.metadata.where_used_index_present(db, product_id) is True
        tops = set(ctx.metadata.top_level_assembly_uuids(db, product_id))
        assert tops == {"asm-root", "asm-spare"}
        assert "asm-child" not in tops


def test_rebuild_clears_false_where_used_so_top_level_returns(
    data_dir, identity: StaticUserProvider
):
    """Stale at311912→844j style edges must clear when parent bytes have no member."""
    from sqlalchemy import select

    ctx = build_context(ConfigManager(), users=identity)
    vault = ctx.config.workspace_for_product("stem-false")
    vault.mkdir(parents=True, exist_ok=True)
    # Parent tree is parts only — no bounded ``844j.asm`` / ``1003573.asm`` token.
    (vault / "at311912.asm").write_bytes(
        b"\x00".join([b"14m7303.prt", b"r44302_3.prt", b"t74416.prt", b"24m7027.prt"])
    )
    (vault / "844j.asm").write_bytes(b"asm")

    with ctx.session_factory() as db:
        product = Product(
            uuid="prod-stem-false",
            name="StemFalse",
            vault_folder="stem-false",
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        parent = _obj(
            product.id,
            filename="at311912.asm",
            object_type="CREO_ASSEMBLY",
            uuid="asm-other",
        )
        child = _obj(
            product.id,
            filename="844j.asm",
            object_type="CREO_ASSEMBLY",
            uuid="asm-top",
        )
        part = _obj(
            product.id,
            filename="14m7303.prt",
            object_type="CREO_PART",
            uuid="prt-14m",
        )
        db.add_all([parent, child, part])
        db.flush()
        db.add(
            Dependency(
                product_id=product.id,
                parent_object_id=parent.id,
                child_object_id=child.id,
                dependency_type=DependencyType.ASSEMBLY_MEMBER.value,
                quantity=1.0,
            )
        )
        db.commit()
        product_uuid = product.uuid
        product_id = product.id
        assert "asm-top" not in set(ctx.metadata.top_level_assembly_uuids(db, product_id))

        result = ctx.metadata.rebuild_where_used_from_vault(
            db, product_uuid, offset=0, limit=40
        )
        db.commit()
        assert result.parents_processed >= 1
        edges = list(
            db.scalars(select(Dependency).where(Dependency.product_id == product_id))
        )
        # Part member may be indexed; false asm→asm edge must be gone.
        assert not any(
            edge.parent_object_id == parent.id and edge.child_object_id == child.id
            for edge in edges
        )
        tops = set(ctx.metadata.top_level_assembly_uuids(db, product_id))
        assert "asm-top" in tops
        assert "asm-other" in tops


def test_where_used_index_absent_without_dependencies(data_dir, identity: StaticUserProvider):
    ctx = build_context(ConfigManager(), users=identity)
    with ctx.session_factory() as db:
        product = Product(
            uuid="prod-empty-wu",
            name="EmptyWU",
            vault_folder="empty-wu",
            repository_path=str(Path(data_dir) / "vaults" / "empty-wu"),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        db.add(
            _obj(
                product.id,
                filename="alone.asm",
                object_type="CREO_ASSEMBLY",
                uuid="asm-alone",
            )
        )
        db.commit()
        assert ctx.metadata.where_used_index_present(db, product.id) is False


def test_top_level_assemblies_pill_wired_in_ui():
    app_html = Path("src/creopdm/templates/app.html").read_text(encoding="utf-8")
    detail = Path("src/creopdm/templates/object_detail.html").read_text(encoding="utf-8")
    pages = Path("src/creopdm/api/pages.py").read_text(encoding="utf-8")
    script = Path("src/creopdm/static/js/app.js").read_text(encoding="utf-8")
    docs = Path("docs/user-interactions.md").read_text(encoding="utf-8")
    assert 'data-filter="top_level_assemblies"' in app_html
    assert "where_used_present" in app_html
    assert "Top level assemblies" in app_html
    assert app_html.index('data-filter="drawings"') < app_html.index(
        'data-filter="top_level_assemblies"'
    )
    assert app_html.index('data-filter="assemblies"') < app_html.index(
        'data-filter="drawings"'
    )
    assert "is_top_level_assembly" in pages
    assert "(Top Level)" in detail
    assert "ASSEMBLY (Top Level)" in detail
    assert "top_level_assemblies" in script
    assert "topLevelAssemblyIds" in script
    chip = script.split("function onMetricChip(", 1)[1].split(
        'document.querySelector("#metric-filters")', 1
    )[0]
    assert 'key === "top_level_assemblies" && next !== "off"' in chip
    assert 'clearMetricFilters(new Set(["top_level_assemblies"]))' in chip
    assert "Top level assemblies" in docs
    assert "current folder only" in docs
    assert "turn **off** every other pill" in docs
    assert "Where Used" in docs
