"""Small Tk log viewer for the tray agent."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from creopdm_agent.logbuf import LogBuffer

_lock = threading.Lock()
_thread: threading.Thread | None = None
_app: "_LogApp | None" = None


class _LogApp:
    def __init__(self, buffer: LogBuffer, title: str) -> None:
        self._buffer = buffer
        self._seen = 0
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("720x420")
        self.root.minsize(420, 240)

        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="Clear", command=self._clear).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Copy all", command=self._copy).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(toolbar, text="Live agent log").pack(side=tk.RIGHT)

        self.text = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=("Consolas", 10),
            state=tk.DISABLED,
        )
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.root.protocol("WM_DELETE_WINDOW", self._hide)
        self._pump()

    def _hide(self) -> None:
        self.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _clear(self) -> None:
        self._buffer.clear()
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.configure(state=tk.DISABLED)
        self._seen = 0

    def _copy(self) -> None:
        content = self.text.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(content)

    def _pump(self) -> None:
        generation, lines = self._buffer.snapshot()
        if generation != self._seen:
            self._seen = generation
            self.text.configure(state=tk.NORMAL)
            self.text.delete("1.0", tk.END)
            if lines:
                self.text.insert(tk.END, "\n".join(lines) + "\n")
                self.text.see(tk.END)
            self.text.configure(state=tk.DISABLED)
        self.root.after(400, self._pump)


def open_log_window(buffer: LogBuffer, *, title: str = "CreoPDM agent log") -> None:
    """Open or focus the tray log window (safe to call from the tray menu thread)."""

    def ensure() -> None:
        global _thread, _app

        with _lock:
            if _app is not None:
                try:
                    _app.root.after(0, _app.show)
                    return
                except Exception:
                    _app = None
            if _thread is not None and _thread.is_alive():
                return

            def run() -> None:
                global _app
                app = _LogApp(buffer, title)
                with _lock:
                    _app = app
                app.show()
                app.root.mainloop()
                with _lock:
                    _app = None

            _thread = threading.Thread(target=run, name="creopdm-agent-logui", daemon=True)
            _thread.start()

    # Defer so the tray menu can finish closing first.
    threading.Timer(0.15, ensure).start()
