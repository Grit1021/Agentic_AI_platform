"""Keep the publication-facing AD completed example pinned across rebuilds.

Live analyses continue to return their own server-generated results.  This lock
only protects the static Featured/Completed AD example and its bundled demo
files from being overwritten by archive builders or server-export imports.
"""

from __future__ import annotations

import json
from pathlib import Path


PIN_FILENAME = "pinned_ad_example.json"


def load_pinned_ad(pin_path: str | Path) -> dict:
    path = Path(pin_path)
    if not path.exists():
        raise FileNotFoundError(f"Pinned AD archive is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        example = json.load(handle)
    if example.get("code") != "AD":
        raise ValueError(f"Pinned archive at {path} is not an AD example")
    result = example.get("result") or {}
    pathways = result.get("pathways") or []
    if example.get("gene_count") != 140 or len(pathways) != 16:
        raise ValueError(
            "Pinned AD archive must remain the approved module-6 result "
            "(140 genes, 16 pathways)"
        )
    first = pathways[0] if pathways else {}
    if first.get("name") != "neuroinflammatory response":
        raise ValueError("Pinned AD archive has an unexpected rank-1 pathway")
    return example


def apply_pinned_ad(payload: dict, pin_path: str | Path) -> dict:
    examples = payload.setdefault("examples", {})
    example = load_pinned_ad(pin_path)
    examples["AD"] = example
    payload["default"] = "AD"
    return example


def _dump_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sync_bundled_archives(web_app_dir: str | Path, payload: dict) -> None:
    web_app = Path(web_app_dir)
    web_app.mkdir(parents=True, exist_ok=True)
    ad_result = (payload.get("examples") or {})["AD"]["result"]

    _dump_json(web_app / "offline_completed_examples.json", payload)
    (web_app / "offline_completed_examples.js").write_text(
        "window.OFFLINE_COMPLETED_EXAMPLES = "
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )
    _dump_json(web_app / "offline_demo_data.json", ad_result)
    (web_app / "offline_demo_data.js").write_text(
        "window.OFFLINE_DEMO_RESULT="
        + json.dumps(ad_result, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

