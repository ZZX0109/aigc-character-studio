"""Scientific pairing and manifest-integrity checks; no model dependencies."""

from copy import deepcopy
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import random
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("make_manifest", ROOT / "scripts/make_manifest.py")
manifest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manifest)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.config = manifest.load_config(ROOT / "configs/pilot.json")

    def test_pilot_counts_and_planning_status(self):
        jobs = manifest.build_jobs(self.config)
        summary = manifest.summarize(jobs)
        self.assertEqual(summary["total_jobs"], 54)
        self.assertEqual(summary["original_jobs"], 18)
        self.assertEqual(summary["edited_jobs"], 36)
        self.assertEqual(set(summary["jobs_by_method"].values()), {18})
        self.assertTrue(all(job["execution_status"] == "planned" for job in jobs))
        self.assertTrue(all(job["asset_status"] == "pending" for job in jobs))
        self.assertTrue(all(job["output_video"] is None for job in jobs))
        proposed = [job for job in jobs if job["method_id"] == "proposed_geometry_delta"]
        self.assertTrue(all(job["implementation_status"] == "planned" for job in proposed))

    def test_every_edit_has_unique_matching_original(self):
        jobs = manifest.build_jobs(self.config)
        by_id = {job["job_id"]: job for job in jobs}
        self.assertEqual(len(by_id), len(jobs))
        for job in jobs:
            if job["state_id"] == "original":
                self.assertIsNone(job["baseline_job_id"])
                continue
            baseline = by_id[job["baseline_job_id"]]
            self.assertEqual(baseline["state_id"], "original")
            for key in ("character_id", "method_id", "motion_input_mode", "shot_id",
                        "start_yaw_degrees", "driver_id", "seed"):
                self.assertEqual(baseline[key], job[key])
            self.assertIn("does not guarantee pixel alignment", job["pairing_note"])
            self.assertIn("requested driver specification", job["pairing_note"])
            self.assertIn("text-only baselines do not consume driving video", job["pairing_note"])

    def test_requested_yaw_distinguishes_reference_selection(self):
        jobs = manifest.build_jobs(self.config)
        for job in jobs:
            expected_yaw = 45 if job["shot_id"] == "turn_profile" else 0
            self.assertEqual(job["start_yaw_degrees"], expected_yaw)
        changed = deepcopy(self.config)
        changed["shots"][1]["start_yaw_degrees"] = 30
        for before, after in zip(jobs, manifest.build_jobs(changed)):
            if before["shot_id"] == "turn_profile":
                self.assertNotEqual(before["job_id"], after["job_id"])
            else:
                self.assertEqual(before["job_id"], after["job_id"])

    def test_motion_interface_is_explicit_and_part_of_job_id(self):
        jobs = manifest.build_jobs(self.config)
        for job in jobs:
            expected_mode = ("planned_geometry_driver" if job["method_id"] == "proposed_geometry_delta"
                             else "text_only")
            self.assertEqual(job["motion_input_mode"], expected_mode)
        changed = deepcopy(self.config)
        changed["methods"][0]["motion_input_mode"] = "planned_geometry_driver"
        for before, after in zip(jobs, manifest.build_jobs(changed)):
            if before["method_id"] == "consisid_frontal":
                self.assertNotEqual(before["job_id"], after["job_id"])
            else:
                self.assertEqual(before["job_id"], after["job_id"])

    def test_invalid_motion_modes_and_yaw_are_rejected(self):
        invalid = deepcopy(self.config)
        invalid["methods"][0]["motion_input_mode"] = "driving_video"
        with self.assertRaisesRegex(ValueError, "motion_input_mode"):
            manifest.build_jobs(invalid)
        for yaw in (True, "45", None, -181, 181):
            with self.subTest(yaw=yaw):
                invalid = deepcopy(self.config)
                invalid["shots"][0]["start_yaw_degrees"] = yaw
                with self.assertRaisesRegex(ValueError, "start_yaw_degrees"):
                    manifest.build_jobs(invalid)

    def test_ids_and_output_are_independent_of_configuration_order(self):
        shuffled = deepcopy(self.config)
        rng = random.Random(2026)
        for key in ("characters", "states", "shots", "seeds", "methods"):
            rng.shuffle(shuffled[key])
        self.assertEqual(manifest.build_jobs(self.config), manifest.build_jobs(shuffled))

    def test_changed_edit_magnitude_changes_only_relevant_job_ids(self):
        changed = deepcopy(self.config)
        changed["states"][1]["edit_delta"] = -0.25
        before = manifest.build_jobs(self.config)
        after = manifest.build_jobs(changed)
        for old, new in zip(before, after):
            if old["state_id"] == "nose_alar_width_narrower":
                self.assertNotEqual(old["job_id"], new["job_id"])
                self.assertEqual(old["baseline_job_id"], new["baseline_job_id"])
            else:
                self.assertEqual(old["job_id"], new["job_id"])

    def test_zero_edit_is_deduplicated_across_edits(self):
        jobs = manifest.build_jobs(self.config)
        originals = [job for job in jobs if job["state_id"] == "original"]
        control_keys = {(job["character_id"], job["method_id"], job["shot_id"], job["seed"])
                        for job in originals}
        self.assertEqual(len(originals), len(control_keys))
        invalid = deepcopy(self.config)
        invalid["states"][1]["edit_delta"] = 0
        with self.assertRaisesRegex(ValueError, "Zero edits"):
            manifest.build_jobs(invalid)

    def test_duplicate_record_ids_are_rejected(self):
        for key in ("characters", "states", "shots", "methods"):
            with self.subTest(key=key):
                invalid = deepcopy(self.config)
                invalid[key].append(deepcopy(invalid[key][0]))
                with self.assertRaisesRegex(ValueError, "duplicate ID"):
                    manifest.build_jobs(invalid)

    def test_invalid_seeds_are_rejected(self):
        for seeds in ([True], [-1], [1.5], ["42"], [2**63], [42, 42], []):
            with self.subTest(seeds=seeds):
                invalid = deepcopy(self.config)
                invalid["seeds"] = seeds
                with self.assertRaises(ValueError):
                    manifest.build_jobs(invalid)

    def test_non_finite_values_are_rejected_even_in_nested_metadata(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                invalid = deepcopy(self.config)
                invalid["states"][1]["edit_delta"] = value
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    manifest.build_jobs(invalid)
                invalid = deepcopy(self.config)
                invalid["metadata"] = {"nested": [value]}
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    manifest.build_jobs(invalid)

    def test_original_must_be_present_and_unchanged(self):
        missing = deepcopy(self.config)
        missing["states"] = missing["states"][1:]
        with self.assertRaisesRegex(ValueError, "exactly one original"):
            manifest.build_jobs(missing)
        invalid = deepcopy(self.config)
        invalid["states"][0]["edit_delta"] = 0.5
        with self.assertRaisesRegex(ValueError, "original must"):
            manifest.build_jobs(invalid)

    def test_manifest_refuses_implicit_overwrite(self):
        jobs = manifest.build_jobs(self.config)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pilot.jsonl"
            manifest.write_manifest(jobs, output)
            original_bytes = output.read_bytes()
            with self.assertRaises(FileExistsError):
                manifest.write_manifest([], output)
            self.assertEqual(output.read_bytes(), original_bytes)
            manifest.write_manifest(jobs, output, overwrite=True)
            self.assertEqual(output.read_bytes(), original_bytes)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual(rows, jobs)

    def test_json_loader_rejects_nonstandard_numeric_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "invalid.json"
            config_path.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Non-finite"):
                manifest.load_config(config_path)

    def test_dry_run_leaves_existing_manifest_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.jsonl"
            output.write_text("existing experiment record\n", encoding="utf-8")
            captured = io.StringIO()
            with redirect_stdout(captured):
                result = manifest.main(["--dry-run", "--summary", "--output", str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(captured.getvalue())["total_jobs"], 54)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing experiment record\n")


if __name__ == "__main__":
    unittest.main()
