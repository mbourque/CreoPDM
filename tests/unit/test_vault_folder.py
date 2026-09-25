from creopdm.exceptions import PathValidationError, ValidationAppError
from creopdm.utils.vault_folder import normalize_uuid_folder, validate_vault_folder
import pytest


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
