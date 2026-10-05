"""Batch vault tip purge must scan each folder once (not once per tip)."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.object_service import ObjectService


def _service() -> ObjectService:
    return ObjectService(None, None, None, None)  # type: ignore[arg-type]


def test_purge_batch_one_iterdir_per_folder(tmp_path: Path, monkeypatch):
    folder = tmp_path / "vault"
    folder.mkdir()
    tips: list[Path] = []
    for i in range(40):
        tip = folder / f"part{i}.prt"
        tip.write_bytes(b"tip")
        (folder / f"part{i}.prt.2").write_bytes(b"higher")
        tips.append(tip)

    calls = {"n": 0}
    real_iterdir = Path.iterdir

    def counting_iterdir(self: Path):
        if self.resolve() == folder.resolve():
            calls["n"] += 1
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", counting_iterdir)

    _service()._purge_numbered_siblings_for_tips(tips)

    assert calls["n"] == 1
    assert (folder / "part0.prt").is_file()
    assert not (folder / "part0.prt.2").exists()
    assert not (folder / "part39.prt.2").exists()


def test_purge_batch_two_folders_two_iterdirs(tmp_path: Path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    tip_a = a / "shaft.prt"
    tip_b = b / "housing.prt"
    tip_a.write_bytes(b"a")
    tip_b.write_bytes(b"b")
    (a / "shaft.prt.3").write_bytes(b"old")
    (b / "housing.prt.1").write_bytes(b"old")

    scanned: list[str] = []
    real_iterdir = Path.iterdir

    def counting_iterdir(self: Path):
        name = self.name
        if name in {"a", "b"}:
            scanned.append(name)
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", counting_iterdir)

    _service()._purge_numbered_siblings_for_tips([tip_a, tip_b])

    assert sorted(scanned) == ["a", "b"]
    assert not (a / "shaft.prt.3").exists()
    assert not (b / "housing.prt.1").exists()


def test_purge_keeps_lower_saves_when_tip_is_numbered(tmp_path: Path):
    folder = tmp_path / "vault"
    folder.mkdir()
    tip = folder / "shaft.prt.3"
    tip.write_bytes(b"tip")
    lower = folder / "shaft.prt.1"
    lower.write_bytes(b"lower")
    higher = folder / "shaft.prt.5"
    higher.write_bytes(b"higher")
    other = folder / "other.prt.9"
    other.write_bytes(b"other")

    _service()._purge_numbered_siblings(tip)

    assert tip.is_file()
    assert lower.is_file()
    assert not higher.exists()
    assert other.is_file()


def test_import_files_finish_uses_batch_purge():
    """Regression: finish loop must not call per-tip purge (O(n) iterdir)."""
    root = Path(__file__).resolve().parents[2]
    text = (root / "src" / "creopdm" / "services" / "object_service.py").read_text(
        encoding="utf-8"
    )
    assert "_purge_numbered_siblings_for_tips(destinations)" in text
    # Per-tip purge in the finish loop would look like this again:
    marker = "self._record_import_activity("
    assert marker in text
    finish = text.split(marker, 1)[1]
    finish = finish.split("except Exception as exc:")[0]
    assert "_purge_numbered_siblings_for_tips(destinations)" in finish
    assert "_purge_numbered_siblings(destination)" not in finish