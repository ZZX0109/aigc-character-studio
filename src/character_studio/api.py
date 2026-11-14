"""Local character workbench: geometry, immutable revisions, and render bundles."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shutil
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from .geometry import BASE_ASSET_ID, canonical_hash
from .assets import AssetLibrary
from .pair_export import export_pair_bundle, PairExportError
from .storage import CharacterStore, StorageError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$")


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    character_id: str
    nose_width: float = Field(ge=-1, le=1)


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    name: str = Field(min_length=1, max_length=80)
    nose_width: float = Field(ge=-1, le=1)
    source_character_id: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    asset_id: str | None = None
    identity_params: list[float] | None = Field(default=None, max_length=300)
    expression_params: list[float] | None = Field(default=None, max_length=100)


class ViewImage(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    name: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    yaw_degrees: float = Field(ge=-180, le=180)
    png_base64: str = Field(max_length=8_000_000)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    character_id: str
    revision: int = Field(ge=1)
    geometry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    views: list[ViewImage] = Field(min_length=5, max_length=5)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=4096)


class PairExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    character_id: str
    revision: int = Field(ge=1)
    baseline_geometry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    edited_geometry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_views: list[ViewImage] = Field(min_length=5, max_length=5)
    edited_views: list[ViewImage] = Field(min_length=5, max_length=5)


def _safe_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise HTTPException(400, "无效的文件或角色编号")
    return value


def _json_write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _geometry_metadata(geometry: dict) -> tuple[str, str]:
    return geometry["asset_id"], geometry["topology_hash"]


def create_app(data_root: Path | None = None, frontend_dist: Path | None = None,
               models_root: Path | None = None) -> FastAPI:
    data_root = Path(data_root) if data_root else PROJECT_ROOT / "data"
    frontend_dist = Path(frontend_dist) if frontend_dist else PROJECT_ROOT / "frontend/dist"
    store = CharacterStore(data_root / "characters")
    library = AssetLibrary(models_root or PROJECT_ROOT / "models/flame")
    save_lock = threading.RLock()

    def build_record(record: dict, nose_width: float | None = None) -> dict:
        return library.build(record["base_asset_id"], record["nose_width"] if nose_width is None else nose_width,
                             record.get("identity_params"), record.get("expression_params"))

    def save_geometry(name: str, nose_width: float, character_id: str | None = None,
                      asset_id: str = BASE_ASSET_ID, identity_params: list[float] | None = None,
                      expression_params: list[float] | None = None) -> dict:
        geometry = library.build(asset_id, nose_width, identity_params, expression_params)
        asset_id, topology_id = _geometry_metadata(geometry)
        asset_meta = {key: geometry["metadata"][key] for key in
                      ["source_sha256", "deformation_version", "calibration_hash", "model_variant", "coordinate_system"]
                      if key in geometry["metadata"]}
        record = store.save(
            name=name, nose_width=nose_width, geometry_hash=geometry["geometry_hash"],
            base_asset_id=asset_id, topology_id=topology_id,
            character_id=character_id, mesh_vertices=geometry["positions"],
            identity_params=geometry["parameters"].get("identity_params", []),
            expression_params=geometry["parameters"].get("expression_params", []),
            asset_metadata=asset_meta,
        )
        return full_response(record, geometry)

    def full_response(record: dict, geometry: dict | None = None) -> dict:
        geometry = geometry or build_record(record)
        return {
            "character": record,
            "geometry_hash": geometry["geometry_hash"],
            "bounds": geometry["bounds"],
            "mesh": {
                "vertices": geometry["positions"], "faces": geometry["indices"],
                "edit_weights": geometry["mask_weights"], "bounds": geometry["bounds"],
                "face_target": geometry["face_target"],
            },
            "metrics": geometry["stats"],
            "is_saved": geometry["geometry_hash"] == record["geometry_hash"],
            "asset": geometry["metadata"],
        }

    def read_record(character_id: str, revision: int | None = None, snapshot: bool = False) -> dict:
        _safe_id(character_id)
        try:
            return store.load_snapshot(character_id, revision) if snapshot else store.load(character_id, revision)
        except FileNotFoundError as exc:
            raise HTTPException(404, "角色或版本不存在") from exc
        except StorageError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def verification(character_id: str, revision: int | None = None) -> dict:
        saved = read_record(character_id, revision, snapshot=True)
        rebuilt = build_record(saved)
        stored_vertices = saved.get("mesh_vertices")
        vertices = rebuilt["positions"]
        vertex_match = stored_vertices == vertices
        max_error = None
        if isinstance(stored_vertices, list) and len(stored_vertices) == len(vertices):
            max_error = max((abs(a - b) for old, new in zip(stored_vertices, vertices) for a, b in zip(old, new)), default=0.0)
        asset_id, topology_id = _geometry_metadata(rebuilt)
        hash_match = saved["geometry_hash"] == rebuilt["geometry_hash"]
        topology_match = saved["topology_id"] == topology_id
        asset_match = saved["base_asset_id"] == asset_id
        asset_metadata_match = all(rebuilt["metadata"].get(key) == value
                                   for key, value in saved.get("asset_metadata", {}).items())
        return {
            "passed": bool(vertex_match and hash_match and topology_match and asset_match and asset_metadata_match),
            "vertex_match": vertex_match, "hash_match": hash_match,
            "topology_match": topology_match, "asset_match": asset_match,
            "asset_metadata_match": asset_metadata_match,
            "character_id": saved["id"], "revision": saved["revision"],
            "nose_width": saved["nose_width"], "vertex_count": len(vertices),
            "max_vertex_error": max_error, "geometry_hash": rebuilt["geometry_hash"],
            "saved_geometry_hash": saved["geometry_hash"],
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "read_from_disk": True,
        }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not store.list():
            save_geometry("初始角色", 0.0)
        yield

    app = FastAPI(title="AIGC Character Studio", version="0.3.0", lifespan=lifespan)
    app.state.store = store
    app.state.library = library

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, exc: RequestValidationError):
        # NaN/Infinity cannot be echoed through a strict JSON response.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8765", "http://127.0.0.1:8765"],
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "stage": "local-character-editor", "asset": BASE_ASSET_ID, "version": "0.3.0"}

    @app.get("/api/assets")
    def assets():
        try:
            return {"assets": library.list(), "flame_status": library.status()}
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/flame/discover")
    def discover_models():
        return {"candidates": library.discover(), "inbox_directory": str(library.inbox)}

    @app.post("/api/flame/import")
    def import_model(body: ImportRequest):
        try:
            return {"asset": library.import_path(body.path)}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/characters")
    def characters():
        try:
            return {"characters": store.list()}
        except StorageError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/characters/{character_id}")
    def character(character_id: str, revision: int | None = None):
        record = read_record(character_id, revision)
        try:
            geometry = build_record(record)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        if geometry["geometry_hash"] != record["geometry_hash"]:
            raise HTTPException(409, "角色几何与保存版本不一致，请先检查资产版本")
        return full_response(record, geometry)

    @app.post("/api/preview")
    def preview(body: PreviewRequest):
        record = read_record(body.character_id)
        try:
            result = full_response(record, build_record(record, body.nose_width))
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        result["preview_nose_width"] = body.nose_width
        return result

    @app.post("/api/characters")
    def save(body: SaveRequest):
        with save_lock:
            previous = None
            if body.source_character_id:
                previous = read_record(body.source_character_id)
                if body.expected_revision is not None and body.expected_revision != previous["revision"]:
                    raise HTTPException(409, "角色已有更新版本，请重新加载后再保存")
            try:
                if previous and body.asset_id and body.asset_id != previous["base_asset_id"]:
                    raise ValueError("同一角色版本不能更换基础模型；请选择新建角色")
                return save_geometry(body.name, body.nose_width, body.source_character_id,
                                     previous["base_asset_id"] if previous else body.asset_id or BASE_ASSET_ID,
                                     body.identity_params if body.identity_params is not None else (previous or {}).get("identity_params", []),
                                     body.expression_params if body.expression_params is not None else (previous or {}).get("expression_params", []))
            except (ValueError, OSError) as exc:
                raise HTTPException(400, str(exc)) from exc

    @app.post("/api/characters/{character_id}/verify")
    def verify(character_id: str, revision: int | None = None):
        try:
            result = verification(character_id, revision)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        report = data_root / "characters" / _safe_id(character_id) / f"verification_{result['revision']:06d}.json"
        _json_write(report, result)
        result["report_path"] = str(report)
        return result

    @app.post("/api/exports")
    def export(body: ExportRequest):
        record = read_record(body.character_id, body.revision)
        if body.geometry_hash != record["geometry_hash"]:
            raise HTTPException(409, "导出画面与保存的角色版本不一致，请重新保存并导出")
        check = verification(body.character_id, body.revision)
        if not check["passed"]:
            raise HTTPException(409, "重新加载验证未通过，不能导出此版本")
        if len({v.name for v in body.views}) != 5 or sorted(v.yaw_degrees for v in body.views) != [-90, -45, 0, 45, 90]:
            raise HTTPException(422, "需要正面、左右45°、左右90°五个不同视角")
        decoded: list[tuple[ViewImage, bytes]] = []
        for view in body.views:
            try:
                raw = base64.b64decode(view.png_base64.split(",", 1)[-1], validate=True)
                if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("not PNG")
                with Image.open(io.BytesIO(raw)) as image:
                    if image.size != (768, 768):
                        raise ValueError("incorrect size")
                    image.verify()
                decoded.append((view, raw))
            except (ValueError, OSError, base64.binascii.Error) as exc:
                raise HTTPException(422, "每个视角必须是完整的768×768 PNG图片") from exc
        geometry = build_record(record)
        export_id = "export_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]
        parent = data_root / "characters" / record["id"] / "exports"
        parent.mkdir(parents=True, exist_ok=True)
        final = parent / export_id
        pending = parent / ("." + export_id + ".pending")
        pending.mkdir()
        try:
            (pending / "views").mkdir()
            rendered = []
            sheet = Image.new("RGB", (3 * 384, 2 * 420), "#eeeae3")
            draw = ImageDraw.Draw(sheet)
            for index, (view, raw) in enumerate(decoded):
                target = pending / "views" / f"{view.name}.png"
                target.write_bytes(raw)
                with Image.open(io.BytesIO(raw)) as image:
                    thumbnail = image.convert("RGB").resize((384, 384), Image.Resampling.LANCZOS)
                    x, y = (index % 3) * 384, (index // 3) * 420
                    sheet.paste(thumbnail, (x, y))
                    draw.text((x + 16, y + 392), f"{view.name}  /  {view.yaw_degrees:g} deg", fill="#24231f")
                rendered.append({"name": view.name, "yaw_degrees": view.yaw_degrees, "path": f"views/{view.name}.png", "sha256": hashlib.sha256(raw).hexdigest()})
            sheet.save(pending / "contact-sheet.png")
            _json_write(pending / "character.json", record)
            _json_write(pending / "mesh.json", {"vertices": geometry["positions"], "faces": geometry["indices"], "geometry_hash": geometry["geometry_hash"], "topology_hash": geometry["topology_hash"]})
            with (pending / "mesh.obj").open("w", encoding="utf-8") as stream:
                stream.write("# AIGC Character Studio; +Y up, +Z front; source metadata in manifest.json\n")
                for vertex in geometry["positions"]:
                    stream.write("v " + " ".join(format(v, ".17g") for v in vertex) + "\n")
                for face in geometry["indices"]:
                    stream.write("f " + " ".join(str(i + 1) for i in face) + "\n")
            _json_write(pending / "verification.json", check)
            _json_write(pending / "manifest.json", {
                "export_id": export_id, "character_id": record["id"], "revision": body.revision,
                "geometry_hash": body.geometry_hash, "nose_width": record["nose_width"],
                "image_size": [768, 768], "views": rendered,
                "asset": geometry["metadata"], "metrics": geometry["stats"],
                "render_method": "Three.js browser renderer, orthographic views",
                "note": "Geometry verification checks the saved mesh and parameters. Images are rendered by the local browser client.",
            })
            with zipfile.ZipFile(pending / "character-bundle.zip", "w", zipfile.ZIP_DEFLATED) as archive:
                for file in sorted(pending.rglob("*")):
                    if file.is_file() and file.name != "character-bundle.zip":
                        archive.write(file, file.relative_to(pending))
            pending.rename(final)
        except Exception:
            shutil.rmtree(pending, ignore_errors=True)
            raise
        prefix = f"/api/exports/{record['id']}/{export_id}"
        return {"id": export_id, "character_id": record["id"], "revision": record["revision"], "geometry_hash": body.geometry_hash,
                "download_url": prefix + "/download", "output_directory": str(final),
                "contact_sheet_url": prefix + "/contact-sheet.png",
                "views": [{**v, "url": prefix + "/" + v["path"]} for v in rendered]}

    def export_path(character_id: str, export_id: str) -> Path:
        path = data_root / "characters" / _safe_id(character_id) / "exports" / _safe_id(export_id)
        if not path.is_dir():
            raise HTTPException(404, "导出文件不存在")
        return path

    @app.get("/api/exports/{character_id}/{export_id}/download")
    def download(character_id: str, export_id: str):
        path = export_path(character_id, export_id) / "character-bundle.zip"
        return FileResponse(path, media_type="application/zip", filename=f"{character_id}-{export_id}.zip")

    @app.get("/api/exports/{character_id}/{export_id}/contact-sheet.png")
    def contact_sheet(character_id: str, export_id: str):
        return FileResponse(export_path(character_id, export_id) / "contact-sheet.png", media_type="image/png")

    def pair_geometries(character_id: str, revision: int | None = None):
        record = read_record(character_id, revision)
        try:
            edited = build_record(record)
            baseline = build_record(record, 0.0)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        if edited["geometry_hash"] != record["geometry_hash"]:
            raise HTTPException(409, "保存的角色参数与当前模型不一致，不能构造成对参考")
        return record, baseline, edited

    @app.get("/api/characters/{character_id}/pair")
    def reference_pair(character_id: str, revision: int | None = None):
        record, baseline, edited = pair_geometries(character_id, revision)
        baseline_document = full_response(record, baseline)
        baseline_document["character"] = {**record, "nose_width": 0.0, "geometry_hash": baseline["geometry_hash"]}
        baseline_document.update(is_saved=False, reference_role="derived_unedited_reference")
        identity = {"character_id": record["id"], "revision": record["revision"],
                    "baseline_hash": baseline["geometry_hash"], "edited_hash": edited["geometry_hash"]}
        return {
            "character": record, "pair_id": "pair_spec_" + canonical_hash(identity)[:24],
            "baseline": baseline_document, "edited": full_response(record, edited),
            "same_identity_expression": True,
            "render_contract": {"framing": "shared_baseline_bounds", "size": [768, 768],
                                "yaws": [0, -45, 45, -90, 90], "lighting": "studio-neutral-v1"},
            "zero_edit": record["nose_width"] == 0,
        }

    @app.post("/api/pair-exports")
    def paired_export(body: PairExportRequest):
        record, baseline, edited = pair_geometries(body.character_id, body.revision)
        if (body.baseline_geometry_hash != baseline["geometry_hash"] or
                body.edited_geometry_hash != edited["geometry_hash"]):
            raise HTTPException(409, "成对参考的形状指纹不匹配，请重新保存并导出")
        try:
            result = export_pair_bundle(
                character=record, baseline_geometry=baseline, edited_geometry=edited,
                baseline_views=body.baseline_views, edited_views=body.edited_views,
                asset=edited["metadata"], verification=verification(record["id"], record["revision"]),
                output_root=data_root / "characters" / record["id"] / "pair-exports",
            )
        except (PairExportError, ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        prefix = f"/api/pair-exports/{record['id']}/{result['id']}"
        return {
            "id": result["id"], "output_directory": result["output_directory"],
            "download_url": prefix + "/download", "contact_sheet_url": prefix + "/contact-sheet.png",
            "baseline_geometry_hash": baseline["geometry_hash"], "edited_geometry_hash": edited["geometry_hash"],
            "pairs": result["pairs"], "warnings": result["warnings"],
        }

    def pair_export_path(character_id: str, pair_id: str) -> Path:
        path = data_root / "characters" / _safe_id(character_id) / "pair-exports" / _safe_id(pair_id)
        if not path.is_dir():
            raise HTTPException(404, "成对参考导出不存在")
        return path

    @app.get("/api/pair-exports/{character_id}/{pair_id}/download")
    def download_pair(character_id: str, pair_id: str):
        path = pair_export_path(character_id, pair_id) / "paired-character-bundle.zip"
        return FileResponse(path, media_type="application/zip", filename=f"{character_id}-{pair_id}.zip")

    @app.get("/api/pair-exports/{character_id}/{pair_id}/contact-sheet.png")
    def pair_contact_sheet(character_id: str, pair_id: str):
        return FileResponse(pair_export_path(character_id, pair_id) / "contact-sheet.png", media_type="image/png")

    @app.get("/api/exports/{character_id}/{export_id}/views/{filename}")
    def view_image(character_id: str, export_id: str, filename: str):
        if not re.fullmatch(r"[a-z0-9_-]{1,40}\.png", filename):
            raise HTTPException(400, "无效图片名")
        path = export_path(character_id, export_id) / "views" / filename
        if not path.is_file():
            raise HTTPException(404, "图片不存在")
        return FileResponse(path, media_type="image/png")

    @app.get("/")
    def index():
        if not (frontend_dist / "index.html").is_file():
            raise HTTPException(503, "请先在frontend目录运行npm run build")
        return FileResponse(frontend_dist / "index.html")

    @app.get("/assets/{asset_path:path}")
    def frontend_asset(asset_path: str):
        root = (frontend_dist / "assets").resolve()
        target = (root / asset_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "资源不存在")
        return FileResponse(target)

    return app


app = create_app()
