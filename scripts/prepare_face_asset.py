#!/usr/bin/env python3
"""Convert the attributed, checksum-pinned head scan to a reproducible mesh.

No pickle loading, model downloads, numpy, or third-party Python packages are
needed. The checked-in GLB is used by default; --download explicitly refreshes
the same pinned source, then verifies its checksum before reading it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIRECTORY = ROOT / "data/base-face"
SOURCE_DIRECTORY = ASSET_DIRECTORY / "source"
SOURCE_URL = "https://raw.githubusercontent.com/mrdoob/three.js/r180/examples/models/gltf/LeePerrySmith/LeePerrySmith.glb"
SOURCE_SHA256 = "402b8a8ac9f03232e6d64b5962929703a069daf99d3c49ac8eb0e48bedc9c576"
LICENSE_URL = "https://raw.githubusercontent.com/mrdoob/three.js/r180/examples/models/gltf/LeePerrySmith/LeePerrySmith_License.txt"
LICENSE_SHA256 = "7cf4da43a6ae6d32f7f7d063fe129a19468af6f4fe7c53b937f83959709fcb50"


def checked_bytes(path: Path, expected_sha256: str) -> bytes:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError(f"Source checksum mismatch: {path.name}")
    return payload


def download(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory) / destination.name
        subprocess.run(["curl", "--silent", "--show-error", "--location", "--fail",
                        "--max-time", "60", "--max-filesize", "209715200",
                        url, "--output", str(temporary)], check=True)
        payload = checked_bytes(temporary, expected_sha256)
        destination.write_bytes(payload)


def decode_glb(payload: bytes) -> tuple[dict, bytes]:
    magic, version, total = struct.unpack_from("<III", payload)
    if magic != 0x46546C67 or version != 2 or total != len(payload):
        raise ValueError("Expected a complete glTF 2.0 binary")
    chunks = {}
    offset = 12
    while offset < total:
        length, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        chunks[kind] = payload[offset:offset + length]
        offset += length
    return json.loads(chunks[0x4E4F534A]), chunks[0x004E4942]


def accessor(document: dict, binary: bytes, index: int) -> list:
    spec = document["accessors"][index]
    view = document["bufferViews"][spec["bufferView"]]
    if "sparse" in spec or spec.get("normalized"):
        raise ValueError("Sparse/normalized accessor is not supported by this pinned converter")
    types = {5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
    kind, size = types[spec["componentType"]]
    columns = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}[spec["type"]]
    stride = view.get("byteStride", size * columns)
    start = view.get("byteOffset", 0) + spec.get("byteOffset", 0)
    records = [list(struct.unpack_from("<" + kind * columns, binary, start + stride * row))
               for row in range(spec["count"])]
    return [row[0] for row in records] if columns == 1 else records


def convert(payload: bytes) -> dict:
    document, binary = decode_glb(payload)
    primitive = document["meshes"][0]["primitives"][0]
    if primitive.get("mode", 4) != 4:
        raise ValueError("Expected triangle mesh")
    source_positions = accessor(document, binary, primitive["attributes"]["POSITION"])
    mesh_node = next(node for node in document["nodes"] if node.get("mesh") == 0)
    if "rotation" in mesh_node or "matrix" in mesh_node:
        raise ValueError("Source transform changed; review before conversion")
    scales = mesh_node.get("scale", [1, 1, 1])
    translations = mesh_node.get("translation", [0, 0, 0])
    source_positions = [[row[i] * scales[i] + translations[i] for i in range(3)]
                        for row in source_positions]
    minimum = [min(v[i] for v in source_positions) for i in range(3)]
    maximum = [max(v[i] for v in source_positions) for i in range(3)]
    center = [(minimum[i] + maximum[i]) / 2 for i in range(3)]
    scale = 3 / (maximum[1] - minimum[1])
    positions = [[round((v[i] - center[i]) * scale, 9) for i in range(3)]
                 for v in source_positions]
    raw_indices = accessor(document, binary, primitive["indices"])
    triangles = [raw_indices[i:i + 3] for i in range(0, len(raw_indices), 3)]
    uvs = accessor(document, binary, primitive["attributes"]["TEXCOORD_0"])
    asset = {
        "schema_version": 1,
        "asset_id": "lee-perry-smith-r180-v1",
        "name": "Lee Perry-Smith 头部扫描",
        "asset_kind": "static_head_scan",
        "license": "CC-BY-3.0",
        "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "attribution": "Infinite, 3D Head Scan by Lee Perry-Smith / Infinite-Realities; distributed with three.js r180.",
        "source_url": SOURCE_URL,
        "source_sha256": SOURCE_SHA256,
        "license_source_url": LICENSE_URL,
        "license_source_sha256": LICENSE_SHA256,
        "coordinate_system": "right_handed_y_up_face_positive_z",
        "unit": "canonical_head_bust_height_3_not_millimeters",
        "source_to_canonical": {"scale": scale, "translation_center": center},
        "positions": positions,
        "indices": triangles,
        "uvs": [[round(x, 9) for x in row] for row in uvs],
        "face_target": [0.0, round(1.3 * scale, 9), round(0.4 * scale, 9)],
        "edit_region": {
            "name": "nose_alar",
            "description": "Symmetric compact-support lateral displacement of the nasal alae; central tip/bridge are protected.",
            "midline_x": round(-0.08 * scale, 9),
            "center_abs_x": round(0.34 * scale, 9),
            "radius_x": round(0.24 * scale, 9),
            "center_y": round((0.98 - center[1]) * scale, 9),
            "radius_y": round(0.18 * scale, 9),
            "center_z": round((2.25 - center[2]) * scale, 9),
            "radius_z": round(0.30 * scale, 9),
            "protected_center_half_width": round(0.22 * scale, 9),
            "protected_transition_width": round(0.07 * scale, 9),
            "protected_tip_min_z": round((2.40 - center[2]) * scale, 9),
            "tip_transition_width": round(0.10 * scale, 9),
            "protected_bridge_min_y": round((1.18 - center[1]) * scale, 9),
            "max_lateral_displacement": round(0.06 * scale, 9),
            "measurement_targets": [[round((x - center[0]) * scale, 9),
                                     round((0.98 - center[1]) * scale, 9),
                                     round((2.25 - center[2]) * scale, 9)]
                                    for x in [-0.42, 0.26]],
        },
        "limitations": ["Static scan; no FLAME or expression rig is included.",
                        "Canonical units are not clinical measurements or millimeters.",
                        "Semantic alar support is a reviewed coordinate-based region for this asset only."],
    }
    return asset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    SOURCE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source = SOURCE_DIRECTORY / "LeePerrySmith.glb"
    license_file = SOURCE_DIRECTORY / "LeePerrySmith_License.txt"
    if args.download:
        download(SOURCE_URL, source, SOURCE_SHA256)
        download(LICENSE_URL, license_file, LICENSE_SHA256)
    payload = checked_bytes(source, SOURCE_SHA256)
    checked_bytes(license_file, LICENSE_SHA256)
    asset = convert(payload)
    output = ASSET_DIRECTORY / "base-face.json"
    output.write_text(json.dumps(asset, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "vertices": len(asset["positions"]),
                      "triangles": len(asset["indices"]), "source_sha256": SOURCE_SHA256}, indent=2))


if __name__ == "__main__":
    main()
