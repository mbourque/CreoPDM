"""One-shot: find Snapshot compare paste prompts in agent transcripts."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(
    r"C:\Users\micha\.cursor\projects\c-dev-pdm-lite\agent-transcripts"
    r"\704fe3ba-15e4-4f55-b717-c12888ab9b36"
)
NEEDLES = (
    "You are comparing",
    "feature_summary",
    "pattern_member",
    "identity.model_type",
    "PART or ASSEMBLY",
    "Snapshot compare",
    "check-in comment",
    "DRAWING",
)
OUT = Path(r"c:\dev\pdm-lite\_tmp_transcript_prompt_hits.txt")


def text_blobs(obj) -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in {"text", "content", "message"} or isinstance(v, (dict, list, str)):
                found.extend(text_blobs(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(text_blobs(item))
    elif isinstance(obj, str):
        found.append(obj)
    return found


def extract_prompt_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    # Fenced code blocks that look like prompts
    for m in re.finditer(r"```(?:text|markdown|prompt)?\n(.*?)```", text, re.S | re.I):
        body = m.group(1).strip()
        if any(n in body for n in ("You are comparing", "feature_summary", "pattern_member")):
            blocks.append(body)
    # Unfenced: from "You are comparing" through a blank-line run or end-ish
    for m in re.finditer(r"(You are comparing[\s\S]{200,20000})", text):
        chunk = m.group(1)
        # trim at common trailing markers
        for stopper in (
            "\n```",
            "\nPaste",
            "\nOpen Administration",
            "\n# Tests",
            "\n```powershell",
            "\ngit add",
            "\npython -m pytest",
        ):
            if stopper in chunk:
                chunk = chunk.split(stopper, 1)[0]
        blocks.append(chunk.strip())
    return blocks


def main() -> int:
    files = sorted(ROOT.rglob("*"))
    files = [p for p in files if p.is_file()]
    hits: list[str] = []
    prompts: list[tuple[int, str, str]] = []  # length, path, prompt

    hits.append(f"Files under ROOT: {len(files)}")
    for path in files:
        hits.append(f"FILE {path} size={path.stat().st_size}")
        if path.suffix.lower() not in {".jsonl", ".txt", ".md", ".json", ""} and path.suffix:
            # still scan jsonl primarily
            if path.suffix.lower() not in {".jsonl", ".txt", ".md", ".log"}:
                continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            hits.append(f"  READ_FAIL {exc}")
            continue

        # Line-oriented for jsonl
        if path.suffix.lower() == ".jsonl":
            for i, line in enumerate(raw.splitlines(), 1):
                low = line.lower()
                if not any(n.lower() in low for n in NEEDLES):
                    continue
                hits.append(f"  HIT line={i} needles={[n for n in NEEDLES if n.lower() in low]}")
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    for block in extract_prompt_blocks(line):
                        prompts.append((len(block), f"{path}:{i}", block))
                    continue
                for blob in text_blobs(obj):
                    if not any(n in blob for n in NEEDLES):
                        continue
                    for block in extract_prompt_blocks(blob):
                        prompts.append((len(block), f"{path}:{i}", block))
                    # Also keep long assistant messages that contain the phrase even if not fenced
                    if "You are comparing" in blob and len(blob) > 400:
                        # try to isolate paste section
                        idx = blob.find("You are comparing")
                        snippet = blob[idx : idx + 12000]
                        prompts.append((len(snippet), f"{path}:{i}:raw", snippet))
        else:
            if any(n in raw for n in NEEDLES):
                hits.append(f"  HIT (whole file)")
                for block in extract_prompt_blocks(raw):
                    prompts.append((len(block), str(path), block))

    prompts.sort(key=lambda t: t[0], reverse=True)
    # de-dupe by exact text
    seen: set[str] = set()
    unique: list[tuple[int, str, str]] = []
    for item in prompts:
        if item[2] in seen:
            continue
        seen.add(item[2])
        unique.append(item)

    with OUT.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(hits) + "\n\n")
        fh.write(f"UNIQUE_PROMPT_CANDIDATES={len(unique)}\n\n")
        for rank, (length, loc, prompt) in enumerate(unique[:15], 1):
            fh.write(f"===== RANK {rank} len={length} loc={loc} =====\n")
            fh.write(prompt)
            fh.write("\n\n")
    print(f"Wrote {OUT} candidates={len(unique)} hits_lines={len(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
