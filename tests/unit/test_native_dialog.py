from pathlib import Path

from creopdm.utils.native_dialog import is_user_cancelled, pick_folder


def _winerror(code: int) -> OSError:
    return OSError(None, "The operation was canceled by the user", None, code)


class _Winerror:
    def __init__(self, winerror):
        self.winerror = winerror


def test_is_user_cancelled_winerror():
    assert is_user_cancelled(_winerror(-2147023673))
    assert is_user_cancelled(_Winerror(0x800704C7))
    assert is_user_cancelled(_winerror(1223))
    assert not is_user_cancelled(_winerror(5))
    assert not is_user_cancelled(RuntimeError("no"))


def test_pick_folder_cancel_does_not_open_winforms(monkeypatch, tmp_path: Path):
    cancelled = _winerror(-2147023673)

    def raise_cancelled(_fn):
        raise cancelled

    monkeypatch.setattr("creopdm.utils.native_dialog.os.name", "nt")
    monkeypatch.setattr("creopdm.utils.native_dialog.run_on_sta", raise_cancelled)
    called = []
    monkeypatch.setattr(
        "creopdm.utils.native_dialog._winforms_folder_dialog",
        lambda *args, **kwargs: called.append(True) or tmp_path,
    )
    assert pick_folder(tmp_path, title="Add a folder to the project") is None
    assert called == []
