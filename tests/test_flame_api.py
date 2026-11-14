"""Integration checks against an already imported real FLAME Open model.

The model library is shared read-only; every test uses temporary character data.
Tests skip clearly when the local official model is absent. Plain PNG fixtures
exercise export validation only and do not claim to test face rendering.
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


class RealFlameApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models_root = ROOT / "models/flame"
        cls.asset_id = "flame2023-open-a6b4c3dc15d569d9-cal-a3717f2607be"
        metadata_path = cls.models_root / cls.asset_id / "metadata.json"
        if not metadata_path.is_file() or not (metadata_path.parent / "model.npz").is_file():
            raise unittest.SkipTest("Real FLAME 2023 Open model is not imported locally; no synthetic substitute is used")
        cls.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if cls.metadata.get("is_test_fixture") or cls.metadata.get("calibration_status") != "ready":
            raise unittest.SkipTest("A real, reviewed FLAME model is required for this integration suite")
        cls.source_zip = cls.models_root / "inbox/FLAME2023Open.zip"
        cls.png_before = cls.png_fixture("#bda78f")
        cls.png_after = cls.png_fixture("#a78369")

    @staticmethod
    def png_fixture(color):
        buffer = io.BytesIO()
        Image.new("RGB", (768, 768), color).save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp.name) / "data"
        self.dist = Path(self.temp.name) / "dist"
        self.dist.mkdir()
        (self.dist / "index.html").write_text("<title>FLAME API test</title>", encoding="utf-8")
        self.app = create_app(data_root=self.data_root, frontend_dist=self.dist, models_root=self.models_root)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.scan = self.client.get("/api/characters").json()["characters"][0]

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def new_flame(self, width=0.0):
        response = self.client.post("/api/characters", json={
            "name": "真实 FLAME 集成验证", "nose_width": width, "asset_id": self.asset_id,
            "identity_params": [0.2], "expression_params": [0.1],
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pair(self, document):
        response = self.client.get(f"/api/characters/{document['character']['id']}/pair",
                                   params={"revision": document["character"]["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pair_body(self, document):
        pair = self.pair(document)
        def views(encoded):
            return [{"name": name, "yaw_degrees": yaw, "png_base64": encoded}
                    for name, yaw in (("front", 0), ("left45", -45), ("right45", 45),
                                      ("left90", -90), ("right90", 90))]
        return {
            "character_id": document["character"]["id"],
            "revision": document["character"]["revision"],
            "baseline_geometry_hash": pair["baseline"]["geometry_hash"],
            "edited_geometry_hash": pair["edited"]["geometry_hash"],
            "baseline_views": views(self.png_before), "edited_views": views(self.png_after),
        }, pair

    def test_assets_report_real_import_ready_and_model_candidates(self):
        response = self.client.get("/api/assets")
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        status = payload["flame_status"]
        self.assertTrue(status["available"])
        self.assertTrue(status["can_edit_nose"])
        self.assertIn("FLAME2023Open.zip", status["download_url"])
        self.assertEqual(Path(status["inbox_directory"]), self.models_root / "inbox")
        ready = next(asset for asset in payload["assets"] if asset["asset_id"] == self.asset_id)
        self.assertEqual(ready["asset_kind"], "flame_parametric_head")
        self.assertEqual(ready["calibration_status"], "ready")
        self.assertTrue(ready["can_edit_nose"])
        self.assertFalse(ready["is_test_fixture"])
        self.assertNotIn("calibration", ready)
        discovered = self.client.post("/api/flame/discover", json={})
        self.assertEqual(discovered.status_code, 200, discovered.text)
        for candidate in discovered.json()["candidates"]:
            self.assertTrue(Path(candidate["path"]).resolve().is_relative_to(self.models_root / "inbox"))
            self.assertGreater(candidate["size"], 0)
        if self.source_zip.is_file():
            self.assertIn(str(self.source_zip), [candidate["path"] for candidate in discovered.json()["candidates"]])

    def test_reimport_existing_official_zip_returns_reviewed_asset_without_rewriting_models(self):
        if not self.source_zip.is_file():
            self.skipTest("Official source ZIP is absent from local inbox")
        files = [self.models_root / self.asset_id / "metadata.json", self.models_root / self.asset_id / "model.npz"]
        before = [(file.stat().st_mtime_ns, file.stat().st_size) for file in files]
        response = self.client.post("/api/flame/import", json={"path": str(self.source_zip)})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()["asset"]
        self.assertEqual(asset["asset_id"], self.asset_id)
        self.assertEqual(asset["calibration_status"], "ready")
        self.assertTrue(asset["can_edit_nose"])
        self.assertEqual(before, [(file.stat().st_mtime_ns, file.stat().st_size) for file in files])

    def test_import_rejects_existing_files_outside_inbox_and_invalid_paths(self):
        model_outside_inbox = self.models_root / self.asset_id / "model.npz"
        for path in (str(model_outside_inbox), "../model.npz", str(self.data_root / "missing.pkl")):
            with self.subTest(path=path):
                response = self.client.post("/api/flame/import", json={"path": path})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn(str(self.models_root / "inbox"), response.json()["detail"])

    def test_real_flame_character_stores_identity_expression_and_provenance(self):
        document = self.new_flame()
        character = document["character"]
        self.assertEqual(character["base_asset_id"], self.asset_id)
        self.assertEqual(len(character["identity_params"]), 300)
        self.assertEqual(len(character["expression_params"]), 100)
        self.assertEqual(character["identity_params"][0], 0.2)
        self.assertEqual(character["expression_params"][0], 0.1)
        self.assertEqual(character["asset_metadata"]["source_sha256"], self.metadata["source_sha256"])
        self.assertEqual(character["asset_metadata"]["calibration_hash"], self.metadata["calibration_hash"])
        self.assertEqual(character["asset_metadata"]["model_variant"], "flame2023_open")
        self.assertEqual(len(document["mesh"]["vertices"]), self.metadata["vertex_count"])
        self.assertEqual(len(document["mesh"]["faces"]), self.metadata["triangle_count"])
        self.assertEqual(document["asset"]["asset_kind"], "flame_parametric_head")
        self.assertTrue(document["is_saved"])

    def test_preview_changes_only_nasal_support_and_keeps_identity_expression_fixed(self):
        document = self.new_flame()
        character = document["character"]
        for width in (-0.5, 0.5):
            with self.subTest(width=width):
                response = self.client.post("/api/preview", json={"character_id": character["id"], "nose_width": width})
                self.assertEqual(response.status_code, 200, response.text)
                preview = response.json()
                self.assertFalse(preview["is_saved"])
                self.assertEqual(preview["character"]["identity_params"], character["identity_params"])
                self.assertEqual(preview["character"]["expression_params"], character["expression_params"])
                changed = []
                for index, (before, after, weight) in enumerate(zip(document["mesh"]["vertices"], preview["mesh"]["vertices"], preview["mesh"]["edit_weights"])):
                    if before != after:
                        changed.append(index)
                        self.assertGreater(weight, 0)
                    if weight == 0:
                        self.assertEqual(before, after)
                self.assertGreater(len(changed), 0)
                self.assertEqual(len(changed), preview["metrics"]["changed_vertices"])
                self.assertEqual(preview["metrics"]["outside_max_displacement"], 0)
                self.assertEqual(preview["metrics"]["tip_max_displacement"], 0)
                self.assertEqual(preview["metrics"]["bridge_max_displacement"], 0)
        reloaded = self.client.get(f"/api/characters/{character['id']}").json()
        self.assertEqual(reloaded["geometry_hash"], document["geometry_hash"])
        self.assertEqual(reloaded["character"]["revision"], 1)

    def test_save_implicitly_inherits_params_and_fresh_app_rebuilds_identically(self):
        original = self.new_flame()
        character = original["character"]
        original_file = self.data_root / "characters" / character["id"] / "revisions/000001.json"
        old_bytes = original_file.read_bytes()
        response = self.client.post("/api/characters", json={
            "name": "FLAME 鼻翼收窄", "nose_width": -0.5,
            "source_character_id": character["id"], "expected_revision": 1,
        })
        self.assertEqual(response.status_code, 200, response.text)
        saved = response.json()
        self.assertEqual(saved["character"]["revision"], 2)
        self.assertEqual(saved["character"]["identity_params"], character["identity_params"])
        self.assertEqual(saved["character"]["expression_params"], character["expression_params"])
        self.assertEqual(saved["character"]["asset_metadata"], character["asset_metadata"])
        self.assertEqual(original_file.read_bytes(), old_bytes)
        verify = self.client.post(f"/api/characters/{character['id']}/verify")
        self.assertEqual(verify.status_code, 200, verify.text)
        report = verify.json()
        for key in ("passed", "vertex_match", "hash_match", "asset_metadata_match", "read_from_disk"):
            self.assertTrue(report[key], key)
        self.assertEqual(report["max_vertex_error"], 0)
        with TestClient(create_app(data_root=self.data_root, frontend_dist=self.dist, models_root=self.models_root)) as fresh:
            loaded = fresh.get(f"/api/characters/{character['id']}")
            self.assertEqual(loaded.status_code, 200, loaded.text)
            self.assertEqual(loaded.json()["mesh"]["vertices"], saved["mesh"]["vertices"])
            self.assertEqual(loaded.json()["geometry_hash"], saved["geometry_hash"])
            self.assertEqual(loaded.json()["character"]["identity_params"], character["identity_params"])

    def test_pair_has_zero_baseline_and_identical_other_parameters(self):
        document = self.new_flame(-0.5)
        pair = self.pair(document)
        before, after = pair["baseline"], pair["edited"]
        self.assertTrue(pair["same_identity_expression"])
        self.assertFalse(pair["zero_edit"])
        self.assertEqual(before["character"]["nose_width"], 0)
        self.assertEqual(after["character"]["nose_width"], -0.5)
        self.assertEqual(before["character"]["identity_params"], after["character"]["identity_params"])
        self.assertEqual(before["character"]["expression_params"], after["character"]["expression_params"])
        self.assertEqual(before["character"]["base_asset_id"], after["character"]["base_asset_id"])
        self.assertEqual(before["mesh"]["faces"], after["mesh"]["faces"])
        self.assertEqual(before["mesh"]["edit_weights"], after["mesh"]["edit_weights"])
        self.assertNotEqual(before["geometry_hash"], after["geometry_hash"])
        self.assertEqual(pair["render_contract"]["framing"], "shared_baseline_bounds")
        self.assertEqual(pair["render_contract"]["yaws"], [0, -45, 45, -90, 90])

    def test_real_flame_pair_exports_ten_pngs_and_exact_vertex_delta(self):
        document = self.new_flame(-0.5)
        body, pair = self.pair_body(document)
        response = self.client.post("/api/pair-exports", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        directory = Path(result["output_directory"])
        self.assertTrue(directory.is_relative_to(self.data_root.resolve()))
        baseline = pair["baseline"]["mesh"]["vertices"]
        edited = pair["edited"]["mesh"]["vertices"]
        expected_delta = [[b - a for a, b in zip(old, new)] for old, new in zip(baseline, edited)]
        expected_changed = [index for index, (old, new) in enumerate(zip(baseline, edited)) if old != new]
        delta = json.loads((directory / "delta.json").read_text())
        self.assertEqual(delta["canonical_vertex_delta"], expected_delta)
        self.assertEqual(delta["changed_vertex_indices"], expected_changed)
        self.assertEqual(delta["changed_vertices"], len(expected_changed))
        self.assertGreater(delta["changed_vertices"], 0)
        self.assertEqual(delta["outside_max_displacement"], 0)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["asset"]["source_sha256"], self.metadata["source_sha256"])
        self.assertIn("FLAME", manifest["asset"]["attribution"])
        self.assertEqual(manifest["baseline_parameters"]["identity_params"], manifest["edited_parameters"]["identity_params"])
        download = self.client.get(result["download_url"])
        self.assertEqual(download.status_code, 200, download.text[:100] if download.status_code != 200 else "")
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            pngs = [name for name in names if "/views/" in name and name.endswith(".png")]
            self.assertEqual(len(pngs), 10)
            self.assertNotIn("model.npz", names)
            self.assertFalse(any(name.endswith(".pkl") for name in names))
            for item in manifest["pairs"]:
                for role in ("baseline", "edited"):
                    raw = archive.read(item[f"{role}_path"])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), item[f"{role}_sha256"])
                    with Image.open(io.BytesIO(raw)) as image:
                        self.assertEqual(image.size, (768, 768))
        sheet = self.client.get(result["contact_sheet_url"])
        self.assertEqual(sheet.status_code, 200)
        with Image.open(io.BytesIO(sheet.content)) as image:
            self.assertEqual(image.size, (1600, 756))

    def test_pair_export_rejects_stale_hash_without_creating_files(self):
        document = self.new_flame(-0.5)
        body, _pair = self.pair_body(document)
        for field in ("baseline_geometry_hash", "edited_geometry_hash"):
            with self.subTest(field=field):
                invalid = {**body, field: "0" * 64}
                response = self.client.post("/api/pair-exports", json=invalid)
                self.assertEqual(response.status_code, 409, response.text)
        directory = self.data_root / "characters" / document["character"]["id"] / "pair-exports"
        self.assertFalse(directory.exists())

    def test_existing_scan_schema_and_pair_still_work(self):
        path = self.data_root / "characters" / self.scan["id"] / "revisions/000001.json"
        legacy = json.loads(path.read_text())
        for key in ("identity_params", "expression_params", "asset_metadata"):
            legacy.pop(key, None)
        path.write_text(json.dumps(legacy), encoding="utf-8")
        old_bytes = path.read_bytes()
        response = self.client.get(f"/api/characters/{self.scan['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        document = response.json()
        self.assertEqual(document["character"]["identity_params"], [])
        self.assertEqual(document["character"]["expression_params"], [])
        self.assertEqual(document["character"]["asset_metadata"], {})
        self.assertEqual(path.read_bytes(), old_bytes)
        self.assertEqual(document["asset"]["asset_kind"], "static_head_scan")
        pair = self.pair(document)
        self.assertTrue(pair["zero_edit"])
        self.assertEqual(pair["baseline"]["geometry_hash"], pair["edited"]["geometry_hash"])

    def test_invalid_identity_expression_inputs_are_rejected_before_saving(self):
        initial_count = len(self.client.get("/api/characters").json()["characters"])
        for key, value in (("identity_params", [True]), ("identity_params", ["0.2"]),
                           ("identity_params", [0.0] * 301), ("expression_params", [0.0] * 101)):
            with self.subTest(key=key, value=str(value)[:40]):
                response = self.client.post("/api/characters", json={
                    "name": "拒绝无效参数", "nose_width": 0, "asset_id": self.asset_id, key: value,
                })
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(self.client.get("/api/characters").json()["characters"]), initial_count)

    def test_modified_saved_provenance_cannot_pass_rebuild_verification(self):
        document = self.new_flame(-0.5)
        character = document["character"]
        path = self.data_root / "characters" / character["id"] / "revisions/000001.json"
        changed = json.loads(path.read_text())
        changed["asset_metadata"]["calibration_hash"] = "0" * 64
        path.write_text(json.dumps(changed), encoding="utf-8")
        response = self.client.post(f"/api/characters/{character['id']}/verify")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["passed"])
        self.assertFalse(response.json()["asset_metadata_match"])


if __name__ == "__main__":
    unittest.main()
