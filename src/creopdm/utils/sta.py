"""Run COM-sensitive Windows APIs on an STA thread.

ShellExecute / GetOpenFileNameW do not show UI from FastAPI worker threads.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import TypeVar

_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0
_S_FALSE = 1

T = TypeVar("T")


def run_on_sta(func: Callable[[], T]) -> T:
    """Run func on a COM STA thread when on Windows; otherwise call it directly."""
    if os.name != "nt":
        return func()
    holder: list[object] = []

    def target() -> None:
        initialized = False
        try:
            import ctypes

            hr = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
            initialized = hr in (_S_OK, _S_FALSE)
            holder.append(func())
        except Exception as exc:  # pragma: no cover - Windows UI path
            holder.append(exc)
        finally:
            if initialized:
                import ctypes

                ctypes.windll.ole32.CoUninitialize()

    thread = threading.Thread(target=target, name="creopdm-sta")
    thread.start()
    thread.join()
    if not holder:
        raise RuntimeError("Windows UI thread exited without a result.")
    result = holder[0]
    if isinstance(result, Exception):
        raise result
    return result  # type: ignore[return-value]
