#!/usr/bin/env python3
"""Import a locally downloaded official FLAME 2023 Open model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from character_studio.flame import DEFAULT_ROOT, FlameError, calibrate_asset, import_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path, help="Official Open .pkl, numeric .npz, or FLAME2023Open.zip")
    parser.add_argument("--model-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--calibration", type=Path, help="Optional separately reviewed topology-specific calibration JSON")
    args = parser.parse_args(argv)
    try:
        metadata = import_model(args.model, args.model_root)
        if args.calibration:
            calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
            metadata = calibrate_asset(metadata["asset_id"], calibration, args.model_root)
    except (FlameError, OSError, ValueError) as exc:
        print(f"FLAME 导入未完成：{exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: metadata[key] for key in [
        "asset_id", "name", "vertex_count", "triangle_count", "identity_dimension",
        "expression_dimension", "calibration_status", "source_sha256", "license",
    ]}, ensure_ascii=False, indent=2))
    if metadata["calibration_status"] != "ready":
        print("模型可中性预览；鼻翼编辑须先对真实网格完成可视校准。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
