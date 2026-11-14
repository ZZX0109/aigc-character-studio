"""Paired-file protocol tests, using plain PNG fixtures, not FLAME renders."""

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
from unittest.mock import patch
import zipfile

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_studio.geometry import canonical_hash, geometry_hash
from character_studio.pair_export import PairExportError, export_pair_bundle


def png_fixture(color: str, size=(768, 768)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def geometry_fixture(amount: float) -> dict:
    positions = [[-1.0 - amount * 0.2, 0.0, 0.0], [1.0 + amount * 0.2, 0.0, 0.0],
                 [0.0, 1.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]
    faces = [[0, 1, 2], [0, 3, 1], [0, 4, 3]]
    return {"asset_id": "protocol-fixture", "deformation_version": "fixture-v1",
            "parameters": {"nose_width": amount, "identity_params": [0.2, -0.1],
                           "expression_params": [0.0]},
            "positions": positions, "indices": faces, "mask_weights": [1.0, 1.0, 0.0, 0.0, 0.0],
            "geometry_hash": geometry_hash(positions, faces),
            "topology_hash": canonical_hash({"vertex_count": len(positions), "indices": faces}),
            "unit": "test_canonical_units", "stats": {"fixture_only": True}}


class PairExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "exports"
        self.baseline = geometry_fixture(0)
        self.edited = geometry_fixture(0.5)
        self.character = {"id": "char_fixture", "name": "配对协议测试", "revision": 2,
                          "nose_width": 0.5, "geometry_hash": self.edited["geometry_hash"],
                          "base_asset_id": "protocol-fixture"}
        self.asset = {"asset_id": "protocol-fixture", "name": "Protocol fixture, not FLAME",
                      "license": "test-only", "attribution": "Test fixture",
                      "source_url": "https://example.invalid/test-fixture", "source_sha256": "f" * 64,
                      "model_path": "/private/models/do-not-distribute.npz",
                      "shapedirs": ["do not distribute basis arrays"]}
        self.verification = {"passed": True, "character_id": "char_fixture", "revision": 2,
                             "vertex_match": True, "hash_match": True}
        self.before = self.views("#d9c5af")
        self.after = self.views("#c4a78c")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def views(color):
        encoded = base64.b64encode(png_fixture(color)).decode("ascii")
        return [{"name": name, "yaw_degrees": yaw, "png_base64": "data:image/png;base64," + encoded}
                for name, yaw in (("front", 0), ("left45", -45), ("right45", 45),
                                  ("left90", -90), ("right90", 90))]

    def export(self, **kwargs):
        arguments = dict(character=self.character, baseline_geometry=self.baseline,
                         edited_geometry=self.edited, baseline_views=self.before,
                         edited_views=self.after, asset=self.asset,
                         verification=self.verification, output_root=self.root)
        arguments.update(kwargs)
        return export_pair_bundle(**arguments)

    def assert_no_output(self):
        self.assertTrue(not self.root.exists() or not list(self.root.iterdir()))

    def test_bundle_contains_ten_paired_pngs_meshes_deltas_and_provenance(self):
        result = self.export()
        directory = Path(result["output_directory"])
        self.assertEqual(directory.parent, self.root.resolve())
        self.assertTrue(result["id"].startswith("pair_"))
        self.assertEqual(len(result["pairs"]), 5)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["source_saved_revision"], 2)
        self.assertTrue(manifest["reference_contract"]["same_non_edit_parameters_verified"])
        self.assertFalse(manifest["reference_contract"]["pixel_alignment_guaranteed"])
        self.assertEqual(manifest["asset"]["attribution"], "Test fixture")
        self.assertNotIn("model_path", manifest["asset"])
        self.assertNotIn("shapedirs", manifest["asset"])
        with zipfile.ZipFile(result["bundle_path"]) as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            self.assertEqual(len([name for name in names if "/views/" in name and name.endswith(".png")]), 10)
            for name in ("baseline/mesh.obj", "edited/mesh.obj", "baseline/mesh.json", "edited/mesh.json",
                         "baseline/character.json", "edited/character.json", "delta.json",
                         "manifest.json", "verification.json", "contact-sheet.png"):
                self.assertIn(name, names)
        for pair in result["pairs"]:
            for role in ("baseline", "edited"):
                data = (directory / pair[f"{role}_path"]).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), pair[f"{role}_sha256"])
                with Image.open(io.BytesIO(data)) as image:
                    self.assertEqual(image.size, (768, 768))
        delta = json.loads((directory / "delta.json").read_text())
        self.assertEqual(delta["changed_vertex_indices"], [0, 1])
        self.assertEqual(delta["outside_max_displacement"], 0)
        self.assertAlmostEqual(delta["canonical_vertex_delta"][0][0], -0.1)
        self.assertAlmostEqual(delta["canonical_vertex_delta"][1][0], 0.1)
        self.assertEqual(delta["canonical_vertex_delta"][2:], [[0.0, 0.0, 0.0]] * 3)
        original = json.loads((directory / "baseline/character.json").read_text())
        self.assertEqual(original["nose_width"], 0)
        self.assertTrue(original["derived_reference_not_a_separate_saved_revision"])
        self.assertEqual(original["parameters"]["identity_params"], self.baseline["parameters"]["identity_params"])

    def test_pairing_is_by_yaw_not_client_list_order(self):
        result = self.export(baseline_views=list(reversed(self.before)), edited_views=list(reversed(self.after)))
        self.assertEqual([pair["yaw_degrees"] for pair in result["pairs"]], [0, -45, 45, -90, 90])

    def test_zero_edit_is_explicitly_reported(self):
        character = deepcopy(self.character)
        character.update(nose_width=0, geometry_hash=self.baseline["geometry_hash"])
        result = self.export(character=character, edited_geometry=deepcopy(self.baseline))
        self.assertTrue(any("zero_edit" in warning for warning in result["warnings"]))
        self.assertEqual(result["manifest"]["changed_vertices"], 0)

    def test_each_export_is_immutable_and_has_a_new_directory(self):
        first = self.export()
        data = Path(first["bundle_path"]).read_bytes()
        second = self.export()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(Path(first["bundle_path"]).read_bytes(), data)
        self.assertFalse(any(path.name.endswith(".pending") for path in self.root.iterdir()))

    def test_unverified_or_wrong_revision_is_rejected(self):
        for verification in ({"passed": False}, {"passed": 1}, {**self.verification, "revision": 1},
                             {**self.verification, "character_id": "other"}):
            with self.subTest(verification=verification):
                with self.assertRaises(PairExportError):
                    self.export(verification=verification)
                self.assert_no_output()

    def test_geometry_tampering_is_rejected_before_writing(self):
        tampered = deepcopy(self.edited)
        tampered["positions"][0][0] -= 0.1
        with self.assertRaisesRegex(PairExportError, "geometry hash"):
            self.export(edited_geometry=tampered)
        self.assert_no_output()

    def test_verification_hash_and_saved_topology_must_match(self):
        with self.assertRaisesRegex(PairExportError, "Verification geometry hash"):
            self.export(verification={**self.verification, "geometry_hash": "a" * 64})
        with self.assertRaisesRegex(PairExportError, "saved character"):
            self.export(character={**self.character, "topology_id": "a" * 64})
        self.assert_no_output()

    def test_derived_baseline_does_not_reuse_edited_snapshot_checksum(self):
        character = {**self.character, "snapshot_hash": "a" * 64,
                     "mesh_vertices": self.edited["positions"]}
        result = self.export(character=character)
        data = json.loads((Path(result["output_directory"]) / "baseline/character.json").read_text())
        self.assertNotIn("snapshot_hash", data)
        self.assertNotIn("mesh_vertices", data)
        self.assertEqual(data["source_saved_snapshot_hash"], "a" * 64)
        self.assertEqual(data["geometry_hash"], self.baseline["geometry_hash"])

    def test_topology_and_non_edit_parameters_must_match(self):
        for field, value in (("identity_params", [0.3, -0.1]), ("expression_params", [0.1])):
            with self.subTest(field=field):
                changed = deepcopy(self.edited)
                changed["parameters"][field] = value
                with self.assertRaisesRegex(PairExportError, "non-edit parameters"):
                    self.export(edited_geometry=changed)
                self.assert_no_output()
        changed = deepcopy(self.edited)
        changed["indices"][0] = [0, 2, 1]
        changed["topology_hash"] = canonical_hash({"vertex_count": len(changed["positions"]), "indices": changed["indices"]})
        changed["geometry_hash"] = geometry_hash(changed["positions"], changed["indices"])
        character = {**self.character, "geometry_hash": changed["geometry_hash"]}
        with self.assertRaisesRegex(PairExportError, "same vertices and topology"):
            self.export(character=character, edited_geometry=changed)

    def test_an_outside_support_change_is_rejected_even_with_valid_hash(self):
        changed = deepcopy(self.edited)
        changed["positions"][2][1] += 0.1
        changed["geometry_hash"] = geometry_hash(changed["positions"], changed["indices"])
        character = {**self.character, "geometry_hash": changed["geometry_hash"]}
        with self.assertRaisesRegex(PairExportError, "outside"):
            self.export(character=character, edited_geometry=changed)
        self.assert_no_output()

    def test_geometry_and_character_parameters_cannot_claim_different_edits(self):
        character = {**self.character, "nose_width": -0.5}
        with self.assertRaisesRegex(PairExportError, "nose_width"):
            self.export(character=character)
        with self.assertRaisesRegex(PairExportError, "baseline nose_width"):
            self.export(baseline_geometry=self.edited)
        self.assert_no_output()

    def test_views_require_matching_names_unique_yaws_and_safe_paths(self):
        variants = []
        views = deepcopy(self.before); views[0]["name"] = "../escape"; variants.append(views)
        views = deepcopy(self.before); views[1]["name"] = "front"; variants.append(views)
        views = deepcopy(self.before); views[1]["yaw_degrees"] = 0; variants.append(views)
        views = deepcopy(self.before); views[0]["yaw_degrees"] = True; variants.append(views)
        variants.append(self.before[:4])
        for views in variants:
            with self.subTest(views=[view["name"] for view in views]):
                with self.assertRaises(PairExportError):
                    self.export(baseline_views=views)
                self.assert_no_output()
        mismatched = deepcopy(self.after); mismatched[0]["name"] = "another_front"
        with self.assertRaisesRegex(PairExportError, "same view name"):
            self.export(edited_views=mismatched)

    def test_invalid_or_truncated_pngs_and_wrong_dimensions_are_rejected(self):
        bad_values = ["not a png", "data:image/jpeg;base64,AAAA",
                      base64.b64encode(png_fixture("red", size=(320, 320))).decode(),
                      base64.b64encode(png_fixture("red")[:100]).decode()]
        for bad in bad_values:
            with self.subTest(prefix=bad[:30]):
                views = deepcopy(self.before); views[0]["png_base64"] = bad
                with self.assertRaises(PairExportError):
                    self.export(baseline_views=views)
                self.assert_no_output()

    def test_non_finite_numbers_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                changed = deepcopy(self.edited); changed["positions"][0][0] = value
                with self.assertRaises(PairExportError):
                    self.export(edited_geometry=changed)
                self.assert_no_output()

    def test_write_failure_leaves_no_partial_bundle(self):
        with patch("character_studio.pair_export._write_mesh", side_effect=OSError("test disk failure")):
            with self.assertRaises(OSError):
                self.export()
        self.assert_no_output()


if __name__ == "__main__":
    unittest.main()
