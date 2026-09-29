from creopdm.exceptions import PathValidationError, ValidationAppError
from creopdm.utils.vault_folder import (
    VAULT_FOLDER_IMMUTABLE_MESSAGE,
    normalize_uuid_folder,
    reject_vault_folder_change,
    validate_vault_folder,
)
import pytest
from types import SimpleNamespace


def test_validate_vault_folder_allows_uuid_and_slug():
    uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert validate_vault_folder(uid) == uid
    assert validate_vault_folder("Robot-Arm_v2") == "Robot-Arm_v2"
    assert normalize_uuid_folder("A1B2C3D4-E5F6-7890-ABCD-EF1234567890") == uid


@pytest.mark.parametrize(
    "bad",
    ["Robot Arm", "a/b", r"a\b", "../x", ".creopdm", "", "bad name!"],
)
def test_validate_vault_folder_rejects_spaces_and_paths(bad):
    with pytest.raises((ValidationAppError, PathValidationError)):
        validate_vault_folder(bad)


def test_reject_vault_folder_change_allows_blank_or_same():
    product = SimpleNamespace(uuid="u1", vault_folder="Robot-Arm")
    reject_vault_folder_change(product, None)
    reject_vault_folder_change(product, "")
    reject_vault_folder_change(product, "Robot-Arm")


def test_reject_vault_folder_change_blocks_rename():
    product = SimpleNamespace(uuid="u1", vault_folder="Robot-Arm")
    with pytest.raises(ValidationAppError, match="cannot be changed") as exc:
        reject_vault_folder_change(product, "Other-Vault")
    assert exc.value.message == VAULT_FOLDER_IMMUTABLE_MESSAGE
    assert exc.value.details["vault_folder"] == "Robot-Arm"
