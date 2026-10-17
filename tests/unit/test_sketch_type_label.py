"""Creo 2D sections (.sec) read SKETCH in the Type column, Overview and settings defaults."""

from creopdm.config import AppSettings, ConfigManager
from creopdm.constants import DEFAULT_TYPE_LABELS
from creopdm.utils.classify import display_type_label, type_label_maps, unique_type_labels
from creopdm.utils.creo_model_class import files_list_type_from_identity_json, model_type_display


def test_sec_files_read_sketch_in_the_type_column():
    names, extensions = type_label_maps(DEFAULT_TYPE_LABELS)
    assert extensions[".sec"] == "SKETCH"
    assert display_type_label("test-sec.sec", "OTHER", names=names, extensions=extensions) == "SKETCH"


def test_collected_section_model_type_reads_sketch():
    assert model_type_display("SECTION") == "SKETCH"
    assert model_type_display("PART") == "PART"
    assert model_type_display("") == ""
    assert files_list_type_from_identity_json('{"model_type":"MDL_2D_SECTION"}') == "SKETCH"
    assert files_list_type_from_identity_json('{"model_type":"PART"}') == "PART"


def test_installs_on_the_old_section_default_migrate_to_sketch(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    legacy = [dict(item) for item in DEFAULT_TYPE_LABELS]
    for item in legacy:
        if item["extension"] == ".sec":
            item["label"] = "Section"  # the label before it became SKETCH
    settings.cad.type_labels = legacy
    manager.save(settings)
    loaded = manager.load()
    labels = {item["extension"]: item["label"] for item in unique_type_labels(loaded.cad.type_labels)}
    assert labels[".sec"] == "SKETCH"
    assert unique_type_labels(loaded.cad.type_labels) == unique_type_labels(DEFAULT_TYPE_LABELS)


def test_current_defaults_are_not_rewritten_on_every_load(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    manager.save(AppSettings())
    before = manager.settings_path.read_text(encoding="utf-8")
    manager._settings = None
    manager.load()
    assert manager.settings_path.read_text(encoding="utf-8") == before


def test_a_customised_section_label_is_kept(tmp_path):
    manager = ConfigManager(tmp_path / "appdata")
    manager.ensure_layout()
    settings = AppSettings()
    settings.cad.type_labels = [
        {"extension": ".sec", "label": "Section"},
        {"extension": ".prt", "label": "Custom Part"},
    ]
    manager.save(settings)
    loaded = manager.load()
    assert unique_type_labels(loaded.cad.type_labels) == [
        {"extension": ".sec", "label": "Section"},
        {"extension": ".prt", "label": "Custom Part"},
    ]
