"""Immutable local character revisions with atomic current-version updates.

Use one Python service process. The root-wide reentrant lock also coordinates
multiple CharacterStore instances in that process; it is not a distributed lock.
Geometry reconstruction and model-specific verification belong to the caller.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from uuid import uuid4


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION_FILE = re.compile(r"^[0-9]{6,12}\.json$")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_MAX_DOCUMENT_BYTES = 64 * 1024 * 1024
_ASSET_METADATA_KEYS = {"source_sha256", "deformation_version", "calibration_hash",
                        "model_variant", "coordinate_system"}


class StorageError(ValueError):
    """A persisted character is malformed, unsafe, or inconsistent."""


class CharacterNotFound(FileNotFoundError):
    """The requested character or revision does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _id(value: Any, label: str = "character_id") -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise StorageError(f"{label} must be a safe character identifier")
    return value


def _revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 999_999_999_999:
        raise StorageError("revision must be a positive integer")
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str):
        raise StorageError("name must be a string")
    value = value.strip()
    if not 1 <= len(value) <= 100 or any(ord(char) < 32 for char in value):
        raise StorageError("name must contain 1–100 printable characters")
    return value


def _width(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StorageError("nose_width must be a number in [-1, 1]")
    try:
        result = float(value)
    except OverflowError as error:
        raise StorageError("nose_width must be finite") from error
    if not math.isfinite(result) or not -1 <= result <= 1:
        raise StorageError("nose_width must be finite and in [-1, 1]")
    return result


def _asset_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ASSET_ID.fullmatch(value):
        raise StorageError(f"{label} must be a nonempty asset identifier")
    return value


def _hash(value: Any, label: str = "geometry_hash") -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise StorageError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _vertices(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or len(value) > 1_000_000:
        raise StorageError("mesh_vertices must be a nonempty list of vertex triples")
    result = []
    for vertex in value:
        if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
            raise StorageError("each mesh vertex must contain three finite numbers")
        coords = []
        for number in vertex:
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                raise StorageError("each mesh vertex must contain three finite numbers")
            try:
                converted = float(number)
            except OverflowError as error:
                raise StorageError("mesh vertices must be finite") from error
            if not math.isfinite(converted):
                raise StorageError("mesh vertices must be finite")
            coords.append(converted)
        result.append(coords)
    return result


def _parameters(value: Any, label: str, maximum: int) -> list[float]:
    if not isinstance(value, list) or len(value) > maximum:
        raise StorageError(f"{label} must be a list of at most {maximum} finite numbers")
    result = []
    for number in value:
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise StorageError(f"{label} must contain finite numbers, excluding booleans")
        try:
            converted = float(number)
        except OverflowError as error:
            raise StorageError(f"{label} must contain finite numbers") from error
        if not math.isfinite(converted):
            raise StorageError(f"{label} must contain finite numbers")
        result.append(converted)
    return result


def _asset_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or any(key not in _ASSET_METADATA_KEYS for key in value):
        raise StorageError("asset_metadata contains unsupported fields")
    result = {}
    for key, item in value.items():
        if not isinstance(item, str) or not 1 <= len(item) <= 256 or any(ord(char) < 32 for char in item):
            raise StorageError(f"asset_metadata.{key} must be a nonempty printable string")
        if key in {"source_sha256", "calibration_hash"}:
            _hash(item, f"asset_metadata.{key}")
        result[key] = item
    return result


def _snapshot_hash(vertices: list[list[float]] | None) -> str | None:
    if vertices is None:
        return None
    payload = json.dumps(vertices, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise StorageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise StorageError(f"non-finite JSON value: {value}")


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise StorageError(f"symbolic links are not allowed in character storage: {path.name}")
    try:
        if path.stat().st_size > _MAX_DOCUMENT_BYTES:
            raise StorageError(f"character document is too large: {path.name}")
        value = json.loads(path.read_text(encoding="utf-8"),
                           parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except FileNotFoundError as error:
        raise CharacterNotFound(str(path)) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StorageError(f"cannot read character document {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise StorageError(f"character document must be an object: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any], *, replace: bool) -> None:
    """Publish a complete file atomically; immutable revisions never replace."""
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".write-", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary_path, path)
        else:
            os.link(temporary_path, path)  # Atomic exclusive publish; existing revision is untouched.
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class CharacterStore:
    """Store versioned parameters and optional exact vertex snapshots on disk."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(self.root), threading.RLock())

    def _directory(self, character_id: str, *, existing: bool = True) -> Path:
        character_id = _id(character_id)
        directory = self.root / character_id
        if directory.is_symlink():
            raise StorageError("character directory must not be a symbolic link")
        if existing and not directory.is_dir():
            raise CharacterNotFound(f"character does not exist: {character_id}")
        if directory.exists() and not directory.is_dir():
            raise StorageError("character path is not a directory")
        return directory

    def _read_snapshot(self, character_id: str, revision: int | None) -> dict[str, Any]:
        directory = self._directory(character_id)
        manifest = _read_json(directory / "manifest.json")
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1 or manifest.get("id") != character_id:
            raise StorageError("character manifest identity or schema is invalid")
        current_revision = _revision(manifest.get("current_revision"))
        selected_revision = current_revision if revision is None else _revision(revision)
        revision_dir = directory / "revisions"
        if revision_dir.is_symlink() or not revision_dir.is_dir():
            raise StorageError("character revisions directory is missing or unsafe")
        document = _read_json(revision_dir / f"{selected_revision:06d}.json")
        self._validate_document(document, character_id, selected_revision)
        return document

    @staticmethod
    def _validate_document(document: dict[str, Any], character_id: str, revision: int) -> None:
        if type(document.get("schema_version")) is not int or document["schema_version"] != 1 or document.get("id") != character_id:
            raise StorageError("saved character identity or schema is invalid")
        if _revision(document.get("revision")) != revision:
            raise StorageError("saved character revision does not match its file")
        if _name(document.get("name")) != document.get("name"):
            raise StorageError("saved character name is not canonical")
        _width(document.get("nose_width"))
        _hash(document.get("geometry_hash"))
        _asset_id(document.get("base_asset_id"), "base_asset_id")
        _asset_id(document.get("topology_id"), "topology_id")
        # Schema-1 scan records predate these optional fields. Supply defaults
        # only in the freshly loaded dictionary; never rewrite an old revision.
        document["identity_params"] = _parameters(document.get("identity_params", []), "identity_params", 300)
        document["expression_params"] = _parameters(document.get("expression_params", []), "expression_params", 100)
        document["asset_metadata"] = _asset_metadata(document.get("asset_metadata", {}))
        for key in ("created_at", "updated_at"):
            try:
                stamp = datetime.fromisoformat(document[key])
                if stamp.tzinfo is None:
                    raise ValueError("timestamp lacks timezone")
            except (KeyError, TypeError, ValueError) as error:
                raise StorageError(f"{key} must be an ISO timestamp with timezone") from error
        vertices = _vertices(document.get("mesh_vertices"))
        if document.get("snapshot_hash") != _snapshot_hash(vertices):
            raise StorageError("saved mesh snapshot checksum does not match")
        parent = document.get("parent_revision")
        if revision == 1 and parent is not None:
            raise StorageError("first revision cannot have a parent")
        if revision > 1 and (_revision(parent) >= revision):
            raise StorageError("parent revision must precede current revision")

    @staticmethod
    def _metadata(document: dict[str, Any]) -> dict[str, Any]:
        return deepcopy({key: value for key, value in document.items() if key != "mesh_vertices"})

    def load(self, character_id: str, revision: int | None = None) -> dict[str, Any]:
        with self._lock:
            return self._metadata(self._read_snapshot(character_id, revision))

    def load_snapshot(self, character_id: str, revision: int | None = None) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._read_snapshot(character_id, revision))

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for directory in sorted(self.root.iterdir()):
                if directory.name.startswith("."):
                    continue
                if directory.is_symlink() or not directory.is_dir():
                    raise StorageError(f"unexpected entry in character storage: {directory.name}")
                result.append(self.load(directory.name))
            return sorted(result, key=lambda item: (item["updated_at"], item["id"]), reverse=True)

    def save(self, *, name: str, nose_width: float, geometry_hash: str,
             base_asset_id: str, topology_id: str, character_id: str | None = None,
             mesh_vertices: list[list[float]] | None = None,
             identity_params: list[float] | None = None,
             expression_params: list[float] | None = None,
             asset_metadata: dict[str, str] | None = None) -> dict[str, Any]:
        """Create a character or append a new immutable revision to an existing one.

        A supplied character_id must already exist. Omit it to create a new one.
        No filesystem write occurs until every supplied value has been validated.
        """
        name = _name(name)
        nose_width = _width(nose_width)
        geometry_hash = _hash(geometry_hash)
        base_asset_id = _asset_id(base_asset_id, "base_asset_id")
        topology_id = _asset_id(topology_id, "topology_id")
        vertices = _vertices(mesh_vertices)
        identity = _parameters([] if identity_params is None else identity_params, "identity_params", 300)
        expression = _parameters([] if expression_params is None else expression_params, "expression_params", 100)
        provenance = _asset_metadata({} if asset_metadata is None else asset_metadata)
        with self._lock:
            timestamp = _now()
            if character_id is None:
                character_id = "char_" + uuid4().hex
                directory = self._directory(character_id, existing=False)
                directory.mkdir(exist_ok=False)
                revision_dir = directory / "revisions"
                revision_dir.mkdir()
                revision, parent_revision, created_at = 1, None, timestamp
            else:
                previous = self._read_snapshot(character_id, None)
                directory = self._directory(character_id)
                revision_dir = directory / "revisions"
                parent_revision = previous["revision"]
                revisions = [int(file.stem) for file in revision_dir.iterdir()
                             if _REVISION_FILE.fullmatch(file.name)]
                revision = max(revisions, default=parent_revision) + 1
                _revision(revision)
                created_at = previous["created_at"]
                if previous["base_asset_id"] != base_asset_id or previous["topology_id"] != topology_id:
                    raise StorageError("base asset and topology cannot change within one character")
            document = {
                "schema_version": 1,
                "id": character_id,
                "name": name,
                "revision": revision,
                "parent_revision": parent_revision,
                "nose_width": nose_width,
                "base_asset_id": base_asset_id,
                "topology_id": topology_id,
                "identity_params": identity,
                "expression_params": expression,
                "asset_metadata": provenance,
                "geometry_hash": geometry_hash,
                "created_at": created_at,
                "updated_at": timestamp,
                "snapshot_hash": _snapshot_hash(vertices),
                "mesh_vertices": vertices,
            }
            _write_json(revision_dir / f"{revision:06d}.json", document, replace=False)
            _write_json(directory / "manifest.json", {
                "schema_version": 1, "id": character_id, "current_revision": revision,
            }, replace=True)
            return self._metadata(document)
