import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.storage import JsonStore, safe_name, sha256


class JsonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = JsonStore(self.root / "data")

    def tearDown(self):
        self.temp.cleanup()

    def video(self, name="clip.mp4", content=b"not-real-video"):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_style_is_saved_with_reference_checksum(self):
        source = self.video()
        style = self.store.create_style("Test style", [source], {str(source): {"duration_seconds": 10}})
        saved = self.store.style(style["style_id"])
        self.assertEqual(saved["label"], "Test style")
        self.assertEqual(saved["reference_files"][0]["sha256"], sha256(source))
        self.assertTrue(self.store.resolve_data_path(saved["reference_files"][0]["stored_path"]).exists())
        self.assertEqual(self.store.style_dir(style["style_id"]).parent, self.store.recipes_dir)
        self.assertFalse(saved["approval"]["approved"])

    def test_permission_backfill_preserves_older_learning_records(self):
        source = self.root / "raw.mp4"
        source.write_bytes(b"raw")
        style = self.store.create_style("Recipe", [], {})
        project = self.store.create_project(
            "Owned project", style["style_id"], "pegasus", "Prompt", 30,
            [source], {str(source): {"duration_seconds": 1}}, device_id="device-a",
        )
        signal = self.store.save_learning_signal(style["style_id"], {
            "source_key": "legacy-signal", "type": "approved_cut",
            "scope": "style_candidate", "project_id": project["project_id"],
        })
        signal_path = self.store.style_dir(style["style_id"]) / "learning" / "signals" / (signal["signal_id"] + ".json")
        example_path = self.store.approved_examples_dir / "example-20260827-abcdef.json"
        self.store.write_json(example_path, {
            "example_id": "example-20260827-abcdef", "project_id": project["project_id"],
            "founder_feedback": {"scores": {"overall": 5}},
        })

        result = self.store.backfill_permission_scopes()

        self.assertEqual(result["signals"], 1)
        self.assertEqual(self.store.read_json(signal_path)["device_id"], "device-a")
        example = self.store.read_json(example_path)
        self.assertEqual(example["device_id"], "device-a")
        self.assertEqual(example["permission_scope"], "device_private")
        self.assertEqual(example["approval_feedback"]["scores"]["overall"], 5)
        self.assertNotIn("founder_feedback", example)

    def test_duplicate_reference_video_uses_one_shared_asset(self):
        source = self.video("same-reference.mp4")
        first = self.store.create_style("First", [source], {})
        second = self.store.create_style("Second", [source], {})
        first_path = self.store.style(first["style_id"])["reference_files"][0]["stored_path"]
        second_path = self.store.style(second["style_id"])["reference_files"][0]["stored_path"]
        self.assertEqual(first_path, second_path)
        self.assertEqual(len(list(self.store.reference_assets_dir.iterdir())), 1)

    def test_project_preserves_provider_and_individual_files(self):
        ref = self.video("reference.mp4")
        style = self.store.create_style("Style", [ref], {})
        recipe = self.store.save_recipe_draft(style["style_id"], {"summary": "Pinned recipe", "rules": []}, "1.0.0")
        self.store.update_style(style["style_id"], recipe=recipe, recipe_version="1.0.0")
        one = self.video("one.mp4", b"one")
        two = self.video("two.mov", b"two")
        project = self.store.create_project("Project", style["style_id"], "pegasus", "Make it quick", 60, [one, two], {})
        saved = self.store.project(project["project_id"])
        self.assertEqual(saved["provider"], "pegasus")
        self.assertEqual(len(saved["raw_files"]), 2)
        self.assertNotEqual(saved["raw_files"][0]["sha256"], saved["raw_files"][1]["sha256"])
        self.assertEqual(saved["recipe_version"], "1.0.0")
        self.assertEqual(self.store.recipe_for_project(saved)["summary"], "Pinned recipe")
        self.store.update_style(style["style_id"], recipe={"summary": "Changed current recipe"})
        self.assertEqual(self.store.recipe_for_project(saved)["summary"], "Pinned recipe")

    def test_project_can_reuse_hashed_staging_file_without_copy_or_reread(self):
        style = self.store.create_style("Staged", [], {})
        staged = self.store.upload_sessions_dir / "upload-20260903-abcdef" / "raw" / "001-clip.mov"
        staged.parent.mkdir(parents=True)
        staged.write_bytes(b"already-streamed")
        checksum = sha256(staged)

        with patch("app.storage.sha256", side_effect=AssertionError("unexpected checksum reread")):
            project = self.store.create_project(
                "Promoted", style["style_id"], "pegasus", "", 30, [staged], {},
                source_checksums={str(staged): checksum}, reuse_staged_files=True,
                source_original_names={str(staged): "clip.mov"},
            )

        promoted = self.store.resolve_data_path(project["raw_files"][0]["stored_path"])
        self.assertEqual(project["raw_files"][0]["sha256"], checksum)
        self.assertEqual(project["raw_files"][0]["original_name"], "clip.mov")
        self.assertEqual(promoted.name, "001-clip.mov")
        self.assertEqual(promoted.read_bytes(), b"already-streamed")
        self.assertEqual(promoted.stat().st_ino, staged.stat().st_ino)

    def test_failed_staged_project_promotion_keeps_source_and_removes_partial_project(self):
        staged = self.root / "staged.mov"
        staged.write_bytes(b"retry-safe")
        before = set(self.store.projects_dir.iterdir())

        with self.assertRaises(FileNotFoundError):
            self.store.create_project(
                "Broken", "style-20260903-ffffff", "pegasus", "", 30, [staged], {},
                source_checksums={str(staged): sha256(staged)}, reuse_staged_files=True,
            )

        self.assertEqual(staged.read_bytes(), b"retry-safe")
        self.assertEqual(set(self.store.projects_dir.iterdir()), before)

    def test_concurrent_project_updates_preserve_independent_fields(self):
        style = self.store.create_style("Concurrent", [], {})
        project = self.store.create_project("Project", style["style_id"], "pegasus", "", 30, [], {})

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(
                lambda index: self.store.update_project(project["project_id"], **{"field_%d" % index: index}),
                range(32),
            ))

        saved = self.store.project(project["project_id"])
        self.assertTrue(all(saved["field_%d" % index] == index for index in range(32)))

    def test_analysis_cache_rejects_a_record_with_a_mismatched_embedded_checksum(self):
        checksum = "a" * 64
        identity = {
            "model": "pegasus-1.2", "prompt_version": "raw-footage-v1",
            "permission_scope": "device:test-device",
        }
        path = self.store.save_cached_analysis(
            "pegasus", "raw_footage", checksum, identity,
            {"provider": "pegasus", "file_id": "raw-001", "usage": {}},
        )
        record = self.store.read_json(path)
        record["source_sha256"] = "b" * 64
        self.store.write_json(path, record)

        cached = self.store.cached_analysis(
            "pegasus", "raw_footage", checksum, identity, "raw-002",
        )

        self.assertIsNone(cached)

        path.write_text("[]")
        self.assertIsNone(self.store.cached_analysis(
            "pegasus", "raw_footage", checksum, identity, "raw-002",
        ))

    def test_atomic_project_transition_admits_only_one_competing_job(self):
        style = self.store.create_style("Admission", [], {})
        project = self.store.create_project("Project", style["style_id"], "pegasus", "", 30, [], {})

        def claim(_index):
            try:
                self.store.transition_project(
                    project["project_id"], reject_statuses={"timeline_queued"},
                    status="timeline_queued",
                )
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(claim, range(16)))

        self.assertEqual(outcomes.count(True), 1)
        self.assertEqual(self.store.project(project["project_id"])["status"], "timeline_queued")

    def test_approved_recipe_version_is_frozen(self):
        source = self.video("versioned-reference.mp4")
        style = self.store.create_style("Versioned", [source], {})
        recipe = self.store.save_recipe_draft(style["style_id"], {"summary": "Version one", "rules": []}, "1.0.0")
        self.store.update_style(style["style_id"], recipe=recipe, recipe_version="1.0.0", recipe_status="testing")
        approved = self.store.approve_recipe_version(style["style_id"])
        self.assertEqual(approved["recipe_status"], "validated")
        self.store.update_style(style["style_id"], recipe={"summary": "A later draft", "rules": []})
        self.assertEqual(self.store.recipe_version(style["style_id"], "1.0.0")["summary"], "Version one")

    def test_json_writes_are_valid_and_safe_names_are_sanitized(self):
        path = self.root / "value.json"
        self.store.write_json(path, {"ok": True})
        self.assertEqual(json.loads(path.read_text()), {"ok": True})
        self.assertEqual(safe_name("../../My Clip (1).mp4"), "My-Clip-1-.mp4")

    def test_remote_asset_inventory_retains_audit_record_after_deletion(self):
        source = self.video()
        style = self.store.create_style("Style", [source], {})
        self.store.record_remote_asset(self.store.style_dir(style["style_id"]), "pegasus", "reference-001", {"id": "assets/abc123", "status": "ready", "retained": True})
        inventory = self.store.remote_assets()
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["owner_id"], style["style_id"])
        deleted = self.store.mark_remote_asset_deleted("style", style["style_id"], "pegasus", "assets/abc123")
        self.assertFalse(deleted["retained"])
        self.assertEqual(self.store.remote_assets()[0]["status"], "deleted")

    def test_delete_style_moves_folder_to_recoverable_archive(self):
        source = self.video("delete-me.mp4")
        style = self.store.create_style("To delete", [source], {})
        reference_path = self.store.resolve_data_path(style["reference_files"][0]["stored_path"])
        archived = self.store.delete_style(style["style_id"])
        self.assertFalse((self.store.styles_dir / style["style_id"]).exists())
        self.assertTrue(archived.exists())
        self.assertTrue(reference_path.exists())

    def test_approved_run_creates_local_learning_example(self):
        reference = self.video("reference-approved.mp4")
        style = self.store.create_style("Approved style", [reference], {})
        self.store.update_style(style["style_id"], style_analysis={"summary": "Fast cuts"})
        raw = self.video("approved-raw.mp4")
        project = self.store.create_project("Approved project", style["style_id"], "pegasus", "Make a short", 60, [raw], {})
        plan_path = self.store.project_dir(project["project_id"]) / "runs" / "run-test" / "edit_plan.json"
        self.store.write_json(plan_path, {"video_segments": [], "audio_segments": []})
        run = {"run_id": "run-test", "revision_number": 1, "plan_path": str(plan_path.relative_to(self.store.data_dir)), "feedback": None}
        self.store.update_project(project["project_id"], runs=[run], latest_run=run, content_map={"all_segments": []})
        record = self.store.approve_project_run(project["project_id"], "run-test", {"scores": {"overall": 5}})
        self.assertEqual(record["approved_plan"]["video_segments"], [])
        self.assertEqual(record["schema_version"], "3.0")
        self.assertIsNone(record["approved_render_receipt"])
        self.assertEqual(self.store.project(project["project_id"])["status"], "approved")
        self.assertEqual(len(self.store.list_approved_examples()), 1)
        evaluations = list((self.store.style_dir(style["style_id"]) / "evaluations").glob("*.json"))
        self.assertEqual(len(evaluations), 1)
        evaluation = self.store.read_json(evaluations[0])
        self.assertTrue(evaluation["first_cut_approved"])
        self.assertEqual(evaluation["learning_status"], "candidate_signal_saved")
        self.assertTrue(self.store.list_learning_signals(style["style_id"]))
        self.assertFalse(evaluation["applied_to_recipe"])


if __name__ == "__main__":
    unittest.main()
