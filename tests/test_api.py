"""Local API integration tests with real files and PNGs, without claiming 3D rendering.

The export checks use ordinary generated PNG fixtures. Actual Three.js render
correctness is checked separately in the browser; these tests cover validation,
version consistency, saved geometry, and the downloadable export bundle.
"""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

from fastapi.testclient import TestClient
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_studio.api import create_app


def png_fixture(color: str = "#a35d45", size: tuple[int, int] = (768, 768)) -> bytes:
    """Return a real PNG fixture; this is intentionally not a face render."""
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


class CharacterApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temporary.name) / "data"
        self.dist = Path(self.temporary.name) / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<!doctype html><title>Test workbench</title>", encoding="utf-8")
        self.app = create_app(data_root=self.data_root, frontend_dist=self.dist)
        self.client = TestClient(self.app)
        self.client.__enter__()
        response = self.client.get("/api/characters")
        self.assertEqual(response.status_code, 200, response.text)
        self.record = response.json()["characters"][0]
        self.character_id = self.record["id"]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temporary.cleanup()

    def load_character(self, revision: int | None = None) -> dict:
        params = {} if revision is None else {"revision": revision}
        response = self.client.get(f"/api/characters/{self.character_id}", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save_width(self, width: float, expected_revision: int | None = None) -> dict:
        body = {"name": "林 · 鼻翼测试", "nose_width": width, "source_character_id": self.character_id}
        if expected_revision is not None:
            body["expected_revision"] = expected_revision
        response = self.client.post("/api/characters", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def export_body(self, character: dict | None = None) -> dict:
        character = character or self.load_character()
        png = base64.b64encode(png_fixture()).decode("ascii")
        return {
            "character_id": self.character_id,
            "revision": character["character"]["revision"],
            "geometry_hash": character["geometry_hash"],
            "views": [
                {"name": name, "yaw_degrees": yaw, "png_base64": png}
                for name, yaw in (("front", 0), ("left45", -45), ("right45", 45),
                                  ("left90", -90), ("right90", 90))
            ],
        }

    def test_startup_seeds_one_loadable_character_with_consistent_geometry(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        result = self.load_character()
        self.assertTrue(result["is_saved"])
        self.assertEqual(result["geometry_hash"], result["character"]["geometry_hash"])
        vertices = result["mesh"]["vertices"]
        faces = result["mesh"]["faces"]
        self.assertGreater(len(vertices), 100)
        self.assertGreater(len(faces), 100)
        self.assertEqual(len(vertices), len(result["mesh"]["edit_weights"]))
        self.assertTrue(all(len(face) == 3 and all(0 <= index < len(vertices) for index in face) for face in faces))
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_preview_only_changes_masked_vertices_and_does_not_save(self):
        original = self.load_character()
        original_vertices = original["mesh"]["vertices"]
        for width in (-0.5, 0.5):
            with self.subTest(width=width):
                response = self.client.post("/api/preview", json={"character_id": self.character_id, "nose_width": width})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertFalse(result["is_saved"])
                self.assertEqual(result["preview_nose_width"], width)
                self.assertNotEqual(result["geometry_hash"], original["geometry_hash"])
                changed = 0
                for before, after, weight in zip(original_vertices, result["mesh"]["vertices"], result["mesh"]["edit_weights"]):
                    if weight == 0:
                        self.assertEqual(before, after, "vertex outside the edit region moved")
                    elif before != after:
                        changed += 1
                self.assertGreater(changed, 0)
        reloaded = self.load_character()
        self.assertEqual(reloaded["character"]["revision"], 1)
        self.assertEqual(reloaded["geometry_hash"], original["geometry_hash"])
        self.assertEqual(reloaded["mesh"]["vertices"], original_vertices)

    def test_save_reload_verify_and_restart_have_identical_vertices(self):
        original = self.load_character()
        original_file = self.data_root / "characters" / self.character_id / "revisions/000001.json"
        original_bytes = original_file.read_bytes()
        saved = self.save_width(-0.65, expected_revision=1)
        self.assertEqual(saved["character"]["revision"], 2)
        self.assertEqual(saved["character"]["nose_width"], -0.65)
        self.assertEqual(original_file.read_bytes(), original_bytes)
        self.assertEqual(self.load_character(revision=1)["mesh"]["vertices"], original["mesh"]["vertices"])
        self.assertEqual(self.load_character()["mesh"]["vertices"], saved["mesh"]["vertices"])
        verify = self.client.post(f"/api/characters/{self.character_id}/verify")
        self.assertEqual(verify.status_code, 200, verify.text)
        report = verify.json()
        for field in ("passed", "vertex_match", "hash_match", "topology_match", "asset_match", "read_from_disk"):
            self.assertTrue(report[field], field)
        self.assertEqual(report["max_vertex_error"], 0)
        self.assertEqual(report["geometry_hash"], saved["geometry_hash"])
        self.assertTrue(Path(report["report_path"]).is_file())
        fresh_app = create_app(data_root=self.data_root, frontend_dist=self.dist)
        with TestClient(fresh_app) as fresh:
            listing = fresh.get("/api/characters").json()["characters"]
            self.assertEqual(len(listing), 1, "restarting must not create another seed character")
            loaded = fresh.get(f"/api/characters/{self.character_id}").json()
            self.assertEqual(loaded["mesh"]["vertices"], saved["mesh"]["vertices"])
            self.assertEqual(loaded["geometry_hash"], saved["geometry_hash"])

    def test_stale_save_is_rejected_and_new_character_is_independent(self):
        self.save_width(0.3, expected_revision=1)
        stale = self.client.post("/api/characters", json={"name": "旧界面", "nose_width": -0.6,
                                  "source_character_id": self.character_id, "expected_revision": 1})
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.load_character()["character"]["revision"], 2)
        duplicate = self.client.post("/api/characters", json={"name": "独立角色", "nose_width": 0.1})
        self.assertEqual(duplicate.status_code, 200, duplicate.text)
        self.assertNotEqual(duplicate.json()["character"]["id"], self.character_id)
        self.assertEqual(duplicate.json()["character"]["revision"], 1)
        self.assertEqual(len(self.client.get("/api/characters").json()["characters"]), 2)

    def test_corrupt_snapshot_cannot_pass_verification_or_export(self):
        body = self.export_body()
        path = self.data_root / "characters" / self.character_id / "revisions/000001.json"
        document = json.loads(path.read_text())
        document["mesh_vertices"][0][0] += 0.1
        path.write_text(json.dumps(document), encoding="utf-8")
        for endpoint in (f"/api/characters/{self.character_id}/verify", "/api/exports"):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, json=body if endpoint == "/api/exports" else None)
                self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.client.get("/api/characters").status_code, 409)

    def test_corrupt_parameters_with_valid_snapshot_fail_rebuild_verification(self):
        body = self.export_body()
        path = self.data_root / "characters" / self.character_id / "revisions/000001.json"
        document = json.loads(path.read_text())
        document["nose_width"] = 0.4
        path.write_text(json.dumps(document), encoding="utf-8")
        response = self.client.post(f"/api/characters/{self.character_id}/verify")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["passed"])
        self.assertFalse(response.json()["hash_match"])
        self.assertFalse(response.json()["vertex_match"])
        self.assertEqual(self.client.get(f"/api/characters/{self.character_id}").status_code, 409)
        self.assertEqual(self.client.post("/api/exports", json=body).status_code, 409)

    def test_export_bundle_contains_views_mesh_metadata_and_verification(self):
        saved = self.save_width(-0.25, expected_revision=1)
        body = self.export_body(saved)
        response = self.client.post("/api/exports", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertTrue(Path(result["output_directory"]).is_dir())
        download = self.client.get(result["download_url"])
        self.assertEqual(download.status_code, 200, download.text[:200])
        self.assertIn("application/zip", download.headers["content-type"])
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            names = set(archive.namelist())
            required = {"character.json", "mesh.obj", "mesh.json", "manifest.json", "verification.json", "contact-sheet.png"}
            required.update("views/" + view["name"] + ".png" for view in body["views"])
            self.assertTrue(required.issubset(names), names)
            self.assertEqual(archive.testzip(), None)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["geometry_hash"], saved["geometry_hash"])
            self.assertEqual(manifest["revision"], 2)
            self.assertEqual(manifest["image_size"], [768, 768])
            self.assertEqual(len(manifest["views"]), 5)
            for field in ("license", "license_url", "attribution", "source_url", "source_sha256"):
                self.assertTrue(manifest["asset"].get(field), f"asset provenance lacks {field}")
            for view in manifest["views"]:
                data = archive.read(view["path"])
                self.assertEqual(view["sha256"], hashlib.sha256(data).hexdigest())
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.size, (768, 768))
                    image.verify()
            mesh = json.loads(archive.read("mesh.json"))
            self.assertEqual(mesh["vertices"], saved["mesh"]["vertices"])
            self.assertEqual(mesh["faces"], saved["mesh"]["faces"])
            obj = archive.read("mesh.obj").decode("utf-8").splitlines()
            self.assertEqual(sum(line.startswith("v ") for line in obj), len(mesh["vertices"]))
            self.assertEqual(sum(line.startswith("f ") for line in obj), len(mesh["faces"]))
            self.assertTrue(json.loads(archive.read("verification.json"))["passed"])
        for view in result["views"]:
            self.assertEqual(self.client.get(view["url"]).status_code, 200)
        sheet = self.client.get(result["contact_sheet_url"])
        self.assertEqual(sheet.status_code, 200)
        with Image.open(io.BytesIO(sheet.content)) as image:
            self.assertEqual(image.size, (1152, 840))

    def test_export_rejects_hash_or_revision_mismatch(self):
        original = self.load_character()
        edited = self.save_width(0.5, expected_revision=1)
        body = self.export_body(edited)
        body["geometry_hash"] = "0" * 64
        self.assertEqual(self.client.post("/api/exports", json=body).status_code, 409)
        body = self.export_body(edited)
        body["revision"] = original["character"]["revision"]
        self.assertEqual(self.client.post("/api/exports", json=body).status_code, 409)
        body = self.export_body(edited)
        body["revision"] = 999
        self.assertEqual(self.client.post("/api/exports", json=body).status_code, 404)

    def test_export_rejects_duplicate_angles_or_names_without_partial_files(self):
        for mutate in ("duplicate_name", "duplicate_angle", "too_few"):
            with self.subTest(mutate=mutate):
                body = self.export_body()
                if mutate == "duplicate_name":
                    body["views"][1]["name"] = body["views"][0]["name"]
                elif mutate == "duplicate_angle":
                    body["views"][1]["yaw_degrees"] = body["views"][0]["yaw_degrees"]
                else:
                    body["views"].pop()
                self.assertEqual(self.client.post("/api/exports", json=body).status_code, 422)
        export_root = self.data_root / "characters" / self.character_id / "exports"
        self.assertFalse(export_root.exists(), "invalid exports should not create output folders")

    def test_export_rejects_malformed_truncated_and_wrong_size_pngs(self):
        invalid = ["not base64", base64.b64encode(b"not PNG").decode(),
                   base64.b64encode(png_fixture()[:50]).decode(),
                   base64.b64encode(png_fixture(size=(128, 128))).decode()]
        for png in invalid:
            with self.subTest(prefix=png[:15]):
                body = self.export_body()
                body["views"][0]["png_base64"] = png
                response = self.client.post("/api/exports", json=body)
                self.assertEqual(response.status_code, 422, response.text)

    def test_invalid_parameters_and_unknown_ids_are_rejected(self):
        for value in (-1.01, 1.01, "not-a-number", None):
            with self.subTest(value=value):
                response = self.client.post("/api/preview", json={"character_id": self.character_id, "nose_width": value})
                self.assertEqual(response.status_code, 422, response.text)
        unknown = self.client.post("/api/preview", json={"character_id": "missing", "nose_width": 0})
        self.assertEqual(unknown.status_code, 404)
        unsafe = self.client.post("/api/preview", json={"character_id": "../outside", "nose_width": 0})
        self.assertEqual(unsafe.status_code, 400)
        empty = self.client.post("/api/characters", json={"name": " ", "nose_width": 0})
        self.assertIn(empty.status_code, (400, 422))
        extra = self.client.post("/api/preview", json={"character_id": self.character_id, "nose_width": 0, "unexpected": True})
        self.assertEqual(extra.status_code, 422)

    def test_boolean_numeric_parameters_are_not_silently_coerced(self):
        for endpoint, body in (
            ("/api/preview", {"character_id": self.character_id, "nose_width": True}),
            ("/api/characters", {"name": "布尔值", "nose_width": False}),
            ("/api/characters", {"name": "布尔版本", "nose_width": 0,
                                 "source_character_id": self.character_id, "expected_revision": True}),
        ):
            with self.subTest(endpoint=endpoint, body=body):
                response = self.client.post(endpoint, json=body)
                self.assertEqual(response.status_code, 422, response.text)

    def test_nonfinite_json_is_rejected_with_a_client_error(self):
        for numeric_literal in ("NaN", "Infinity", "1e999"):
            with self.subTest(value=numeric_literal):
                raw = '{"character_id":' + json.dumps(self.character_id) + ',"nose_width":' + numeric_literal + '}'
                with TestClient(self.app, raise_server_exceptions=False) as client:
                    response = client.post("/api/preview", content=raw,
                                           headers={"content-type": "application/json"})
                self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
