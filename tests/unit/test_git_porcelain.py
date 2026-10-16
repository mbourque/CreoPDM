"""git status --porcelain paths must survive non-ASCII names and quoted renames."""

from creopdm.services.git_service import _porcelain_path


def test_porcelain_path_decodes_utf8_octal_and_keeps_arrow_in_name():
    # Git quotes café as octal UTF-8 bytes. unicode_escape alone turns that into mojibake.
    assert _porcelain_path('"caf\\303\\251.prt"') == "café.prt"
    # A quoted name that contains " -> " is one path, not a rename with a leftover quote.
    assert _porcelain_path('"a -> b.prt"') == "a -> b.prt"
    assert _porcelain_path('old.prt -> "a -> b.prt"') == "a -> b.prt"
    assert _porcelain_path("plain.prt") == "plain.prt"
    assert _porcelain_path("old.prt -> new.prt") == "new.prt"
