"""One-off: list creopdm_probe* files under common CreoPDM paths."""
from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

ROOTS: list[Path] = [
    Path(r"C:\Users\micha\AppData\Local\CreoPDM"),
    Path(r"C:\Users\micha\AppData\Local\CreoPDM-agent"),
    Path(r"c:\dev\pdm-lite"),
]

# Optional: Creo / PTC common working dirs (shallow name check only)
EXTRA = [
    Path.home() / "Documents",
    Path(os.environ.get("TEMP", r"C:\Users\micha\AppData\Local\Temp")),
]
for extra in EXTRA:
    if extra.is_dir():
        ROOTS.append(extra)

PREFIX = "creopdm_probe"
by_dir: dict[str, list[str]] = defaultdict(list)
all_paths: list[str] = []

for root in ROOTS:
    if not root.is_dir():
        print(f"SKIP (missing): {root}")
        continue
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().startswith(PREFIX.lower()):
                continue
            full = str(Path(dirpath, name).resolve())
            all_paths.append(full)
            by_dir[str(Path(dirpath).resolve())].append(full)

print(f"TOTAL: {len(all_paths)} file(s)\n")
for d in sorted(by_dir.keys(), key=lambda x: (-len(by_dir[x]), x.lower())):
    files = sorted(by_dir[d], key=str.lower)
    print(f"[{len(files)}] {d}")
    for p in files:
        print(f"  {p}")
    print()

if not all_paths:
    print("(none found under scanned roots)")
