"""Deterministic static-head geometry and a compact-support nasal-ala edit.

The static scan is deliberately separate from the future FLAME/identity model.
All runtime computations use Python's standard library and always start from
the unchanged base geometry; editing never accumulates from an edited mesh.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE_ASSET_PATH = ROOT / "data/base-face/base-face.json"
BASE_ASSET_ID = "lee-perry-smith-r180-v1"
DEFORMATION_VERSION = "nasal-ala-anatomical-support-v2"
PARAMETER_MIN = -1.0
PARAMETER_MAX = 1.0


def canonical_hash(value: Any) -> str:
    """SHA256 of a strict, deterministic JSON representation."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def geometry_hash(positions: list[list[float]], indices: list[list[int]]) -> str:
    return canonical_hash({"positions": positions, "indices": indices})


def _bump(value: float) -> float:
    """Compact C2 polynomial: zero outside [-1, 1], zero slope at boundary."""
    if abs(value) >= 1:
        return 0.0
    return (1 - value * value) ** 3


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value ** 3 * (value * (value * 6 - 15) + 10)


def region_weight(position: list[float], region: dict[str, Any]) -> float:
    x, y, z = position
    abs_x = abs(x - region["midline_x"])
    if (abs_x <= region["protected_center_half_width"]
            or z >= region["protected_tip_min_z"]
            or y >= region["protected_bridge_min_y"]):
        return 0.0
    protected_ramp = _smoothstep((abs_x - region["protected_center_half_width"])
                                 / region["protected_transition_width"])
    tip_ramp = _smoothstep((region["protected_tip_min_z"] - z)
                           / region["tip_transition_width"])
    return (protected_ramp * tip_ramp
            * _bump((abs_x - region["center_abs_x"]) / region["radius_x"])
            * _bump((y - region["center_y"]) / region["radius_y"])
            * _bump((z - region["center_z"]) / region["radius_z"]))


def _bounds(positions: list[list[float]]) -> dict[str, list[float]]:
    minimum = [min(p[i] for p in positions) for i in range(3)]
    maximum = [max(p[i] for p in positions) for i in range(3)]
    return {"min": minimum, "max": maximum,
            "center": [(a + b) / 2 for a, b in zip(minimum, maximum)],
            "size": [b - a for a, b in zip(minimum, maximum)]}


@lru_cache(maxsize=1)
def _cached_base() -> dict[str, Any]:
    if not BASE_ASSET_PATH.is_file():
        raise FileNotFoundError("Base mesh is missing. Run python3 scripts/prepare_face_asset.py")
    asset = json.loads(BASE_ASSET_PATH.read_text(encoding="utf-8"))
    if asset.get("asset_id") != BASE_ASSET_ID:
        raise ValueError("Unsupported base mesh ID")
    points, faces = asset["positions"], asset["indices"]
    if not points or not faces:
        raise ValueError("Base mesh is empty")
    if not all(len(p) == 3 and all(math.isfinite(v) for v in p) for p in points):
        raise ValueError("Invalid base vertices")
    if not all(len(f) == 3 and all(isinstance(i, int) and 0 <= i < len(points) for i in f)
               for f in faces):
        raise ValueError("Invalid triangle indices")
    weights = [region_weight(p, asset["edit_region"]) for p in points]
    maximum = max(weights)
    if maximum <= 0:
        raise ValueError("Nasal region contains no vertices")
    weights = [round(w / maximum, 12) for w in weights]
    active = [i for i, w in enumerate(weights) if w > 0]
    landmarks = []
    for target in asset["edit_region"]["measurement_targets"]:
        landmarks.append(min(active, key=lambda i: sum((points[i][d] - target[d]) ** 2 for d in range(3))))
    asset["mask_weights"] = weights
    asset["alar_landmark_indices"] = landmarks
    asset["topology_hash"] = canonical_hash({"vertex_count": len(points), "indices": faces})
    asset["base_geometry_hash"] = geometry_hash(points, faces)
    asset["bounds"] = _bounds(points)
    return asset


def load_base_asset() -> dict[str, Any]:
    """Return an independent copy so callers cannot mutate the shared template."""
    return deepcopy(_cached_base())


def get_asset_info() -> dict[str, Any]:
    base = _cached_base()
    excluded = {"positions", "indices", "uvs", "mask_weights"}
    result = {k: deepcopy(v) for k, v in base.items() if k not in excluded}
    result.update(vertex_count=len(base["positions"]), triangle_count=len(base["indices"]),
                  deformation_version=DEFORMATION_VERSION,
                  parameter_range={"min": PARAMETER_MIN, "max": PARAMETER_MAX, "default": 0.0},
                  editable_vertex_count=sum(w > 0 for w in base["mask_weights"]))
    return result


def build_geometry(nose_width: float = 0.0) -> dict[str, Any]:
    """Edit nasal alae only; -1 narrows, +1 widens, 0 is the exact base mesh.

    This dimensionless control is not itself a percentage. The actual change
    in the asset-specific alar landmark span is returned in stats.
    """
    if (isinstance(nose_width, bool) or not isinstance(nose_width, (int, float))
            or not math.isfinite(nose_width)):
        raise ValueError("nose_width must be a finite number")
    if not PARAMETER_MIN <= nose_width <= PARAMETER_MAX:
        raise ValueError("nose_width must be in [-1, 1]")
    amount = float(nose_width)
    if amount == 0:
        amount = 0.0  # canonicalise negative zero for stable snapshots
    base = _cached_base()
    region = base["edit_region"]
    positions = []
    changed = 0
    max_displacement = 0.0
    outside_displacement = 0.0
    protected_tip_displacement = 0.0
    protected_bridge_displacement = 0.0
    for point, weight in zip(base["positions"], base["mask_weights"]):
        x, y, z = point
        delta = amount * region["max_lateral_displacement"] * weight
        if x < region["midline_x"]:
            delta = -delta
        edited = [round(x + delta, 9), y, z] if weight and amount else point.copy()
        displacement = abs(edited[0] - x)
        changed += displacement > 0
        max_displacement = max(max_displacement, displacement)
        if weight == 0:
            outside_displacement = max(outside_displacement, displacement)
        if abs(x - region["midline_x"]) <= region["protected_center_half_width"] or z >= region["protected_tip_min_z"]:
            protected_tip_displacement = max(protected_tip_displacement, displacement)
        if y >= region["protected_bridge_min_y"]:
            protected_bridge_displacement = max(protected_bridge_displacement, displacement)
        positions.append(edited)
    left, right = base["alar_landmark_indices"]
    baseline_span = abs(base["positions"][right][0] - base["positions"][left][0])
    edited_span = abs(positions[right][0] - positions[left][0])
    return {
        "asset_id": BASE_ASSET_ID,
        "deformation_version": DEFORMATION_VERSION,
        "parameters": {"nose_width": amount},
        "positions": positions,
        "indices": deepcopy(base["indices"]),
        "uvs": deepcopy(base["uvs"]),
        "mask_weights": base["mask_weights"].copy(),
        "geometry_hash": geometry_hash(positions, base["indices"]),
        "base_geometry_hash": base["base_geometry_hash"],
        "topology_hash": base["topology_hash"],
        "bounds": _bounds(positions),
        "face_target": base["face_target"].copy(),
        "unit": base["unit"],
        "metadata": get_asset_info(),
        "stats": {
            "vertex_count": len(positions), "triangle_count": len(base["indices"]),
            "editable_vertex_count": sum(w > 0 for w in base["mask_weights"]),
            "changed_vertices": changed,
            "max_displacement": max_displacement,
            "outside_max_displacement": outside_displacement,
            "tip_max_displacement": protected_tip_displacement,
            "bridge_max_displacement": protected_bridge_displacement,
            "nose_width_measure": edited_span,
            "baseline_nose_width": baseline_span,
            "nose_width_change_ratio": edited_span / baseline_span - 1,
            "alar_landmark_indices": base["alar_landmark_indices"].copy(),
            "measurement_note": "Asset-specific landmark span in canonical units, not a clinical or millimeter measurement.",
        },
    }
