"""Log viewer for the tray agent (WinForms on Windows — no Tcl/Tk)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _winforms_script(log_path: Path, title: str) -> str:
    path = str(Path(log_path).resolve())
    return f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$path = {_ps_quote(path)}
$title = {_ps_quote(title)}
$form = New-Object System.Windows.Forms.Form
$form.Text = $title
$form.Width = 780
$form.Height = 500
$form.MinimumSize = New-Object System.Drawing.Size(420, 240)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$timerTop = New-Object System.Windows.Forms.Timer
$timerTop.Interval = 600
$timerTop.Add_Tick({{ $form.TopMost = $false; $timerTop.Stop() }})
$timerTop.Start()
$toolbar = New-Object System.Windows.Forms.Panel
$toolbar.Dock = 'Top'
$toolbar.Height = 36
$pathLabel = New-Object System.Windows.Forms.Label
$pathLabel.Text = $path
$pathLabel.AutoSize = $false
$pathLabel.Dock = 'Fill'
$pathLabel.TextAlign = 'MiddleLeft'
$pathLabel.Padding = New-Object System.Windows.Forms.Padding(8, 0, 0, 0)
$btnClear = New-Object System.Windows.Forms.Button
$btnClear.Text = 'Clear'
$btnClear.Dock = 'Right'
$btnClear.Width = 70
$btnCopy = New-Object System.Windows.Forms.Button
$btnCopy.Text = 'Copy all'
$btnCopy.Dock = 'Right'
$btnCopy.Width = 80
$toolbar.Controls.Add($pathLabel)
$toolbar.Controls.Add($btnClear)
$toolbar.Controls.Add($btnCopy)
$box = New-Object System.Windows.Forms.TextBox
$box.Multiline = $true
$box.ScrollBars = 'Both'
$box.ReadOnly = $true
$box.Dock = 'Fill'
$box.Font = New-Object System.Drawing.Font('Consolas', 10)
$box.WordWrap = $false
$form.Controls.Add($box)
$form.Controls.Add($toolbar)
$script:lastLen = -1
function Refresh-Log {{
  if (-not (Test-Path -LiteralPath $path)) {{
    if ($script:lastLen -ne 0) {{ $box.Text = '(log file not created yet)'; $script:lastLen = 0 }}
    return
  }}
  $len = (Get-Item -LiteralPath $path).Length
  if ($len -eq $script:lastLen) {{ return }}
  $script:lastLen = $len
  $bytes = [System.IO.File]::ReadAllBytes($path)
  if ($bytes.Length -gt 200000) {{ $bytes = $bytes[($bytes.Length - 200000)..($bytes.Length - 1)] }}
  $box.Text = [System.Text.Encoding]::UTF8.GetString($bytes)
  $box.SelectionStart = $box.Text.Length
  $box.ScrollToCaret()
}}
$btnClear.Add_Click({{ [System.IO.File]::WriteAllText($path, ''); $script:lastLen = -1; Refresh-Log }})
$btnCopy.Add_Click({{ [System.Windows.Forms.Clipboard]::SetText($box.Text) }})
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 500
$timer.Add_Tick({{ Refresh-Log }})
$timer.Start()
Refresh-Log
[void]$form.ShowDialog()
"""


def run_viewer_winforms(log_path: Path, *, title: str = "CreoPDM agent log") -> int:
    """Blocking WinForms viewer via PowerShell (works when Tk/Tcl is broken)."""
    import subprocess

    creationflags = 0x08000000 if sys.platform == "win32" else 0
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _winforms_script(log_path, title),
        ],
        check=False,
        creationflags=creationflags,
    )
    return int(completed.returncode or 0)


def run_viewer_tk(log_path: Path, *, title: str = "CreoPDM agent log") -> int:
    import tkinter as tk
    from tkinter import scrolledtext, ttk

    path = log_path.resolve()
    root = tk.Tk()
    root.title(title)
    root.geometry("760x460")
    root.minsize(420, 240)
    try:
        root.attributes("-topmost", True)
        root.after(600, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    toolbar = ttk.Frame(root, padding=(8, 6))
    toolbar.pack(fill=tk.X)
    status = ttk.Label(toolbar, text=str(path))
    status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    text = scrolledtext.ScrolledText(root, wrap=tk.WORD, font=("Consolas", 10))
    text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    state = {"len": -1}

    def _read_tail(max_chars: int = 200_000) -> str:
        if not path.is_file():
            return "(log file not created yet)\n"
        try:
            data = path.read_bytes()
        except OSError as exc:
            return f"(could not read log: {exc})\n"
        if len(data) > max_chars:
            data = data[-max_chars:]
            body = data.decode("utf-8", errors="replace")
            cut = body.find("\n")
            if cut >= 0:
                body = body[cut + 1 :]
            return body
        return data.decode("utf-8", errors="replace")

    def refresh() -> None:
        try:
            size = path.stat().st_size if path.is_file() else 0
        except OSError:
            size = -1
        if size != state["len"]:
            state["len"] = size
            body = _read_tail()
            text.delete("1.0", tk.END)
            text.insert(tk.END, body or "(empty)\n")
            text.see(tk.END)
        root.after(500, refresh)

    def clear_file() -> None:
        try:
            path.write_text("", encoding="utf-8")
        except OSError:
            pass
        state["len"] = -1
        refresh()

    def copy_all() -> None:
        root.clipboard_clear()
        root.clipboard_append(text.get("1.0", tk.END))

    ttk.Button(toolbar, text="Clear", command=clear_file).pack(side=tk.RIGHT)
    ttk.Button(toolbar, text="Copy all", command=copy_all).pack(side=tk.RIGHT, padx=(0, 6))

    refresh()
    root.mainloop()
    return 0


def run_viewer(log_path: Path, *, title: str = "CreoPDM agent log") -> int:
    if sys.platform == "win32":
        return run_viewer_winforms(log_path, title=title)
    return run_viewer_tk(log_path, title=title)


def _show_launch_error(message: str) -> None:
    if sys.platform != "win32":
        print(message, file=sys.stderr)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message[:1500], "CreoPDM agent log", 0x10)
    except Exception:
        print(message, file=sys.stderr)


def open_log_window(log_path: Path, *, title: str = "CreoPDM agent log") -> None:
    """Spawn a separate process so the window appears under pythonw/pystray."""
    import subprocess
    import threading

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("", encoding="utf-8")

    def launch() -> None:
        if sys.platform == "win32":
            try:
                proc = subprocess.Popen(
                    [
                        "powershell",
                        "-NoProfile",
                        "-STA",
                        "-WindowStyle",
                        "Hidden",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                        _winforms_script(path, title),
                    ],
                    close_fds=False,
                    creationflags=0x08000000,
                )
                try:
                    code = proc.wait(timeout=1.5)
                except subprocess.TimeoutExpired:
                    return
                _show_launch_error(
                    f"Log window closed immediately (powershell exited {code}).\n\n"
                    f"Log file:\n{path}"
                )
                return
            except Exception as exc:  # noqa: BLE001
                _show_launch_error(
                    f"Could not open the log window.\n{exc}\n\nLog file:\n{path}"
                )
                return

        # Non-Windows: Tk via a child Python process.
        import os
        import tempfile

        python = Path(sys.executable)
        env = os.environ.copy()
        src = Path(__file__).resolve().parents[1]
        if src.name == "src" and (src / "creopdm_agent").is_dir():
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(src) if not existing else f"{src}{os.pathsep}{existing}"
        err_path = Path(tempfile.gettempdir()) / "creopdm-agent-logui-err.txt"
        try:
            with err_path.open("w", encoding="utf-8") as err_file:
                proc = subprocess.Popen(
                    [
                        str(python),
                        "-m",
                        "creopdm_agent.logui",
                        "--file",
                        str(path),
                        "--title",
                        title,
                    ],
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=err_file,
                    close_fds=False,
                )
            try:
                code = proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                return
            detail = err_path.read_text(encoding="utf-8", errors="replace").strip()
            _show_launch_error(
                f"Could not open the log window (exit {code}).\n{detail}\n\nLog file:\n{path}"
            )
        except Exception as exc:  # noqa: BLE001
            _show_launch_error(f"Could not open the log window.\n{exc}\n\nLog file:\n{path}")

    threading.Timer(0.15, launch).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="creopdm-agent-logui")
    parser.add_argument("--file", required=True, help="Path to the agent log file.")
    parser.add_argument("--title", default="CreoPDM agent log")
    args = parser.parse_args(argv)
    return run_viewer(Path(args.file), title=args.title)


if __name__ == "__main__":
    raise SystemExit(main())
