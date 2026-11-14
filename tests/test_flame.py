"""FLAME parser/math regression tests; tiny inputs are explicitly fixtures."""
from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import pickle
import tempfile
import unittest
import zipfile

import numpy as np

from character_studio.flame import (
    CalibrationRequired, FlameError, build_geometry, calibrate_asset,
    get_asset_info, import_model, list_assets,
)


def fixture_arrays() -> dict:
    points = np.array([
        [-.25, 0, .5], [.25, 0, .5], [0, .12, .8], [0, .55, .4],
        [-1, -1, -.2], [1, -1, -.2], [-.8, 1, -.2], [.8, 1, -.2],
        [0, -.3, .45],
    ], dtype=np.float64)
    faces = np.array([[0, 2, 3], [1, 3, 2], [0, 4, 8], [1, 8, 5],
                      [0, 6, 4], [1, 5, 7], [3, 6, 0], [3, 1, 7]], dtype=np.int64)
    directions = np.zeros((len(points), 3, 400))
    directions[4, 0, 0] = .04
    directions[8, 1, 300] = .06
    return {"v_template": points, "f": faces, "shapedirs": directions}


class FlameCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.models = self.root / "models"
        self.source = self.root / "fixture.npz"
        np.savez(self.source, **fixture_arrays())
        self.meta = import_model(self.source, self.models, _test_fixture=True)
        self.asset_id = self.meta["asset_id"]

    def tearDown(self):
        self.temporary.cleanup()

    def calibration(self) -> dict:
        geometry = build_geometry(self.asset_id, root=self.models)
        return {
            "reviewed": True, "review_note": "synthetic fixture support; not an anatomical review",
            "base_geometry_hash": geometry["geometry_hash"],
            "weights": [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "alar_landmark_indices": [0, 1], "protected_tip_indices": [2],
            "protected_bridge_indices": [3], "max_lateral_displacement": .04, "midline_x": 0.0,
        }

    def test_synthetic_fixtures_are_not_listed_as_real_models(self):
        self.assertTrue(self.meta["is_test_fixture"])
        self.assertEqual(self.meta["asset_kind"], "synthetic_test_fixture")
        self.assertEqual(list_assets(self.models), [])
        self.assertEqual(len(list_assets(self.models, include_test_fixtures=True)), 1)

    def test_production_import_does_not_mislabel_arbitrary_mesh_as_flame(self):
        with self.assertRaisesRegex(FlameError, "5,023"):
            import_model(self.source, self.models)

    def test_neutral_rebuild_uses_fixed_canonical_transform(self):
        geometry = build_geometry(self.asset_id, root=self.models)
        self.assertEqual(geometry["bounds"]["size"][1], 3)
        self.assertEqual(geometry["stats"]["changed_vertices"], 0)
        self.assertEqual(geometry["geometry_hash"], self.meta["base_geometry_hash"])
        self.assertEqual(geometry["stats"]["calibration_status"], "calibration_required")

    def test_identity_and_expression_dimensions_are_separate(self):
        base = np.array(build_geometry(self.asset_id, root=self.models)["positions"])
        shape = np.array(build_geometry(self.asset_id, identity_params=[1], root=self.models)["positions"])
        expression = np.array(build_geometry(self.asset_id, expression_params=[1], root=self.models)["positions"])
        self.assertAlmostEqual(shape[4, 0] - base[4, 0], .06)
        self.assertAlmostEqual(expression[8, 1] - base[8, 1], .09)
        self.assertTrue(np.array_equal(shape[8], base[8]))
        self.assertTrue(np.array_equal(expression[4], base[4]))

    def test_reimport_is_idempotent_and_does_not_replace_model(self):
        original = (self.models / self.asset_id / "model.npz").read_bytes()
        again = import_model(self.source, self.models, _test_fixture=True)
        self.assertEqual(again["asset_id"], self.asset_id)
        self.assertEqual(original, (self.models / self.asset_id / "model.npz").read_bytes())

    def test_nonzero_edit_requires_review(self):
        with self.assertRaises(CalibrationRequired):
            build_geometry(self.asset_id, .1, root=self.models)

    def test_calibration_creates_immutable_derivative_and_preserves_parent(self):
        ready = calibrate_asset(self.asset_id, self.calibration(), self.models)
        self.assertNotEqual(ready["asset_id"], self.asset_id)
        self.assertEqual(ready["parent_asset_id"], self.asset_id)
        self.assertEqual(get_asset_info(self.asset_id, self.models)["calibration_status"], "calibration_required")
        self.assertEqual(ready, calibrate_asset(self.asset_id, self.calibration(), self.models))

    def test_local_edit_is_monotonic_without_leaking_to_protected_vertices(self):
        ready = calibrate_asset(self.asset_id, self.calibration(), self.models)
        results = [build_geometry(ready["asset_id"], amount, root=self.models) for amount in [-1, -.5, 0, .5, 1]]
        spans = [result["stats"]["nose_width_measure"] for result in results]
        self.assertEqual(spans, sorted(spans))
        baseline = results[2]["positions"]
        for result in results:
            self.assertEqual(result["stats"]["outside_max_displacement"], 0)
            self.assertEqual(result["stats"]["tip_max_displacement"], 0)
            self.assertEqual(result["stats"]["bridge_max_displacement"], 0)
            self.assertEqual(result["positions"][2:], baseline[2:])

    def test_parameter_save_reload_rebuilds_identical_vertices_and_hash(self):
        ready = calibrate_asset(self.asset_id, self.calibration(), self.models)
        before = build_geometry(ready["asset_id"], -.5, identity_params=[.3], expression_params=[.2], root=self.models)
        record = json.loads(json.dumps(before["parameters"]))
        after = build_geometry(ready["asset_id"], **record, root=self.models)
        self.assertEqual(before["positions"], after["positions"])
        self.assertEqual(before["geometry_hash"], after["geometry_hash"])

    def test_calibration_rejects_wrong_template_protected_overlap_and_nan(self):
        variants = []
        invalid = self.calibration(); invalid["base_geometry_hash"] = "0" * 64; variants.append(invalid)
        invalid = self.calibration(); invalid["weights"][2] = .1; variants.append(invalid)
        invalid = self.calibration(); invalid["weights"][0] = float("nan"); variants.append(invalid)
        invalid = self.calibration(); invalid["alar_landmark_indices"] = [0, 0]; variants.append(invalid)
        invalid = self.calibration(); invalid["max_lateral_displacement"] = 100; variants.append(invalid)
        invalid = self.calibration(); invalid["reviewed"] = False; variants.append(invalid)
        for invalid in variants:
            with self.subTest(invalid=invalid):
                with self.assertRaises(FlameError): calibrate_asset(self.asset_id, invalid, self.models)

    def test_parameters_and_ids_reject_nonfinite_values_and_path_escape(self):
        for value in [True, float("nan"), float("inf"), 2, "0.2"]:
            with self.subTest(value=value):
                with self.assertRaises(FlameError): build_geometry(self.asset_id, value, root=self.models)
        for params in [[True], [float("nan")], [6], [0] * 301]:
            with self.assertRaises(FlameError): build_geometry(self.asset_id, identity_params=params, root=self.models)
        with self.assertRaises(FlameError): get_asset_info("../../escape", self.models)

    def test_model_hash_is_checked_even_after_array_cache_is_warm(self):
        build_geometry(self.asset_id, root=self.models)
        path = self.models / self.asset_id / "model.npz"
        payload = bytearray(path.read_bytes()); payload[-1] ^= 1; path.write_bytes(payload)
        with self.assertRaisesRegex(FlameError, "校验失败"):
            build_geometry(self.asset_id, root=self.models)

    def test_unsafe_pickle_global_is_rejected_without_execution(self):
        sentinel = self.root / "executed"

        class Malicious:
            def __reduce__(self):
                import os
                return (os.system, (f"touch {sentinel}",))

        path = self.root / "unsafe.pkl"
        path.write_bytes(pickle.dumps({"payload": Malicious()}))
        with self.assertRaisesRegex(FlameError, "序列化对象"):
            import_model(path, self.models)
        self.assertFalse(sentinel.exists())

    def test_numeric_pickle_and_scalar_npy_container_are_supported(self):
        for suffix, payload in [(".pkl", pickle.dumps(fixture_arrays(), protocol=4))]:
            path = self.root / ("numeric" + suffix); path.write_bytes(payload)
            result = import_model(path, self.models, _test_fixture=True)
            self.assertEqual(result["vertex_count"], 9)
        stream = io.BytesIO(); np.save(stream, fixture_arrays(), allow_pickle=True)
        path = self.root / "scalar.npy"; path.write_bytes(stream.getvalue())
        result = import_model(path, self.models, _test_fixture=True)
        self.assertEqual(result["vertex_count"], 9)

    def test_zip_selects_unique_open_model_without_extracting_paths(self):
        path = self.root / "bundle.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../../flame2023_Open.pkl", pickle.dumps(fixture_arrays(), protocol=4))
        result = import_model(path, self.models, _test_fixture=True)
        self.assertEqual(result["vertex_count"], 9)
        self.assertFalse((self.root.parent / "flame2023_Open.pkl").exists())

    def test_object_npz_and_incompatible_basis_are_rejected(self):
        path = self.root / "object.npz"
        data = fixture_arrays(); data["object"] = np.array([{"arbitrary": "object"}], dtype=object)
        np.savez(path, **data)
        with self.assertRaises(FlameError): import_model(path, self.models, _test_fixture=True)
        data = fixture_arrays(); data["shapedirs"] = data["shapedirs"][:, :, :399]
        path = self.root / "short.npz"; np.savez(path, **data)
        with self.assertRaisesRegex(FlameError, "shapedirs"):
            import_model(path, self.models, _test_fixture=True)


@unittest.skipUnless((Path(__file__).resolve().parents[1] / "models/flame/inbox/FLAME2023Open.zip").is_file(), "official local model not available")
class RealFlameRegressionTests(unittest.TestCase):
    def test_real_model_reviewed_support_and_pair_are_consistent(self):
        root = Path(__file__).resolve().parents[1] / "models/flame"
        ready = import_model(root / "inbox/FLAME2023Open.zip", root)
        self.assertFalse(ready["is_test_fixture"])
        self.assertEqual(ready["calibration_status"], "ready")
        self.assertEqual(ready["vertex_count"], 5023)
        self.assertEqual(ready["triangle_count"], 9976)
        base = build_geometry(ready["asset_id"], root=root)
        narrow = build_geometry(ready["asset_id"], -.5, root=root)
        wide = build_geometry(ready["asset_id"], .5, root=root)
        for geometry in [narrow, wide]:
            self.assertEqual(geometry["stats"]["outside_max_displacement"], 0)
            self.assertEqual(geometry["stats"]["tip_max_displacement"], 0)
            self.assertEqual(geometry["stats"]["bridge_max_displacement"], 0)
            self.assertGreater(geometry["stats"]["changed_vertices"], 0)
        self.assertLess(narrow["stats"]["nose_width_measure"], base["stats"]["nose_width_measure"])
        self.assertGreater(wide["stats"]["nose_width_measure"], base["stats"]["nose_width_measure"])
        positions = np.asarray(base["positions"])
        anchors = ready["calibration"]["alar_landmark_indices"]
        self.assertTrue(np.all((positions[anchors, 1] > .08) & (positions[anchors, 1] < .18)))
        self.assertTrue(np.all(positions[anchors, 2] > .9))


if __name__ == "__main__":
    unittest.main()
