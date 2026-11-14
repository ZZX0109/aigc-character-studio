"""Write validated before/after reference bundles; never render or run models.

PNG inputs are supplied by the local Three.js client. Validation proves their
format, pairing and saved-mesh provenance, not that pixels depict the mesh.
Raw FLAME model files and blendshape bases are never included in this bundle.
"""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4
import zipfile

from PIL import Image, ImageDraw

from .geometry import canonical_hash, geometry_hash


VIEW_YAWS = {-90, -45, 0, 45, 90}
VIEW_ORDER = [0, -45, 45, -90, 90]
SAFE_NAME = re.compile(r"^[a-z0-9_-]{1,40}$")
PUBLIC_ASSET_FIELDS = {
    "asset_id", "name", "asset_kind", "model_variant", "model_version",
    "license", "license_url", "source_url", "source_sha256", "attribution",
    "license_source_url", "license_source_sha256", "deformation_version",
    "calibration_status", "calibration_hash", "coordinate_system", "unit",
    "identity_dimensions", "expression_dimensions", "vertex_count",
    "identity_dimension", "expression_dimension", "source_verification",
    "triangle_count", "limitations", "model_format", "imported_at",
}


class PairExportError(ValueError):
    """The pair is inconsistent, malformed, or cannot support the claimed edit."""


def _finite_tree(value: Any, location: str = "input") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise PairExportError(f"{location}: non-finite numbers are forbidden")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_tree(item, f"{location}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _finite_tree(item, f"{location}[{index}]")


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PairExportError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise PairExportError(f"{label} must be finite") from exc
    if not math.isfinite(number):
        raise PairExportError(f"{label} must be finite")
    return number


def _validate_geometry(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise PairExportError(f"{label} must be a geometry object")
    _finite_tree(value, label)
    positions, indices = value.get("positions"), value.get("indices")
    if not isinstance(positions, list) or not 3 <= len(positions) <= 1_000_000:
        raise PairExportError(f"{label}: positions must be a nonempty triangle-mesh vertex list")
    for row in positions:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise PairExportError(f"{label}: each position must contain three numbers")
        for number in row:
            _number(number, f"{label}.positions")
    if not isinstance(indices, list) or not 1 <= len(indices) <= 2_000_000:
        raise PairExportError(f"{label}: indices must contain triangles")
    for face in indices:
        if (not isinstance(face, (tuple, list)) or len(face) != 3
                or any(type(index) is not int or not 0 <= index < len(positions) for index in face)
                or len(set(face)) != 3):
            raise PairExportError(f"{label}: invalid triangle indices")
    actual_hash = geometry_hash(positions, indices)
    if value.get("geometry_hash") != actual_hash:
        raise PairExportError(f"{label}: geometry hash does not match the actual mesh")
    actual_topology = canonical_hash({"vertex_count": len(positions), "indices": indices})
    if value.get("topology_hash") != actual_topology:
        raise PairExportError(f"{label}: topology hash does not match the actual mesh")
    parameters = value.get("parameters")
    if not isinstance(parameters, dict) or "nose_width" not in parameters:
        raise PairExportError(f"{label}: parameters.nose_width is required")
    if not -1 <= _number(parameters["nose_width"], f"{label}.nose_width") <= 1:
        raise PairExportError(f"{label}: nose_width must be in [-1, 1]")
    weights = value.get("mask_weights")
    if not isinstance(weights, list) or len(weights) != len(positions):
        raise PairExportError(f"{label}: mask_weights must match the vertex count")
    if any(not 0 <= _number(weight, f"{label}.mask_weights") <= 1 for weight in weights):
        raise PairExportError(f"{label}: mask weights must be in [0, 1]")
    return value


def _view_dict(view: Any) -> dict:
    if isinstance(view, dict):
        return view
    if callable(getattr(view, "model_dump", None)):
        value = view.model_dump()
        if isinstance(value, dict):
            return value
    raise PairExportError("Each view must be an object")


def _decode_views(views: Any, label: str) -> dict[int, dict]:
    if not isinstance(views, (list, tuple)) or len(views) != 5:
        raise PairExportError(f"{label}: exactly five standard views are required")
    result: dict[int, dict] = {}
    names = set()
    for item in views:
        view = _view_dict(item)
        name = view.get("name")
        if not isinstance(name, str) or not SAFE_NAME.fullmatch(name) or name in names:
            raise PairExportError(f"{label}: view names must be unique safe identifiers")
        yaw = _number(view.get("yaw_degrees"), f"{label}.yaw_degrees")
        if yaw not in VIEW_YAWS or yaw in result:
            raise PairExportError(f"{label}: views must use unique yaw values 0, ±45 and ±90")
        encoded = view.get("png_base64")
        if not isinstance(encoded, str) or len(encoded) > 8_000_000:
            raise PairExportError(f"{label}: invalid PNG data")
        if encoded.startswith("data:"):
            if not encoded.startswith("data:image/png;base64,"):
                raise PairExportError(f"{label}: only PNG data URLs are accepted")
            encoded = encoded.partition(",")[2]
        try:
            raw = base64.b64decode(encoded, validate=True)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("not PNG")
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != "PNG" or image.size != (768, 768):
                    raise ValueError("wrong image format or size")
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()  # Truncated image streams can pass header checks.
        except (ValueError, OSError, binascii.Error, Image.DecompressionBombError) as exc:
            raise PairExportError(f"{label}: each image must be a complete 768×768 PNG") from exc
        names.add(name)
        result[int(yaw)] = {"name": name, "yaw_degrees": yaw, "raw": raw,
                            "sha256": hashlib.sha256(raw).hexdigest()}
    return result


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def _write_mesh(directory: Path, mesh: dict, character: dict, role: str) -> None:
    directory.mkdir()
    _write_json(directory / "mesh.json", {
        "vertices": mesh["positions"], "faces": mesh["indices"],
        "geometry_hash": mesh["geometry_hash"], "topology_hash": mesh["topology_hash"],
        "coordinate_system": "right_handed_y_up_face_positive_z", "unit": mesh.get("unit"),
    })
    document = deepcopy(character)
    document.pop("mesh_vertices", None)
    source_snapshot_hash = document.pop("snapshot_hash", None)
    if source_snapshot_hash is not None:
        document["source_saved_snapshot_hash"] = source_snapshot_hash
    document.update(nose_width=mesh["parameters"]["nose_width"], geometry_hash=mesh["geometry_hash"],
                    reference_role=role, source_saved_revision=character["revision"],
                    derived_reference_not_a_separate_saved_revision=True,
                    parameters=deepcopy(mesh["parameters"]))
    _write_json(directory / "character.json", document)
    with (directory / "mesh.obj").open("w", encoding="utf-8") as stream:
        stream.write(f"# {role} reference; +Y up, +Z front. Attribution in ../manifest.json\n")
        for position in mesh["positions"]:
            stream.write("v " + " ".join(format(v, ".17g") for v in position) + "\n")
        for face in mesh["indices"]:
            stream.write("f " + " ".join(str(index + 1) for index in face) + "\n")


def export_pair_bundle(*, character: dict, baseline_geometry: dict,
                       edited_geometry: dict, baseline_views: list,
                       edited_views: list, asset: dict, verification: dict,
                       output_root: str | Path) -> dict:
    """Publish one atomic paired bundle, raising PairExportError before partial output.

    The baseline is derived from the same saved identity/expression with nose_width=0.
    Both geometries must use identical topology, non-edit parameters and support.
    Five corresponding PNGs per state must use matching names and declared yaw.
    """
    for label, value in (("character", character), ("asset", asset), ("verification", verification)):
        if not isinstance(value, dict):
            raise PairExportError(f"{label} must be an object")
        _finite_tree(value, label)
    if verification.get("passed") is not True:
        raise PairExportError("Saved character verification must pass before paired export")
    if (not isinstance(character.get("id"), str)
            or type(character.get("revision")) is not int or character["revision"] < 1):
        raise PairExportError("A saved character ID and positive revision are required")
    for key, expected in (("character_id", character["id"]), ("revision", character["revision"])):
        if key in verification and verification[key] != expected:
            raise PairExportError("Verification does not belong to the requested character revision")
    baseline = _validate_geometry(baseline_geometry, "baseline")
    edited = _validate_geometry(edited_geometry, "edited")
    if baseline["parameters"]["nose_width"] != 0:
        raise PairExportError("The baseline nose_width must be zero")
    if edited["parameters"]["nose_width"] != _number(character.get("nose_width"), "character.nose_width"):
        raise PairExportError("Edited nose_width does not match the saved character")
    if character.get("geometry_hash") != edited["geometry_hash"]:
        raise PairExportError("Edited geometry does not match the saved character hash")
    if ("geometry_hash" in verification
            and verification["geometry_hash"] != edited["geometry_hash"]):
        raise PairExportError("Verification geometry hash does not match the saved edit")
    if ("topology_id" in character
            and character["topology_id"] != edited["topology_hash"]):
        raise PairExportError("The mesh topology does not match the saved character")
    if (baseline["topology_hash"] != edited["topology_hash"]
            or baseline["indices"] != edited["indices"]
            or len(baseline["positions"]) != len(edited["positions"])):
        raise PairExportError("The pair must have exactly the same vertices and topology")
    for key in ("asset_id", "deformation_version", "unit"):
        if baseline.get(key) != edited.get(key):
            raise PairExportError(f"The pair must share the same {key}")
    if asset.get("asset_id") is not None and asset["asset_id"] != edited.get("asset_id"):
        raise PairExportError("Asset metadata does not match the paired geometry")
    if character.get("base_asset_id") is not None and character["base_asset_id"] != edited.get("asset_id"):
        raise PairExportError("The pair uses a different asset than the saved character")
    if baseline["mask_weights"] != edited["mask_weights"]:
        raise PairExportError("The pair must share the same canonical edit support")
    base_params = {k: v for k, v in baseline["parameters"].items() if k != "nose_width"}
    edit_params = {k: v for k, v in edited["parameters"].items() if k != "nose_width"}
    if base_params != edit_params:
        raise PairExportError("Identity, expression and other non-edit parameters must remain fixed")
    before = _decode_views(baseline_views, "baseline_views")
    after = _decode_views(edited_views, "edited_views")
    if any(before[yaw]["name"] != after[yaw]["name"] for yaw in VIEW_ORDER):
        raise PairExportError("Each paired yaw must use the same view name")
    deltas = [[b - a for a, b in zip(old, new)]
              for old, new in zip(baseline["positions"], edited["positions"])]
    lengths = [math.sqrt(sum(v * v for v in row)) for row in deltas]
    if any(not math.isfinite(length) for length in lengths):
        raise PairExportError("Vertex displacement magnitude is not finite")
    outside_max = max((length for length, weight in zip(lengths, edited["mask_weights"])
                       if weight == 0), default=0.0)
    if outside_max != 0:
        raise PairExportError("Vertices outside the declared edit support have changed")
    changed_indices = [index for index, length in enumerate(lengths) if length != 0]
    warnings = []
    if not changed_indices:
        warnings.append("zero_edit: both meshes are identical; this bundle does not demonstrate an edit")
    if not changed_indices and edited["parameters"]["nose_width"] != 0:
        warnings.append("nonzero_parameter_without_geometry_change")
    public_asset = {key: deepcopy(value) for key, value in asset.items() if key in PUBLIC_ASSET_FIELDS}
    stamp = datetime.now(timezone.utc)
    pair_id = "pair_" + stamp.strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:12]
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    final = root / pair_id
    pending = root / ("." + pair_id + ".pending")
    pending.mkdir(exist_ok=False)
    try:
        _write_mesh(pending / "baseline", baseline, character, "baseline_derived")
        _write_mesh(pending / "edited", edited, character, "edited_saved")
        for role in ("baseline", "edited"):
            (pending / role / "views").mkdir()
        sheet = Image.new("RGB", (1600, 756), "#f1eee8")
        draw = ImageDraw.Draw(sheet)
        pairs = []
        for row_index, (role, views) in enumerate((("baseline", before), ("edited", after))):
            top = row_index * 378
            draw.text((14, top + 10), "BASELINE / nose_width = 0" if role == "baseline"
                      else f"EDITED / nose_width = {edited['parameters']['nose_width']:g}", fill="#27251f")
            for column, yaw in enumerate(VIEW_ORDER):
                view = views[yaw]
                (pending / role / "views" / f"{view['name']}.png").write_bytes(view["raw"])
                with Image.open(io.BytesIO(view["raw"])) as image:
                    thumbnail = image.convert("RGB").resize((320, 320), Image.Resampling.LANCZOS)
                    sheet.paste(thumbnail, (column * 320, top + 30))
                draw.text((column * 320 + 12, top + 358), f"{view['name']} / {yaw:g} deg", fill="#27251f")
        for yaw in VIEW_ORDER:
            original, changed = before[yaw], after[yaw]
            pairs.append({"name": original["name"], "yaw_degrees": yaw,
                          "baseline_path": f"baseline/views/{original['name']}.png",
                          "edited_path": f"edited/views/{changed['name']}.png",
                          "baseline_sha256": original["sha256"], "edited_sha256": changed["sha256"]})
        sheet.save(pending / "contact-sheet.png")
        delta_document = {
            "coordinate_system": "right_handed_y_up_face_positive_z", "unit": edited.get("unit"),
            "baseline_geometry_hash": baseline["geometry_hash"], "edited_geometry_hash": edited["geometry_hash"],
            "canonical_vertex_delta": deltas, "support_mask": edited["mask_weights"],
            "changed_vertex_indices": changed_indices, "changed_vertices": len(changed_indices),
            "max_displacement": max(lengths, default=0.0), "outside_max_displacement": outside_max,
            "baseline_nose_width_parameter": 0, "edited_nose_width_parameter": edited["parameters"]["nose_width"],
            "baseline_metrics": baseline.get("stats", {}), "edited_metrics": edited.get("stats", {}),
            "warnings": warnings,
        }
        _write_json(pending / "delta.json", delta_document)
        _write_json(pending / "verification.json", verification)
        manifest = {
            "schema_version": 1, "pair_id": pair_id, "created_at": stamp.isoformat(),
            "source_character_id": character["id"], "source_saved_revision": character["revision"],
            "baseline_role": "Derived from the same identity/expression with nose_width=0; not a separate saved revision",
            "edited_role": "Exact mesh of the requested saved character revision",
            "baseline_parameters": baseline["parameters"], "edited_parameters": edited["parameters"],
            "baseline_geometry_hash": baseline["geometry_hash"], "edited_geometry_hash": edited["geometry_hash"],
            "topology_hash": edited["topology_hash"], "vertex_count": len(deltas),
            "triangle_count": len(edited["indices"]), "image_size": [768, 768],
            "pairs": pairs, "asset": public_asset, "deformation_version": edited.get("deformation_version"),
            "changed_vertices": len(changed_indices), "outside_max_displacement": outside_max,
            "reference_contract": {"corresponding_yaw_verified": True, "same_non_edit_parameters_verified": True,
                                   "image_renderer": "Three.js browser client", "pixel_alignment_guaranteed": False,
                                   "note": "PNG format and paired yaw are validated. Pixel content, camera intrinsics, lighting and material are supplied by the local renderer, not independently inferred by this file writer."},
            "model_distribution": "Only derived reference meshes, parameters and metadata; no raw FLAME model or blendshape basis included",
            "warnings": warnings,
        }
        _write_json(pending / "manifest.json", manifest)
        with zipfile.ZipFile(pending / "paired-character-bundle.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(pending.rglob("*")):
                if path.is_file() and path.name != "paired-character-bundle.zip":
                    archive.write(path, path.relative_to(pending))
        pending.rename(final)
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    return {"id": pair_id, "output_directory": str(final.resolve()),
            "bundle_path": str((final / "paired-character-bundle.zip").resolve()),
            "bundle_relative_path": "paired-character-bundle.zip",
            "contact_sheet_relative_path": "contact-sheet.png", "pairs": pairs,
            "manifest": manifest, "warnings": warnings}
