"""One-off: promote probe .creojs into static/creo_inventory/ with IIFE wrappers."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "creopdm" / "static"
OUT = STATIC / "creo_inventory"

CONFIGS = [
    {
        "probe": STATIC / "feature_probe" / "feature_probe.creojs",
        "out": OUT / "features.creojs",
        "comment": "feature_probe",
        "var": "__creoInvFeatures",
        "for_model": "listFeaturesForModel",
        "session": "listSessionFeatures",
        "extra_exports": ["exportSessionInfo"],
        "session_replace": (
            "function listSessionFeatures() {\n"
            "  var am = activeModel();\n"
            "  if (am.error) return { ok: false, error: am.error };\n"
            "  var session = am.session;\n"
            "  var model = am.model;\n"
        ),
        "for_model_header": "function listFeaturesForModel(model, session) {\n",
    },
    {
        "probe": STATIC / "assembly_probe" / "assembly_probe.creojs",
        "out": OUT / "assembly.creojs",
        "comment": "assembly_probe",
        "var": "__creoInvAssembly",
        "for_model": "listAssemblyStructureForModel",
        "session": "listSessionAssemblyStructure",
        "extra_exports": [],
        "session_replace": (
            "function listSessionAssemblyStructure() {\n"
            "  var am = activeModel();\n"
            "  if (am.error) return { ok: false, error: am.error };\n"
            "  var session = am.session;\n"
            "  var model = am.model;\n"
        ),
        "for_model_header": "function listAssemblyStructureForModel(model, session) {\n",
    },
    {
        "probe": STATIC / "drawing_probe" / "drawing_probe.creojs",
        "out": OUT / "drawing.creojs",
        "comment": "drawing_probe",
        "var": "__creoInvDrawing",
        "for_model": "listDrawingStructureForModel",
        "session": "listSessionDrawingStructure",
        "extra_exports": [],
        "session_replace": (
            "function listSessionDrawingStructure() {\n"
            "  var am = activeModel();\n"
            "  if (am.error) return { ok: false, error: am.error };\n"
            "  var model = am.model;\n"
        ),
        "for_model_header": "function listDrawingStructureForModel(model, session) {\n",
    },
]


def body_from_probe(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    # Drop leading file comment block
    if text.startswith("/*"):
        end = text.find("*/")
        if end >= 0:
            text = text[end + 2 :].lstrip("\n")
    return text


def wrap(cfg: dict) -> None:
    body = body_from_probe(cfg["probe"])
    session_fn = cfg["session"]
    if cfg["session_replace"] not in body:
        raise SystemExit(f"{cfg['probe']}: expected session function header missing")
    body = body.replace(cfg["session_replace"], cfg["for_model_header"], 1)
    # Thin session wrapper after the for-model function (insert before EOF)
    session_wrapper = f"""
function {cfg['session']}() {{
  var am = activeModel();
  if (am.error) return {{ ok: false, error: am.error }};
  return {cfg['for_model']}(am.model, am.session);
}}
"""
    if not body.rstrip().endswith("}"):
        raise SystemExit(f"{cfg['probe']}: unexpected EOF")
    body = body.rstrip() + session_wrapper

    exports = [
        f"    listForModel: {cfg['for_model']},",
        f"    listSession: {cfg['session']},",
    ]
    for name in cfg["extra_exports"]:
        exports.append(f"    {name}: {name},")
    export_block = "\n".join(exports)

    global_fns = [
        f"function {cfg['for_model']}(model, session) {{ return {cfg['var']}.listForModel(model, session); }}",
        f"function {cfg['session']}() {{ return {cfg['var']}.listSession(); }}",
    ]
    for name in cfg["extra_exports"]:
        global_fns.append(
            f"function {name}(featIds) {{ return {cfg['var']}.{name}(featIds); }}"
        )

    out_text = f"""/* CreoPDM inventory — promoted from {cfg['comment']} */
var {cfg['var']} = (function () {{
{body}
  return {{
{export_block}
  }};
}})();
{chr(10).join(global_fns)}
"""
    cfg["out"].parent.mkdir(parents=True, exist_ok=True)
    cfg["out"].write_text(out_text, encoding="utf-8", newline="\n")
    print(f"Wrote {cfg['out']} ({len(out_text)} bytes)")


def main() -> None:
    for cfg in CONFIGS:
        wrap(cfg)


if __name__ == "__main__":
    main()
