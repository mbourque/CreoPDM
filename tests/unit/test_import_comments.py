"""Stable Add / import History comments."""

from creopdm.utils.import_comments import resolve_add_commit_message


def test_resolve_add_commit_message_prefers_batch_total_over_chunk_size():
    assert resolve_add_commit_message(None, planned_count=5, batch_total=935) == "Add 935 files"
    assert resolve_add_commit_message("", planned_count=5, batch_total=935) == "Add 935 files"
    assert resolve_add_commit_message("  ", planned_count=5) == "Add 5 files"
    assert resolve_add_commit_message(None, planned_count=1, single_filename="shaft.prt") == "Add shaft.prt"
    assert resolve_add_commit_message("Library import", planned_count=5, batch_total=935) == "Library import"
    assert resolve_add_commit_message(None, planned_count=0, batch_total=0) == "Add files"
