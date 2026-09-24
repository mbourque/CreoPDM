"""Type icon mapping from settings labels / extensions."""

from pathlib import Path

from creopdm.utils.classify import resolve_type_icon, type_icon_client_payload


def test_resolve_type_icon_by_label_and_extension():
    assert resolve_type_icon(type_label="PDF Document") == "pdf.svg"
    assert resolve_type_icon(extension=".docx") == "word.svg"
    assert resolve_type_icon(extension=".sldprt") == "sldprt.svg"
    assert resolve_type_icon(type_label="Image File") == "image.svg"
    assert resolve_type_icon(extension=".json") == "json.svg"
    assert resolve_type_icon(object_type="CREO_PART") == "part.png"
    assert resolve_type_icon(filename="notes.txt") == "text.svg"
    assert resolve_type_icon(type_label="Audio", extension=".mp3") == "audio.svg"


def test_type_icon_client_payload_includes_settings_extensions():
    payload = type_icon_client_payload()
    assert payload["by_ext"][".pdf"] == "pdf.svg"
    assert payload["by_label"]["Word Document"] == "word.svg"
    assert payload["by_label"]["Image File"] == "image.svg"
    assert payload["by_object_type"]["CREO_DRAWING"] == "drawing.png"


def test_material_icon_fetch_script_exists():
    assert Path("scripts/fetch_type_icons.py").is_file()
    assert "material-icon-theme" in open("scripts/fetch_type_icons.py", encoding="utf-8").read()
