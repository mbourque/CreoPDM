"""Type icon mapping from settings labels / extensions."""

from creopdm.utils.classify import resolve_type_icon, type_icon_client_payload
from pathlib import Path


def test_resolve_type_icon_by_label_and_extension():
    pdf = resolve_type_icon(type_label="PDF Document")
    assert pdf in {"pdf.svg", "pdf.png"}
    word = resolve_type_icon(extension=".docx")
    assert word in {"word.svg", "word.png"}
    sw = resolve_type_icon(extension=".sldprt")
    assert sw in {"sldprt.svg", "sldprt.png"}
    assert resolve_type_icon(object_type="CREO_PART") == "part.png"
    text = resolve_type_icon(filename="notes.txt")
    assert text in {"text.svg", "text.png"}
    audio = resolve_type_icon(type_label="Audio", extension=".mp3")
    assert audio in {"audio.svg", "audio.png"}


def test_type_icon_client_payload_includes_settings_extensions():
    payload = type_icon_client_payload()
    assert payload["by_ext"][".pdf"] in {"pdf.svg", "pdf.png"}
    assert payload["by_label"]["Word Document"] in {"word.svg", "word.png"}
    assert payload["by_object_type"]["CREO_DRAWING"] == "drawing.png"


def test_windows_icon_extract_script_exists():
    assert Path("scripts/extract_windows_filetype_icons.py").is_file()
