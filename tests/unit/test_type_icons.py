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


def test_default_type_icons_cover_office_and_creo():
    from creopdm.constants import DEFAULT_TYPE_ICON_BY_LABEL

    assert DEFAULT_TYPE_ICON_BY_LABEL["Part"] == "part.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["Assembly"] == "assembly.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["Drawing"] == "drawing.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["PDF Document"].endswith(".svg")
    assert DEFAULT_TYPE_ICON_BY_LABEL["Word Document"].endswith(".svg")
    assert DEFAULT_TYPE_ICON_BY_LABEL["Excel Document"].endswith(".svg")


def test_filetype_icon_attribution_present():
    path = Path("src/creopdm/static/icons/ATTRIBUTION.txt")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "vscode-icons" in text
