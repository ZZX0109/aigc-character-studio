#!/usr/bin/env python3
"""Create a deterministic planning manifest; never execute generation jobs."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PAIRING_NOTE = (
    "Paired jobs share the requested driver specification and seed; text-only "
    "baselines do not consume driving video. The seed does not guarantee pixel alignment."
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON number is forbidden: {value}")


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, parse_constant=_reject_constant)


def _finite_numbers(value: Any, location: str = "config") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{location}: non-finite numbers are forbidden")
    if isinstance(value, dict):
        for key, item in value.items():
            _finite_numbers(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _finite_numbers(item, f"{location}[{index}]")


def _valid_id(value: Any, location: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f"{location}: expected a nonempty simple string ID")
    return value


def _records(config: dict[str, Any], key: str) -> list[dict[str, Any]]:
    records = config.get(key)
    if not isinstance(records, list) or not records:
        raise ValueError(f"{key}: expected a nonempty list")
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"{key}[{index}]: expected an object")
        record_id = _valid_id(record.get("id"), f"{key}[{index}].id")
        if record_id in seen:
            raise ValueError(f"{key}: duplicate ID {record_id!r}")
        seen.add(record_id)
    return sorted(records, key=lambda record: record["id"])


def validate_config(config: Any) -> None:
    if not isinstance(config, dict):
        raise ValueError("config: expected an object")
    _finite_numbers(config)
    _valid_id(config.get("experiment_id"), "experiment_id")
    if config.get("schema_version") != "1.0":
        raise ValueError("schema_version must be '1.0'")
    if config.get("experiment_status") != "planned":
        raise ValueError("This scaffold only accepts experiment_status='planned'")

    characters = _records(config, "characters")
    states = _records(config, "states")
    shots = _records(config, "shots")
    methods = _records(config, "methods")

    for character in characters:
        if character.get("asset_status") not in {"pending", "available"}:
            raise ValueError(f"{character['id']}: invalid asset_status")
        asset_path = character.get("asset_path")
        if asset_path is not None and (not isinstance(asset_path, str) or not asset_path):
            raise ValueError(f"{character['id']}: asset_path must be null or a nonempty string")
        if character["asset_status"] == "available" and not asset_path:
            raise ValueError(f"{character['id']}: available assets require asset_path")

    original_states = [state for state in states if state["id"] == "original"]
    if len(original_states) != 1:
        raise ValueError("states must contain exactly one original state")
    for state in states:
        delta = state.get("edit_delta")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise ValueError(f"{state['id']}: edit_delta must be a finite number")
        if not isinstance(state.get("edit_unit"), str) or not state["edit_unit"]:
            raise ValueError(f"{state['id']}: edit_unit must be a nonempty string")
        if state["id"] == "original":
            if state.get("edit_parameter") is not None or delta != 0:
                raise ValueError("original must have null edit_parameter and zero edit_delta")
        else:
            _valid_id(state.get("edit_parameter"), f"{state['id']}.edit_parameter")
            if delta == 0:
                raise ValueError("Zero edits must reuse original, not add duplicate control states")

    for shot in shots:
        _valid_id(shot.get("driver_id"), f"{shot['id']}.driver_id")
        if shot.get("driver_status") not in {"pending", "available"}:
            raise ValueError(f"{shot['id']}: invalid driver_status")
        yaw = shot.get("start_yaw_degrees")
        if isinstance(yaw, bool) or not isinstance(yaw, (int, float)) or not -180 <= yaw <= 180:
            raise ValueError(f"{shot['id']}: start_yaw_degrees must be a finite number in [-180, 180]")
    for method in methods:
        if method.get("implementation_status") not in {"planned", "implemented"}:
            raise ValueError(f"{method['id']}: invalid implementation_status")
        if method.get("motion_input_mode") not in {"text_only", "planned_geometry_driver"}:
            raise ValueError(f"{method['id']}: invalid motion_input_mode")

    seeds = config.get("seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("seeds: expected a nonempty list")
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
            raise ValueError("seeds must be integers in [0, 2**63), excluding booleans")
    if len(seeds) != len(set(seeds)):
        raise ValueError("seeds: duplicate seeds are forbidden")


def _job_id(config: dict[str, Any], character: dict[str, Any], state: dict[str, Any],
            shot: dict[str, Any], seed: int, method: dict[str, Any]) -> str:
    # Include scientific inputs, not list positions or mutable run status.
    identity = {
        "schema_version": config["schema_version"],
        "experiment_id": config["experiment_id"],
        "character_id": character["id"],
        "asset_path": character.get("asset_path"),
        "state": {
            "id": state["id"],
            "edit_parameter": state["edit_parameter"],
            "edit_delta": state["edit_delta"],
            "edit_unit": state["edit_unit"],
        },
        "shot_id": shot["id"],
        "start_yaw_degrees": shot["start_yaw_degrees"],
        "driver_id": shot["driver_id"],
        "seed": seed,
        "method_id": method["id"],
        "motion_input_mode": method["motion_input_mode"],
    }
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "job_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_jobs(config: dict[str, Any]) -> list[dict[str, Any]]:
    validate_config(config)
    characters = _records(config, "characters")
    states = _records(config, "states")
    shots = _records(config, "shots")
    methods = _records(config, "methods")
    original = next(state for state in states if state["id"] == "original")
    jobs: list[dict[str, Any]] = []
    job_ids: set[str] = set()
    for character, state, shot, seed, method in itertools.product(
        characters, states, shots, sorted(config["seeds"]), methods
    ):
        job_id = _job_id(config, character, state, shot, seed, method)
        if job_id in job_ids:
            raise ValueError(f"Duplicate generated job ID: {job_id}")
        job_ids.add(job_id)
        jobs.append({
            "schema_version": config["schema_version"],
            "experiment_id": config["experiment_id"],
            "job_id": job_id,
            "execution_status": "planned",
            "implementation_status": method["implementation_status"],
            "character_id": character["id"],
            "asset_status": character["asset_status"],
            "asset_path": character.get("asset_path"),
            "state_id": state["id"],
            "edit": deepcopy({key: value for key, value in state.items() if key != "id"}),
            "shot_id": shot["id"],
            "start_yaw_degrees": shot["start_yaw_degrees"],
            "driver_id": shot["driver_id"],
            "driver_status": shot["driver_status"],
            "seed": seed,
            "method_id": method["id"],
            "motion_input_mode": method["motion_input_mode"],
            "baseline_job_id": None if state["id"] == "original" else _job_id(
                config, character, original, shot, seed, method
            ),
            "pairing_note": PAIRING_NOTE,
            "output_video": None,
        })
    return jobs


def write_manifest(jobs: list[dict[str, Any]], output: Path, overwrite: bool = False) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8") as stream:
        for job in jobs:
            stream.write(json.dumps(job, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def summarize(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "total_jobs": len(jobs),
        "original_jobs": sum(job["state_id"] == "original" for job in jobs),
        "edited_jobs": sum(job["state_id"] != "original" for job in jobs),
        "jobs_by_method": dict(sorted(Counter(job["method_id"] for job in jobs).items())),
        "jobs_by_status": dict(sorted(Counter(job["execution_status"] for job in jobs).items())),
        "note": "Planning only: no model was called and no 3D/video output was generated.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "configs/pilot.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/manifests/pilot.jsonl")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace an existing manifest")
    parser.add_argument("--dry-run", action="store_true", help="Inspect the plan without writing or replacing a manifest")
    parser.add_argument("--summary", action="store_true", help="Print job counts and method names")
    args = parser.parse_args(argv)
    try:
        jobs = build_jobs(load_config(args.config))
        if not args.dry_run:
            write_manifest(jobs, args.output, overwrite=args.overwrite)
    except FileExistsError:
        print(f"Refusing to overwrite {args.output}; use --overwrite explicitly.", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"Manifest error: {error}", file=sys.stderr)
        return 2
    if args.summary or args.dry_run:
        print(json.dumps(summarize(jobs), ensure_ascii=False, indent=2))
    else:
        print(f"Wrote {len(jobs)} planned jobs to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
