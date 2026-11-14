"""Persistence checks independent of any face model or GPU package."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from character_studio.storage import CharacterNotFound, CharacterStore, StorageError


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "characters"
        self.store = CharacterStore(self.root)
        self.values = dict(name="林 · 测试角色", nose_width=-0.35,
                           geometry_hash=hashlib.sha256(b"geometry-v1").hexdigest(),
                           base_asset_id="licensed-head-v1", topology_id="head-topology-v1",
                           mesh_vertices=[[0.0, 0.1, 0.2], [-0.3, 0.4, 0.5], [0.3, 0.4, 0.5]])

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_and_fresh_store_reload_preserve_exact_parameters_and_vertices(self):
        saved = self.store.save(**self.values)
        fresh = CharacterStore(self.root)
        self.assertEqual(fresh.load(saved["id"]), saved)
        snapshot = fresh.load_snapshot(saved["id"])
        self.assertEqual(snapshot["mesh_vertices"], self.values["mesh_vertices"])
        self.assertEqual(snapshot["nose_width"], self.values["nose_width"])
        self.assertEqual(snapshot["geometry_hash"], self.values["geometry_hash"])
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(fresh.list(), [saved])

    def test_revision_save_never_overwrites_original(self):
        first = self.store.save(**self.values)
        original_path = self.root / first["id"] / "revisions/000001.json"
        original_bytes = original_path.read_bytes()
        second = self.store.save(**{**self.values, "nose_width": 0.6}, character_id=first["id"])
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["parent_revision"], 1)
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertEqual(original_bytes, original_path.read_bytes())
        self.assertEqual(self.store.load(first["id"], revision=1), first)
        self.assertEqual(self.store.load(first["id"]), second)

    def test_bad_ids_and_revisions_do_not_escape_root(self):
        first = self.store.save(**self.values)
        for bad in ("../other", "/tmp/other", "a/b", "", ".", "..", "a\\b", None):
            with self.subTest(bad=bad), self.assertRaises(StorageError):
                self.store.load(bad)
        for bad in (0, -1, True, "1", 1.2):
            with self.subTest(revision=bad), self.assertRaises(StorageError):
                self.store.load(first["id"], revision=bad)
        with self.assertRaises(CharacterNotFound):
            self.store.load(first["id"], revision=42)

    def test_invalid_inputs_fail_before_any_character_is_written(self):
        cases = [dict(nose_width=value) for value in (float("nan"), float("inf"), -1.01, 1.01, True, "0")]
        cases += [dict(name=""), dict(name="bad\nname"), dict(geometry_hash="not-a-hash"),
                  dict(base_asset_id=""), dict(topology_id="bad/id"),
                  dict(mesh_vertices=[[0, float("nan"), 0]]), dict(mesh_vertices=[[1, 2]]),
                  dict(mesh_vertices=[])]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(StorageError):
                self.store.save(**{**self.values, **case})
        self.assertEqual(self.store.list(), [])

    def test_corrupt_current_revision_is_not_silently_omitted(self):
        saved = self.store.save(**self.values)
        revision = self.root / saved["id"] / "revisions/000001.json"
        revision.write_text("{broken", encoding="utf-8")
        with self.assertRaises(StorageError):
            self.store.load(saved["id"])
        with self.assertRaises(StorageError):
            self.store.list()

    def test_vertex_snapshot_corruption_is_detected(self):
        saved = self.store.save(**self.values)
        path = self.root / saved["id"] / "revisions/000001.json"
        content = json.loads(path.read_text())
        content["mesh_vertices"][0][0] = 12.5
        path.write_text(json.dumps(content), encoding="utf-8")
        with self.assertRaisesRegex(StorageError, "checksum"):
            CharacterStore(self.root).load_snapshot(saved["id"])

    def test_missing_and_wrong_manifest_identity_are_reported(self):
        with self.assertRaises(CharacterNotFound):
            self.store.load("missing")
        saved = self.store.save(**self.values)
        path = self.root / saved["id"] / "manifest.json"
        content = json.loads(path.read_text())
        content["id"] = "another"
        path.write_text(json.dumps(content), encoding="utf-8")
        with self.assertRaisesRegex(StorageError, "identity"):
            self.store.load(saved["id"])

    def test_mesh_return_values_cannot_mutate_disk_or_next_load(self):
        vertices = self.values["mesh_vertices"]
        saved = self.store.save(**self.values)
        vertices[0][0] = 99
        loaded = self.store.load_snapshot(saved["id"])
        self.assertEqual(loaded["mesh_vertices"][0][0], 0)
        loaded["mesh_vertices"][0][0] = -99
        self.assertEqual(self.store.load_snapshot(saved["id"])["mesh_vertices"][0][0], 0)

    def test_parallel_saves_across_instances_have_unique_revisions(self):
        first = self.store.save(**self.values)
        def append(index):
            return CharacterStore(self.root).save(**{**self.values, "nose_width": index / 20},
                                                  character_id=first["id"])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(append, range(8)))
        self.assertEqual(sorted(item["revision"] for item in results), list(range(2, 10)))
        self.assertEqual(self.store.load(first["id"])["revision"], 9)
        self.assertEqual(len(list((self.root / first["id"] / "revisions").glob("*.json"))), 9)

    def test_symlinked_character_or_revision_is_rejected(self):
        def create_symlink(path, target, *, target_is_directory=False):
            try:
                path.symlink_to(target, target_is_directory=target_is_directory)
            except OSError as exc:
                if sys.platform == "win32" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows user lacks symbolic-link creation privilege (WinError 1314)")
                raise

        saved = self.store.save(**self.values)
        create_symlink(self.root / "outside", self.root / saved["id"], target_is_directory=True)
        with self.assertRaisesRegex(StorageError, "symbolic"):
            self.store.load("outside")
        revision = self.root / saved["id"] / "revisions/000001.json"
        target = self.root.parent / "snapshot.json"
        revision.rename(target)
        create_symlink(revision, target)
        with self.assertRaisesRegex(StorageError, "symbolic"):
            self.store.load(saved["id"])

    def test_asset_or_topology_cannot_change_within_character(self):
        first = self.store.save(**self.values)
        for case in (dict(base_asset_id="new-base"), dict(topology_id="new-topology")):
            with self.subTest(case=case), self.assertRaisesRegex(StorageError, "cannot change"):
                self.store.save(**{**self.values, **case}, character_id=first["id"])
        self.assertEqual(self.store.load(first["id"])["revision"], 1)

    def test_duplicate_json_keys_and_nonfinite_disk_values_are_rejected(self):
        saved = self.store.save(**self.values)
        path = self.root / saved["id"] / "manifest.json"
        path.write_text('{"id":"a","id":"b"}', encoding="utf-8")
        with self.assertRaisesRegex(StorageError, "duplicate"):
            self.store.load(saved["id"])
        path.write_text('{"current_revision":NaN}', encoding="utf-8")
        with self.assertRaisesRegex(StorageError, "non-finite"):
            self.store.load(saved["id"])

    def test_disk_schema_and_revision_types_are_strict(self):
        saved = self.store.save(**self.values)
        path = self.root / saved["id"] / "revisions/000001.json"
        original = json.loads(path.read_text())
        for key, value in (("schema_version", True), ("revision", 1.0)):
            with self.subTest(key=key):
                content = {**original, key: value}
                path.write_text(json.dumps(content), encoding="utf-8")
                with self.assertRaises(StorageError):
                    self.store.load(saved["id"])

    def test_flame_parameters_and_provenance_roundtrip_without_mutable_aliases(self):
        identity, expression = [0.1, -0.2, 0], [0.25, -0.5]
        provenance = {"source_sha256": "a" * 64, "calibration_hash": "b" * 64,
                      "deformation_version": "nasal-v1", "model_variant": "flame2023_open",
                      "coordinate_system": "right_handed_y_up_face_positive_z"}
        saved = self.store.save(**self.values, identity_params=identity,
                                expression_params=expression, asset_metadata=provenance)
        fresh = CharacterStore(self.root).load_snapshot(saved["id"])
        self.assertEqual(fresh["identity_params"], [0.1, -0.2, 0.0])
        self.assertEqual(fresh["expression_params"], [0.25, -0.5])
        self.assertEqual(fresh["asset_metadata"], provenance)
        identity[0], expression[0], provenance["deformation_version"] = 9, 9, "mutated"
        saved["identity_params"][0] = 8
        saved["asset_metadata"]["deformation_version"] = "also-mutated"
        loaded = self.store.load(saved["id"])
        self.assertEqual(loaded["identity_params"][0], 0.1)
        self.assertEqual(loaded["expression_params"][0], 0.25)
        self.assertEqual(loaded["asset_metadata"]["deformation_version"], "nasal-v1")

    def test_legacy_scan_record_gets_defaults_without_rewriting_file(self):
        saved = self.store.save(**self.values)
        path = self.root / saved["id"] / "revisions/000001.json"
        legacy = json.loads(path.read_text())
        for key in ("identity_params", "expression_params", "asset_metadata"):
            legacy.pop(key)
        path.write_text(json.dumps(legacy), encoding="utf-8")
        before = path.read_bytes()
        fresh = CharacterStore(self.root)
        loaded = fresh.load(saved["id"])
        self.assertEqual(loaded["identity_params"], [])
        self.assertEqual(loaded["expression_params"], [])
        self.assertEqual(loaded["asset_metadata"], {})
        self.assertEqual(fresh.load_snapshot(saved["id"])["identity_params"], [])
        self.assertEqual(fresh.list()[0]["asset_metadata"], {})
        self.assertEqual(path.read_bytes(), before)

    def test_parameter_and_provenance_changes_are_versioned_not_inherited_implicitly(self):
        first = self.store.save(**self.values, identity_params=[0.1], expression_params=[0.2],
                                asset_metadata={"model_variant": "flame2023_open"})
        path = self.root / first["id"] / "revisions/000001.json"
        before = path.read_bytes()
        second = self.store.save(**self.values, character_id=first["id"], identity_params=[0.3],
                                 expression_params=[0.4], asset_metadata={"model_variant": "flame2023_open"})
        self.assertEqual(self.store.load(first["id"], revision=1)["identity_params"], [0.1])
        self.assertEqual(self.store.load(first["id"])["expression_params"], [0.4])
        self.assertEqual(path.read_bytes(), before)
        third = self.store.save(**self.values, character_id=first["id"])
        self.assertEqual(third["identity_params"], [])
        self.assertEqual(third["expression_params"], [])
        self.assertEqual(third["asset_metadata"], {})
        self.assertEqual(second["revision"], 2)

    def test_invalid_flame_parameters_are_rejected_before_writing(self):
        for key, maximum in (("identity_params", 300), ("expression_params", 100)):
            for invalid in ([True], [float("nan")], [float("inf")], ["0"], [[0]],
                            [0] * (maximum + 1), (0.1,), {"0": 0.1}, [10 ** 1000]):
                with self.subTest(key=key, value=repr(invalid)[:60]), self.assertRaises(StorageError):
                    self.store.save(**self.values, **{key: invalid})
        for invalid in ({"weights": [1, 2]}, {"model_variant": ["array"]},
                        {"source_sha256": "not-a-hash"}, {"calibration_hash": "A" * 64},
                        {"deformation_version": "bad\nname"}, {"coordinate_system": ""},
                        {"model_variant": 42}, []):
            with self.subTest(metadata=invalid), self.assertRaises(StorageError):
                self.store.save(**self.values, asset_metadata=invalid)
        self.assertEqual(self.store.list(), [])

    def test_malformed_parameters_or_provenance_on_disk_are_rejected(self):
        saved = self.store.save(**self.values)
        path = self.root / saved["id"] / "revisions/000001.json"
        original = json.loads(path.read_text())
        cases = [("identity_params", [True]), ("expression_params", ["0"]),
                 ("identity_params", None), ("identity_params", [0] * 301),
                 ("expression_params", [0] * 101), ("asset_metadata", None),
                 ("asset_metadata", {"weights": [0.1]}),
                 ("asset_metadata", {"source_sha256": "invalid"})]
        for key, value in cases:
            with self.subTest(key=key, value=str(value)[:60]):
                path.write_text(json.dumps({**original, key: value}), encoding="utf-8")
                with self.assertRaises(StorageError):
                    CharacterStore(self.root).load_snapshot(saved["id"])


if __name__ == "__main__":
    unittest.main()
