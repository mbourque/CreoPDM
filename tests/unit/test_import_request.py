from creopdm.schemas.common import ImportLocalRequest


def test_import_request_allows_folder_without_paths():
    payload = ImportLocalRequest(folder=r"D:\CAD\Incoming", comment="Add")
    assert payload.paths == []
    assert payload.folder.endswith("Incoming")
    assert payload.base_folder is None


def test_import_request_allows_paths_without_folder():
    payload = ImportLocalRequest(paths=[r"D:\CAD\pin.prt"])
    assert payload.folder is None
    assert payload.paths == [r"D:\CAD\pin.prt"]
