"""Contract: large-product Open must not thin companions or abort Creo early.

JD-scale regressions this locks:
- Discard Where Used >120 → ~23 files materialized
- Sparse WU trusted → vault-scan skipped
- Depth/cap + magnet prune → ~2748 of ~4022
- Fixed 90s Creo openModel → "session may be offline" after materialize
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CREO_SERVICE = ROOT / "src" / "creopdm" / "services" / "creo_service.py"
CREO_DEPS = ROOT / "src" / "creopdm" / "utils" / "creo_dependencies.py"
APP_JS = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"
DOCS = ROOT / "docs" / "user-interactions.md"


def test_contract_never_discard_large_where_used_as_noise():
    body = CREO_SERVICE.read_text(encoding="utf-8")
    deps_for = body.split("def _dependencies_for(", 1)[1].split("def _open_resolved(", 1)[0]
    assert "_MAX_OPEN_FROM_WHERE_USED" not in deps_for
    assert "likely noisy index" not in deps_for
    assert "_SPARSE_OPEN_WHERE_USED" in deps_for
    assert "product-fill" in deps_for


def test_contract_db_walk_allows_thousands_and_deep_trees():
    from creopdm.services.creo_service import (
        _MAX_DEP_DEPENDENCIES,
        _MAX_DEP_DEPENDENCY_DEPTH,
        _MIN_PRODUCT_FILL_WHERE_USED,
        _SPARSE_OPEN_WHERE_USED,
    )

    assert _MAX_DEP_DEPENDENCIES >= 4000
    assert _MAX_DEP_DEPENDENCY_DEPTH >= 32
    assert _SPARSE_OPEN_WHERE_USED == 80
    assert _MIN_PRODUCT_FILL_WHERE_USED == 500
    body = CREO_SERVICE.read_text(encoding="utf-8")
    deps_for = body.split("def _dependencies_for(", 1)[1].split("def _open_resolved(", 1)[0]
    # Regression: 95% coverage skipped fill when only 1 companion was missing (4021/4022).
    assert "_PRODUCT_FILL_COVERAGE" not in body
    assert "len(chosen) < len(companion_siblings)" in deps_for


def test_contract_magnet_prune_allows_shared_jd_subasms():
    from creopdm.utils.creo_dependencies import _MAX_WHERE_USED_ASM_PARENTS

    assert _MAX_WHERE_USED_ASM_PARENTS >= 200
    text = CREO_DEPS.read_text(encoding="utf-8")
    assert "_MAX_WHERE_USED_ASM_PARENTS = 200" in text or "_MAX_WHERE_USED_ASM_PARENTS =" in text


def test_contract_finding_deps_does_not_materialize_tips():
    body = CREO_SERVICE.read_text(encoding="utf-8")
    deps_for = body.split("def _dependencies_for(", 1)[1].split("def _open_resolved(", 1)[0]
    assert "locate_content" in deps_for
    assert "materialize(" not in deps_for


def test_contract_creo_open_timeout_scales_with_dependency_count():
    script = APP_JS.read_text(encoding="utf-8")
    assert "function creoOpenModelTimeoutMs(" in script
    assert "function openWorkTimeoutMs(" in script
    assert "function preparedDependencyCount(" in script
    open_fn = script.split("async function openPdmObjectWork(", 1)[1].split(
        "function openPdmLaunchResult(", 1
    )[0]
    assert "creoOpenModelTimeoutMs(preparedDependencyCount(prepared))" in open_fn
    assert "90000" not in open_fn
    # Outer Open budget must not stay at a hard 3 minutes for JD zip + Retrieve.
    open_wrap = script.split("async function openPdmObject(", 1)[1].split(
        "async function openPdmObjectWork(", 1
    )[0]
    assert "openWorkTimeoutMs(" in open_wrap
    assert "180000" not in open_wrap


def test_contract_docs_mention_fill_and_long_creo_wait():
    docs = DOCS.read_text(encoding="utf-8")
    assert "fill the rest" in docs
    assert "do not fail at 90s" in docs or "session may be offline" in docs
