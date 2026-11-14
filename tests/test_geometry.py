"""Scientific invariants of the local edit; does not require a browser/GPU."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_studio.geometry import (  # noqa: E402
    build_geometry, get_asset_info, load_base_asset, region_weight,
)


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_base_asset()
        cls.zero = build_geometry()

    def test_base_asset_is_attributed_real_triangle_mesh(self):
        info = get_asset_info()
        self.assertEqual(info["license"], "CC-BY-3.0")
        self.assertEqual(info["asset_kind"], "static_head_scan")
        self.assertEqual(info["vertex_count"], 9279)
        self.assertEqual(info["triangle_count"], 17684)
        source = ROOT / "data/base-face/source/LeePerrySmith.glb"
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), info["source_sha256"])
        self.assertEqual(info["coordinate_system"], "right_handed_y_up_face_positive_z")
        self.assertAlmostEqual(info["bounds"]["size"][1], 3)

    def test_zero_edit_recovers_exact_base_and_topology(self):
        self.assertEqual(self.zero["positions"], self.base["positions"])
        self.assertEqual(self.zero["indices"], self.base["indices"])
        self.assertEqual(self.zero["geometry_hash"], self.base["base_geometry_hash"])
        self.assertEqual(self.zero["stats"]["changed_vertices"], 0)

    def test_edit_only_changes_lateral_coordinates_inside_alar_support(self):
        edited = build_geometry(0.8)
        changed = []
        for i, (before, after, weight) in enumerate(zip(self.base["positions"], edited["positions"], edited["mask_weights"])):
            self.assertEqual(before[1:], after[1:])
            if weight == 0:
                self.assertEqual(before, after)
            if before != after:
                changed.append(i)
                self.assertGreater(weight, 0)
                self.assertGreater((after[0] - before[0]) * (before[0] - self.base["edit_region"]["midline_x"]), 0)
        self.assertGreater(len(changed), 100)
        self.assertLess(len(changed), len(edited["positions"]) / 10)
        self.assertEqual(edited["stats"]["outside_max_displacement"], 0)
        self.assertEqual(edited["stats"]["tip_max_displacement"], 0)
        self.assertEqual(edited["stats"]["bridge_max_displacement"], 0)
        self.assertEqual(edited["indices"], self.base["indices"])
        self.assertEqual(edited["topology_hash"], self.zero["topology_hash"])

    def test_alar_measurement_is_monotonic_and_both_directions_work(self):
        widths = [build_geometry(p)["stats"]["nose_width_measure"] for p in [-1, -.5, 0, .5, 1]]
        self.assertTrue(all(a < b for a, b in zip(widths, widths[1:])))
        self.assertAlmostEqual(widths[2] - widths[0], widths[-1] - widths[2], places=8)
        self.assertLess(build_geometry(-1)["stats"]["nose_width_change_ratio"], -0.1)
        self.assertGreater(build_geometry(1)["stats"]["nose_width_change_ratio"], 0.1)

    def test_mask_peak_and_measurement_anchors_are_on_reviewed_nasal_alae(self):
        points = self.base["positions"]
        weights = self.base["mask_weights"]
        midline = self.base["edit_region"]["midline_x"]
        for side in [-1, 1]:
            candidates = [i for i, p in enumerate(points) if (p[0] - midline) * side > 0]
            peak = max(candidates, key=lambda i: weights[i])
            x, y, z = points[peak]
            self.assertGreater(weights[peak], 0.5)
            self.assertTrue(.33 <= y <= .42, (peak, points[peak]))
            self.assertTrue(.80 <= z <= .91, (peak, points[peak]))
            self.assertTrue(.09 <= abs(x - midline) <= .17, (peak, points[peak]))
        for index in self.base["alar_landmark_indices"]:
            x, y, z = points[index]
            self.assertTrue(.33 <= y <= .42, (index, points[index]))
            self.assertTrue(.80 <= z <= .91, (index, points[index]))
            self.assertGreater(weights[index], 0.5)
        # Earlier coordinate estimates selected nasolabial/cheek vertices.
        # These visually reviewed negative landmarks must remain untouched.
        for index in [2303, 2300, 6996]:
            self.assertEqual(weights[index], 0, (index, points[index]))

    def test_edit_field_is_symmetric_even_though_scan_is_not(self):
        region = self.base["edit_region"]
        for dx in [.04, .10, .15, .20, .30]:
            right = [region["midline_x"] + dx, region["center_y"], region["center_z"]]
            left = [region["midline_x"] - dx, region["center_y"], region["center_z"]]
            self.assertAlmostEqual(region_weight(right, region), region_weight(left, region), places=12)

    def test_protected_support_boundary_tapers_continuously(self):
        r = self.base["edit_region"]
        boundary = r["midline_x"] + r["protected_center_half_width"]
        p = [boundary, r["center_y"], r["center_z"]]
        self.assertEqual(region_weight(p, r), 0)
        p[0] += 1e-7
        self.assertLess(region_weight(p, r), 1e-12)

    def test_invalid_controls_are_rejected(self):
        for value in [True, False, "0.5", None, float("nan"), float("inf"), -1.01, 1.01]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_geometry(value)

    def test_valid_parameter_extremes_preserve_triangle_orientation(self):
        def normal(points, face):
            a, b, c = (points[i] for i in face)
            ab = [b[i] - a[i] for i in range(3)]
            ac = [c[i] - a[i] for i in range(3)]
            return [ab[1] * ac[2] - ab[2] * ac[1],
                    ab[2] * ac[0] - ab[0] * ac[2],
                    ab[0] * ac[1] - ab[1] * ac[0]]
        for value in [-1, 1]:
            edited = build_geometry(value)
            for face in self.base["indices"]:
                before = normal(self.base["positions"], face)
                after = normal(edited["positions"], face)
                dot = sum(a * b for a, b in zip(before, after))
                self.assertGreater(dot, 0, (value, face))

    def test_save_reload_parameters_and_vertices_are_bitwise_repeatable(self):
        before = build_geometry(-0.375)
        serialized = json.dumps({"asset_id": before["asset_id"],
                                 "deformation_version": before["deformation_version"],
                                 "parameters": before["parameters"],
                                 "positions": before["positions"],
                                 "geometry_hash": before["geometry_hash"]}, allow_nan=False)
        restored = json.loads(serialized)
        after = build_geometry(**restored["parameters"])
        self.assertEqual(restored["positions"], after["positions"])
        self.assertEqual(restored["geometry_hash"], after["geometry_hash"])
        self.assertEqual(before["topology_hash"], after["topology_hash"])

    def test_templates_and_generated_meshes_cannot_mutate_shared_base(self):
        first = build_geometry(.5)
        first["positions"][0][0] = 12345
        first["indices"][0][0] = 12345
        external_base = load_base_asset()
        external_base["positions"][0][0] = -12345
        self.assertEqual(build_geometry()["geometry_hash"], self.zero["geometry_hash"])
        self.assertNotEqual(build_geometry()["positions"][0][0], -12345)

    def test_pinned_asset_conversion_is_reproducible_without_network(self):
        spec = importlib.util.spec_from_file_location("prepare_face_asset", ROOT / "scripts/prepare_face_asset.py")
        prepare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prepare)
        payload = (ROOT / "data/base-face/source/LeePerrySmith.glb").read_bytes()
        rebuilt = prepare.convert(payload)
        existing = json.loads((ROOT / "data/base-face/base-face.json").read_text())
        self.assertEqual(rebuilt, existing)


if __name__ == "__main__":
    unittest.main()
