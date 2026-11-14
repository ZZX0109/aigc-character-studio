"""Local FLAME Open import and deterministic neutral-pose geometry.

Model weights are supplied by the user from the official download, never bundled
with the application. Only numeric arrays are persisted in the internal NPZ.
This implements identity/expression blendshapes at zero joint pose, not full LBS.
Nasal editing requires a separately reviewed, immutable anatomical calibration.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
import re
import shutil
import tempfile
from typing import Any
import zipfile

import numpy as np
try:
    from numpy._core import multiarray as _np_multiarray, numeric as _np_numeric
except ImportError:  # NumPy 1.x compatibility.
    from numpy.core import multiarray as _np_multiarray, numeric as _np_numeric

from .geometry import canonical_hash, geometry_hash

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "models/flame"
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
ASSET_ID = re.compile(r"^(?:flame2023-open|fixture-flame)-[0-9a-f]{16}(?:-cal-[0-9a-f]{12})?$")
MODEL_VARIANT = "flame2023_open"
DEFORMATION_VERSION = "flame-reviewed-vertex-ala-v1"
OFFICIAL_OPEN_DOWNLOAD = "https://download.is.tue.mpg.de/download.php?domain=flame&sfile=FLAME2023Open.zip"
OFFICIAL_SOURCE_SHA256 = "a6b4c3dc15d569d98136a1e548b6fe532eb2830ca12a4f0d4b3a5dba8ee87a91"
REVIEWED_TEMPLATE_HASH = "db4aaf1d3d326dc64c0870d7163d7a483f1c884f896729085f4e345afe219432"
REVIEWED_TOPOLOGY_HASH = "acc81fdfa47ffc281248e6d150cf5be96042021539213c70f4b1c64696a69fed"


class FlameError(ValueError):
    """Unsupported model, unsafe serialization, or incompatible calibration."""


class CalibrationRequired(FlameError):
    """The imported template has not yet had its nasal support reviewed."""


class _ArrayUnpickler(pickle.Unpickler):
    """Permit numeric numpy/scipy containers, never arbitrary pickle globals."""

    def find_class(self, module: str, name: str):
        if module in {"numpy", "numpy.core.multiarray", "numpy._core.multiarray",
                      "numpy.core.numeric", "numpy._core.numeric"}:
            allowed = {
                ("numpy", "ndarray"): np.ndarray,
                ("numpy", "dtype"): np.dtype,
                ("numpy.core.multiarray", "_reconstruct"): _np_multiarray._reconstruct,
                ("numpy._core.multiarray", "_reconstruct"): _np_multiarray._reconstruct,
                ("numpy.core.multiarray", "scalar"): _np_multiarray.scalar,
                ("numpy._core.multiarray", "scalar"): _np_multiarray.scalar,
                ("numpy.core.numeric", "_frombuffer"): _np_numeric._frombuffer,
                ("numpy._core.numeric", "_frombuffer"): _np_numeric._frombuffer,
            }
            if (module, name) in allowed:
                return allowed[(module, name)]
        if module == "_codecs" and name == "encode":
            import codecs
            return codecs.encode  # Python 2 numpy byte strings.
        if module in {"scipy.sparse._csr", "scipy.sparse.csr", "scipy.sparse._csc",
                      "scipy.sparse.csc", "scipy.sparse._coo", "scipy.sparse.coo"}:
            from scipy import sparse
            classes = {"csr_matrix": sparse.csr_matrix, "csc_matrix": sparse.csc_matrix,
                       "coo_matrix": sparse.coo_matrix}
            if name in classes:
                return classes[name]
        raise FlameError(f"模型包含不支持的序列化对象：{module}.{name}。请使用官方 FLAME 2023 Open 文件。")


def _restricted_pickle(payload: bytes) -> dict:
    try:
        value = _ArrayUnpickler(io.BytesIO(payload), encoding="latin1").load()
    except FlameError:
        raise
    except (pickle.UnpicklingError, EOFError, AttributeError, TypeError, ValueError, ImportError) as exc:
        raise FlameError(f"无法读取 FLAME 数值容器：{exc}") from exc
    if not isinstance(value, dict):
        raise FlameError("FLAME 模型必须包含参数字典")
    return {key.decode("ascii") if isinstance(key, bytes) else key: item for key, item in value.items()}


def _decode_model(payload: bytes, name: str) -> dict:
    if payload.startswith(b"\x93NUMPY"):
        # Some official .pkl downloads are a scalar numpy object array, not a
        # plain pickle. Read its header, then use the same restricted loader.
        stream = io.BytesIO(payload)
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version in {(2, 0), (3, 0)}:
            shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise FlameError("不支持的 numpy 文件版本")
        if shape != () or not dtype.hasobject:
            raise FlameError("模型 numpy 容器应为单个参数字典")
        # Object NPY payload pickles a scalar ndarray containing the dictionary.
        try:
            value = _ArrayUnpickler(stream, encoding="latin1").load()
        except (pickle.UnpicklingError, EOFError, AttributeError, TypeError, ValueError) as exc:
            if isinstance(exc, FlameError):
                raise
            raise FlameError(f"无法读取 numpy 模型容器：{exc}") from exc
        if isinstance(value, np.ndarray) and value.shape == ():
            value = value.item()
        if not isinstance(value, dict):
            raise FlameError("numpy 模型容器不是参数字典")
        return value
    if payload.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_BYTES:
                    raise FlameError("模型压缩包解压后过大")
                names = {entry.filename for entry in entries}
                if {"v_template.npy", "shapedirs.npy"}.issubset(names):
                    with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
                        # Read all arrays so an object array cannot be hidden in
                        # an ignored model field. No allow_pickle fallback.
                        return {key: arrays[key] for key in arrays.files}
                candidates = [entry for entry in entries if entry.filename.lower().endswith((".pkl", ".pickle", ".npz", ".npy"))
                              and "open" in Path(entry.filename).name.lower()
                              and not entry.filename.startswith("__MACOSX/")]
                if len(candidates) != 1:
                    raise FlameError("请从压缩包选择唯一的 FLAME 2023 Open 模型文件，再导入")
                entry = candidates[0]
                if entry.file_size > MAX_SOURCE_BYTES:
                    raise FlameError("模型文件过大")
                return _decode_model(archive.read(entry), Path(entry.filename).name)
        except FlameError:
            raise
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise FlameError(f"无法读取数值模型压缩包：{exc}") from exc
    if Path(name).suffix.lower() not in {".pkl", ".pickle", ".npy"}:
        raise FlameError("请选择官方 .pkl / .npz 模型，或包含唯一 Open 模型的 .zip 压缩包")
    return _restricted_pickle(payload)


def _finite_array(value: Any, label: str, dtype=np.float64) -> np.ndarray:
    try:
        array = np.asarray(value)
        if array.dtype.kind not in "biuf":
            raise FlameError(f"{label} 必须是纯数值数组")
        array = np.asarray(array, dtype=dtype)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FlameError(f"{label} 无法转换为数值数组") from exc
    if not np.isfinite(array).all():
        raise FlameError(f"{label} 包含非有限数值")
    return array


def _normalise(data: dict, *, test_fixture: bool = False) -> tuple[dict[str, np.ndarray], dict]:
    try:
        template = _finite_array(data["v_template"], "v_template")
        shapedirs = _finite_array(data["shapedirs"], "shapedirs")
        face_values = _finite_array(data.get("f", data.get("faces")), "f")
    except KeyError as exc:
        raise FlameError(f"模型缺少必要字段：{exc.args[0]}") from exc
    if template.ndim != 2 or template.shape[1] != 3 or len(template) < 4:
        raise FlameError("v_template 应为 N×3 顶点数组")
    if not test_fixture and len(template) != 5023:
        raise FlameError("本版仅接受标准 5,023 顶点 FLAME 2023 Open 模型；不会把其他网格当作 FLAME")
    if shapedirs.ndim != 3 or shapedirs.shape[:2] != template.shape or shapedirs.shape[2] < 400:
        raise FlameError("shapedirs 应为 N×3×K，至少包含 300 个身份及 100 个表情分量")
    if face_values.ndim != 2 or face_values.shape[1] != 3 or not len(face_values):
        raise FlameError("f 应为非空三角面数组")
    if not np.equal(face_values, np.floor(face_values)).all():
        raise FlameError("三角面索引必须是整数")
    faces = face_values.astype(np.int64)
    if faces.min() < 0 or faces.max() >= len(template):
        raise FlameError("三角面包含越界索引")
    if np.any((faces[:, 0] == faces[:, 1]) | (faces[:, 0] == faces[:, 2]) | (faces[:, 1] == faces[:, 2])):
        raise FlameError("三角面不能重复顶点")
    minimum, maximum = template.min(axis=0), template.max(axis=0)
    height = maximum[1] - minimum[1]
    if height <= 1e-10:
        raise FlameError("模型没有有效的 Y 方向高度")
    center = (minimum + maximum) / 2
    scale = 3.0 / height
    vertices = np.round((template - center) * scale, 9)
    arrays = {"v_template": vertices, "f": faces,
              "identity_dirs": np.asarray(shapedirs[:, :, :300] * scale, dtype=np.float64),
              "expression_dirs": np.asarray(shapedirs[:, :, 300:400] * scale, dtype=np.float64)}
    return arrays, {"scale": float(scale), "translation_center": center.tolist(),
                    "coordinate_system": "right_handed_y_up_face_positive_z",
                    "orientation_note": "Official FLAME coordinate convention retained; visually verify the imported model before anatomical calibration."}


def _directory(asset_id: str, root: Path | str | None) -> Path:
    if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id):
        raise FlameError("无效的 FLAME 资产编号")
    directory = Path(root or DEFAULT_ROOT).resolve() / asset_id
    if directory.is_symlink():
        raise FlameError("模型目录不能是符号链接")
    return directory


def _read_metadata(asset_id: str, root: Path | str | None) -> tuple[Path, dict]:
    directory = _directory(asset_id, root)
    try:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"FLAME 资产不存在：{asset_id}") from exc
    except (OSError, ValueError) as exc:
        raise FlameError("FLAME 模型元数据损坏") from exc
    if metadata.get("asset_id") != asset_id or metadata.get("schema_version") != 1:
        raise FlameError("FLAME 模型标识或版本不一致")
    model = directory / "model.npz"
    if model.is_symlink() or not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != metadata.get("model_sha256"):
        raise FlameError("FLAME 模型校验失败，不能重建角色")
    # Correct guide URLs for assets imported before the dedicated Open endpoint
    # was confirmed, without mutating immutable model/calibration data.
    metadata["source_url"] = OFFICIAL_OPEN_DOWNLOAD
    if metadata.get("source_sha256") == OFFICIAL_SOURCE_SHA256:
        metadata["source_verification"] = "checksum matches the official endpoint download observed on 2026-11-14"
    return directory, metadata


def get_asset_info(asset_id: str, root: Path | str | None = None) -> dict:
    return deepcopy(_read_metadata(asset_id, root)[1])


def list_assets(root: Path | str | None = None, *, include_test_fixtures: bool = False) -> list[dict]:
    directory = Path(root or DEFAULT_ROOT)
    if not directory.exists():
        return []
    result = []
    for item in sorted(directory.iterdir()):
        if item.name.startswith("."):
            continue
        if not item.is_dir() or not ASSET_ID.fullmatch(item.name):
            continue
        meta = get_asset_info(item.name, directory)
        if meta.get("is_test_fixture") and not include_test_fixtures:
            continue
        result.append(meta)
    return result


def import_model(path: Path | str, root: Path | str | None = None, *,
                 model_variant: str = MODEL_VARIANT, _test_fixture: bool = False) -> dict:
    """Convert a user-supplied official Open file to immutable numeric NPZ.

    _test_fixture exists solely for tiny unit-test inputs; such assets are clearly
    labelled and hidden from normal asset listings. It is not exposed by the CLI.
    """
    if model_variant != MODEL_VARIANT:
        raise FlameError("本版只接入 FLAME 2023 Open，不混用旧版的许可和表情参数")
    source = Path(path)
    if not source.is_file() or source.stat().st_size > MAX_SOURCE_BYTES:
        raise FlameError("模型文件不存在或超过 512 MB")
    payload = source.read_bytes()
    source_hash = hashlib.sha256(payload).hexdigest()
    asset_id = ("fixture-flame-" if _test_fixture else "flame2023-open-") + source_hash[:16]
    directory = _directory(asset_id, root)
    if directory.exists():
        return apply_reviewed_default(asset_id, root)
    arrays, transform = _normalise(_decode_model(payload, source.name), test_fixture=_test_fixture)
    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=True)
    pending = Path(tempfile.mkdtemp(prefix=".import-", dir=parent))
    try:
        np.savez_compressed(pending / "model.npz", **arrays)
        positions, faces = arrays["v_template"].tolist(), arrays["f"].tolist()
        metadata = {
            "schema_version": 1, "asset_id": asset_id,
            "name": "FLAME 测试夹具（非真实模型）" if _test_fixture else "FLAME 2023 Open",
            "asset_kind": "synthetic_test_fixture" if _test_fixture else "flame_parametric_head",
            "model_variant": MODEL_VARIANT, "is_test_fixture": _test_fixture,
            "source_filename": source.name, "source_sha256": source_hash,
            "source_url": OFFICIAL_OPEN_DOWNLOAD,
            "source_verification": "checksum matches the official endpoint download observed on 2026-11-14" if source_hash == OFFICIAL_SOURCE_SHA256 else "user-supplied; numeric structure validated, official provenance not inferred from filename",
            "model_sha256": hashlib.sha256((pending / "model.npz").read_bytes()).hexdigest(),
            "license": "synthetic test fixture only" if _test_fixture else "CC-BY-4.0 (official FLAME 2023 Open only)",
            "license_url": "https://flame.is.tue.mpg.de/modellicense.html",
            "attribution": "FLAME: Learning a model of facial shape and expression from 4D scans; Li et al., SIGGRAPH Asia 2017; Max Planck Institute for Intelligent Systems.",
            "vertex_count": len(positions), "triangle_count": len(faces),
            "identity_dimension": 300, "expression_dimension": 100,
            "topology_hash": canonical_hash({"vertex_count": len(positions), "indices": faces}),
            "base_geometry_hash": geometry_hash(positions, faces),
            "unit": "canonical_template_height_3_not_millimeters",
            "source_to_canonical": transform,
            "coordinate_system": transform["coordinate_system"],
            "calibration_status": "calibration_required", "calibration": None,
            "deformation_version": DEFORMATION_VERSION,
            "limitations": ["No texture assets are included.", "Zero joint pose only; identity and expression blendshapes are separate, but full jaw/neck/eye LBS is not implemented.", "Nasal edit requires a visually reviewed calibration on this exact topology.", "Canonical units are not millimeters."],
        }
        (pending / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        pending.rename(directory)
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    return apply_reviewed_default(asset_id, root)


@lru_cache(maxsize=3)
def _cached_arrays(model_path: str, model_hash: str, mtime_ns: int, size: int) -> dict[str, np.ndarray]:
    try:
        with np.load(model_path, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in ["v_template", "f", "identity_dirs", "expression_dirs"]}
    except (OSError, ValueError, KeyError) as exc:
        raise FlameError("内部 FLAME 数值模型损坏") from exc
    for array in arrays.values():
        array.flags.writeable = False
    return arrays


def _load_arrays(asset_id: str, root: Path | str | None) -> tuple[dict[str, np.ndarray], dict]:
    directory, meta = _read_metadata(asset_id, root)
    model = directory / "model.npz"
    stamp = model.stat()
    arrays = _cached_arrays(str(model), meta["model_sha256"], stamp.st_mtime_ns, stamp.st_size)
    return arrays, meta


def apply_reviewed_default(asset_id: str, root: Path | str | None = None) -> dict:
    """Apply only the exact real template/topology visually reviewed in this app.

    An unrelated mesh cannot opt in by filename or by merely having 5023 points.
    The returned asset is an immutable calibrated derivative; its parent remains
    unchanged. Unknown templates remain available for neutral preview only.
    """
    arrays, meta = _load_arrays(asset_id, root)
    if meta.get("calibration_status") == "ready" or meta.get("is_test_fixture"):
        return deepcopy(meta)
    if meta["base_geometry_hash"] != REVIEWED_TEMPLATE_HASH or meta["topology_hash"] != REVIEWED_TOPOLOGY_HASH:
        return deepcopy(meta)
    points = arrays["v_template"]
    midline = 0.010322468
    distance = np.abs(points[:, 0] - midline)

    def bump(value):
        return np.where(np.abs(value) < 1, (1 - value * value) ** 3, 0)

    ramp = np.clip((distance - 0.075) / 0.035, 0, 1)
    ramp = ramp ** 3 * (ramp * (ramp * 6 - 15) + 10)
    weights = (bump((distance - 0.128) / 0.075)
               * bump((points[:, 1] - 0.125) / 0.085)
               * bump((points[:, 2] - 0.94) / 0.105) * ramp)
    weights[(distance <= 0.075) | (points[:, 1] > 0.27) | (points[:, 2] >= 1.02)] = 0
    weights = np.round(weights / weights.max(), 12)
    calibration = {
        "reviewed": True,
        "review_note": "Actual official FLAME2023Open template front/side and detailed triangle projections visually inspected on 2026-11-14; support follows the nasal alae, excluding central tip, bridge and nasolabial cheeks. Manual topology-specific engineering calibration, not anatomical ground truth.",
        "base_geometry_hash": meta["base_geometry_hash"], "weights": weights.tolist(),
        "alar_landmark_indices": [2762, 1645],
        "protected_tip_indices": [3564, 2922, 3563, 2920, 3526, 3668, 2921, 3618],
        "protected_bridge_indices": [3518, 3516, 3561, 2221, 2220, 739, 3560, 2973],
        "max_lateral_displacement": 0.025, "midline_x": midline,
    }
    return calibrate_asset(asset_id, calibration, root)


def _parameters(value: list[float] | None, count: int, label: str) -> np.ndarray:
    if value is None:
        return np.zeros(count, dtype=np.float64)
    if not isinstance(value, (list, tuple)) or len(value) > count:
        raise FlameError(f"{label} 必须是最多 {count} 个有限数值")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 5 for v in value):
        raise FlameError(f"{label} 参数须为 [-5,5] 内的有限数值")
    result = np.zeros(count, dtype=np.float64)
    result[:len(value)] = value
    return result


def _mesh_arrays(arrays: dict, identity_params: list[float] | None, expression_params: list[float] | None) -> np.ndarray:
    identity = _parameters(identity_params, 300, "identity")
    expression = _parameters(expression_params, 100, "expression")
    points = arrays["v_template"].copy()
    if np.any(identity):
        points += np.einsum("vcd,d->vc", arrays["identity_dirs"], identity, optimize=False)
    if np.any(expression):
        points += np.einsum("vcd,d->vc", arrays["expression_dirs"], expression, optimize=False)
    points = np.round(points, 9)
    points[points == 0] = 0.0
    return points


def _check_orientation(base: np.ndarray, edited: np.ndarray, faces: np.ndarray) -> None:
    normals = np.cross(base[faces[:, 1]] - base[faces[:, 0]], base[faces[:, 2]] - base[faces[:, 0]])
    changed = np.cross(edited[faces[:, 1]] - edited[faces[:, 0]], edited[faces[:, 2]] - edited[faces[:, 0]])
    valid = np.einsum("ij,ij->i", normals, normals) > 1e-20
    if np.any(np.einsum("ij,ij->i", normals[valid], changed[valid]) <= 0):
        raise FlameError("此次鼻翼调整会造成局部折面，请降低幅度或重新校准编辑区域")


def calibrate_asset(asset_id: str, calibration: dict, root: Path | str | None = None) -> dict:
    """Create an immutable calibrated derivative after explicit visual review.

    calibration contains reviewed=True, review_note, base_geometry_hash,
    weights[N], alar_landmark_indices[2], protected_tip_indices,
    protected_bridge_indices, max_lateral_displacement, midline_x. The support
    must be reviewed on the real model; no scan-coordinate mask is transferred.
    """
    arrays, meta = _load_arrays(asset_id, root)
    if not isinstance(calibration, dict) or calibration.get("reviewed") is not True:
        raise FlameError("鼻翼校准必须经过实际模型的可视审核")
    if not isinstance(calibration.get("review_note"), str) or not calibration["review_note"].strip():
        raise FlameError("请记录鼻翼区域的审核依据")
    if calibration.get("base_geometry_hash") != meta["base_geometry_hash"]:
        raise FlameError("校准对应的基础网格指纹不匹配")
    n = len(arrays["v_template"])
    weights = _finite_array(calibration.get("weights"), "weights")
    if weights.shape != (n,) or weights.min() < 0 or weights.max() > 1 or not np.any(weights > 0):
        raise FlameError("校准权重必须与顶点等长、处于[0,1]且有非零支持")
    indices = {}
    for key in ["alar_landmark_indices", "protected_tip_indices", "protected_bridge_indices"]:
        values = calibration.get(key)
        if not isinstance(values, list) or not values or any(isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < n for v in values):
            raise FlameError(f"{key} 必须包含有效顶点编号")
        if len(set(values)) != len(values):
            raise FlameError(f"{key} 不能重复")
        indices[key] = values
    alar = indices["alar_landmark_indices"]
    if len(alar) != 2 or not all(weights[i] > 0 for i in alar):
        raise FlameError("鼻翼量测需要两个位于编辑区域的不同锚点")
    protected = indices["protected_tip_indices"] + indices["protected_bridge_indices"]
    if np.any(weights[protected] != 0):
        raise FlameError("鼻尖和鼻梁保护顶点不能具有编辑权重")
    for key in ["max_lateral_displacement", "midline_x"]:
        value = calibration.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise FlameError(f"{key} 必须是有限数值")
    points = arrays["v_template"]
    baseline_span = abs(points[alar[1], 0] - points[alar[0], 0])
    maximum = float(calibration["max_lateral_displacement"])
    midline = float(calibration["midline_x"])
    if baseline_span <= 1e-9 or not 0 < maximum <= baseline_span * 0.15:
        raise FlameError("局部最大位移必须大于0且不超过鼻翼基准跨度的15%")
    if not min(points[alar, 0]) < midline < max(points[alar, 0]):
        raise FlameError("编辑中线必须位于两个鼻翼锚点之间")
    normalised = {"schema_version": 1, "reviewed": True, "review_note": calibration["review_note"].strip(),
                  "base_geometry_hash": meta["base_geometry_hash"], "weights": np.round(weights, 12).tolist(),
                  **indices, "max_lateral_displacement": maximum, "midline_x": midline}
    for amount in [-1, 1]:
        edited = points.copy()
        edited[:, 0] += np.where(points[:, 0] < midline, -1, 1) * weights * maximum * amount
        _check_orientation(points, edited, arrays["f"])
    calibration_hash = canonical_hash(normalised)
    base_id = asset_id.split("-cal-")[0]
    new_id = base_id + "-cal-" + calibration_hash[:12]
    directory = _directory(new_id, root)
    if directory.exists():
        return get_asset_info(new_id, root)
    original = _directory(asset_id, root)
    pending = Path(tempfile.mkdtemp(prefix=".calibrate-", dir=directory.parent))
    try:
        shutil.copyfile(original / "model.npz", pending / "model.npz")
        updated = {**meta, "asset_id": new_id, "parent_asset_id": base_id,
                   "calibration_status": "ready", "calibration": normalised,
                   "calibration_hash": calibration_hash, "deformation_version": DEFORMATION_VERSION,
                   "editable_vertex_count": int(np.count_nonzero(weights))}
        (pending / "metadata.json").write_text(json.dumps(updated, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        pending.rename(directory)
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    return deepcopy(updated)


def build_geometry(asset_id: str, nose_width: float = 0.0,
                   identity_params: list[float] | None = None,
                   expression_params: list[float] | None = None, *,
                   root: Path | str | None = None) -> dict:
    if isinstance(nose_width, bool) or not isinstance(nose_width, (int, float)) or not math.isfinite(nose_width) or not -1 <= nose_width <= 1:
        raise FlameError("nose_width 必须是[-1,1]内的有限数值")
    arrays, meta = _load_arrays(asset_id, root)
    base = _mesh_arrays(arrays, identity_params, expression_params)
    points = base.copy()
    calibration = meta.get("calibration")
    weights = np.zeros(len(points), dtype=np.float64)
    span = baseline_span = None
    if calibration:
        weights = np.asarray(calibration["weights"], dtype=np.float64)
        if canonical_hash(calibration) != meta.get("calibration_hash"):
            raise FlameError("鼻翼校准数据校验失败")
        if nose_width:
            midline = calibration["midline_x"]
            delta = np.where(base[:, 0] < midline, -1, 1) * weights * calibration["max_lateral_displacement"] * float(nose_width)
            active = weights > 0
            points[active, 0] = np.round(base[active, 0] + delta[active], 9)
            _check_orientation(base, points, arrays["f"])
        left, right = calibration["alar_landmark_indices"]
        baseline_span = float(abs(base[right, 0] - base[left, 0]))
        span = float(abs(points[right, 0] - points[left, 0]))
    elif nose_width:
        raise CalibrationRequired("FLAME 模型已导入，但鼻翼区域尚未经过可视校准；暂不能进行非零鼻翼编辑")
    displacement = np.abs(points - base).max(axis=1)
    positions, faces = points.tolist(), arrays["f"].tolist()
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    bounds = {"min": minimum.tolist(), "max": maximum.tolist(),
              "center": ((minimum + maximum) / 2).tolist(), "size": (maximum - minimum).tolist()}
    outside = float(displacement[weights == 0].max(initial=0))
    tip_error = bridge_error = 0.0
    if calibration:
        tip_error = float(displacement[calibration["protected_tip_indices"]].max(initial=0))
        bridge_error = float(displacement[calibration["protected_bridge_indices"]].max(initial=0))
        target = points[calibration["alar_landmark_indices"]].mean(axis=0).tolist()
    else:
        target = [0.0, float(minimum[1] + (maximum[1] - minimum[1]) * 0.58), float(maximum[2] * 0.6)]
    public_meta = {key: deepcopy(value) for key, value in meta.items() if key != "calibration"}
    return {
        "asset_id": asset_id, "deformation_version": DEFORMATION_VERSION,
        "parameters": {"nose_width": float(nose_width),
                       "identity_params": _parameters(identity_params, 300, "identity").tolist(),
                       "expression_params": _parameters(expression_params, 100, "expression").tolist()},
        "positions": positions, "indices": faces, "uvs": [], "mask_weights": weights.tolist(),
        "geometry_hash": geometry_hash(positions, faces),
        "base_geometry_hash": geometry_hash(base.tolist(), faces), "topology_hash": meta["topology_hash"],
        "bounds": bounds, "face_target": target, "unit": meta["unit"], "metadata": public_meta,
        "stats": {"vertex_count": len(points), "triangle_count": len(faces),
                  "editable_vertex_count": int(np.count_nonzero(weights)),
                  "changed_vertices": int(np.count_nonzero(displacement)),
                  "max_displacement": float(displacement.max(initial=0)),
                  "outside_max_displacement": outside, "tip_max_displacement": tip_error,
                  "bridge_max_displacement": bridge_error, "nose_width_measure": span,
                  "baseline_nose_width": baseline_span,
                  "nose_width_change_ratio": span / baseline_span - 1 if span is not None and baseline_span else None,
                  "alar_landmark_indices": calibration["alar_landmark_indices"] if calibration else [],
                  "calibration_status": meta["calibration_status"],
                  "measurement_note": "Reviewed topology-specific landmark span in canonical units, not millimeters."},
    }
