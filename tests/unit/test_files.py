import os
import stat
from pathlib import Path

from creopdm.utils.files import set_file_readonly, set_file_writable


def test_readonly_and_writable_roundtrip(tmp_path: Path):
    path = tmp_path / "part.prt"
    path.write_text("solid", encoding="utf-8")
    set_file_readonly(path)
    readonly_bit_cleared = not (path.stat().st_mode & stat.S_IWRITE)
    readonly_attr = False
    if os.name == "nt" and hasattr(path.stat(), "st_file_attributes"):
        readonly_attr = bool(path.stat().st_file_attributes & 0x1)
    write_blocked = False
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("x")
    except OSError:
        write_blocked = True
    assert readonly_bit_cleared or readonly_attr or write_blocked
    set_file_writable(path)
    path.write_text("changed", encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "changed"
