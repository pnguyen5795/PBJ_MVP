import json
import io
import asyncio
import hashlib
import tempfile
import time
import unittest
import zipfile
from base64 import b64encode
from dataclasses import replace
from pathlib import Path
from threading import Lock
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import app.main as main_module
from app.config import settings
from app.storage import JsonStore
from app.timeline.contracts import empty_timeline, refresh_hash
from app.timeline.storage import TimelineStore


class CanonicalUIFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name))
        style = self.store.create_style("Test recipe", [], {})
        self.store.update_style(
            style["style_id"],
            recipe={"summary": "A clear chronological edit", "rules": []},
            style_analysis={"summary": "A clear chronological edit", "rules": []},
            recipe_version="1.0.0",
            recipe_status="validated",
            approval={"approved": True, "approved_at": "now"},
        )
        project = self.store.create_project(
            "Flow contract", style["style_id"], "pegasus",
            "Make a fast chronological 45 second video.", 45, [], {},
            {"pacing": "fast", "requirements": []},
            {"method": "test", "confidence": 1.0}, None,
        )
        run = {
            "run_id": "run-20260827-abcdef",
            "revision_number": 1,
            "feedback": None,
            "output_path": "projects/%s/runs/run-20260827-abcdef/rough-cut.mp4" % project["project_id"],
        }
        self.project_id = project["project_id"]
        self.store.update_project(self.project_id, status="rough_cut_ready", runs=[run], latest_run=run)
        timeline = empty_timeline(self.project_id, [])
        TimelineStore(self.store).initialize(self.project_id, timeline)
        cuts = []
        for number in (1, 2):
            export_id = "export-flow-%d" % number
            export_root = self.store.project_dir(self.project_id) / "exports" / export_id
            output = export_root / "output.mp4"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(("cut-%d" % number).encode())
            export = {
                "export_id": export_id, "status": "complete",
                "created_at": "2026-09-01T00:00:0%d+00:00" % number,
                "completed_at": "2026-09-01T00:00:1%d+00:00" % number,
                "timeline_path": "projects/%s/timeline/current.json" % self.project_id,
                "output_path": str(output.relative_to(self.store.data_dir)),
            }
            self.store.write_json(export_root / "export.json", export)
            cuts.append(export)
        self.store.update_project(
            self.project_id, status="timeline_ready", latest_export=cuts[-1],
            revision_feedback=[{"feedback": "Make the ending faster", "requested_at": "now"}],
        )
        self.store_patch = patch.object(main_module, "store", self.store)
        self.store_patch.start()
        self.client = TestClient(main_module.app)
        session = {"authorized": True, "owner": True, "device_id": "test-device"}
        signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("session", signed)

    def set_session(self, owner: bool, device_id: str = "test-device"):
        session = {"authorized": True, "owner": owner, "device_id": device_id}
        signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("session", signed)

    def tearDown(self):
        self.client.close()
        self.store_patch.stop()
        self.temp.cleanup()

    def test_rough_cut_ready_shows_video_approval_and_revision(self):
        response = self.client.get("/projects/%s/ready" % self.project_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your revised cut is ready", response.text)
        self.assertIn("REVISED CUT READY · CUT 2", response.text)
        self.assertIn("applied your feedback", response.text)
        self.assertIn("Approve this cut", response.text)
        self.assertIn("Request changes", response.text)
        self.assertIn("<video", response.text)
        self.assertNotIn("openreel", response.text.casefold())
        self.assertNotIn("/static/editor/", response.text)
        self.assertIn("Compare with earlier cuts", response.text)
        self.assertIn("Download analysis data", response.text)

        removed = self.client.get("/projects/%s/openreel" % self.project_id)
        self.assertEqual(removed.status_code, 404)

    def test_project_analysis_data_download_contains_saved_json(self):
        analysis = self.store.project_dir(self.project_id) / "analyses" / "pegasus" / "raw-001.json"
        self.store.write_json(analysis, {"file_id": "raw-001", "analysis": {"segments": []}})
        self.store.write_json(self.store.project_dir(self.project_id) / "content_map.json", {"all_segments": []})

        response = self.client.get("/projects/%s/analysis-data/download" % self.project_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(
                set(archive.namelist()),
                {"footage/pegasus/raw-001.json", "content-map.json", "package-manifest.json"},
            )
            saved = json.loads(archive.read("footage/pegasus/raw-001.json"))
            self.assertEqual(saved["file_id"], "raw-001")

    def test_read_only_analysis_results_show_timestamped_findings(self):
        project = self.store.project(self.project_id)
        project["raw_files"] = [{"file_id": "raw-001", "original_name": "Golf swing.mov"}]
        self.store.write_json(self.store.project_dir(self.project_id) / "manifest.json", project)
        self.store.write_json(
            self.store.project_dir(self.project_id) / "analyses" / "pegasus" / "raw-001.json",
            {
                "file_id": "raw-001", "model": "pegasus1.5", "duration_seconds": 12.0,
                "analysis": {
                    "summary": "A golfer completes a drive.",
                    "story_beats": ["Setup", "Swing"],
                    "segments": [{
                        "start_seconds": 2.0, "end_seconds": 6.5,
                        "visual_description": "The golfer swings and follows through.",
                        "transcript": "Great shot", "audio_description": "Club impact",
                        "editorial_roles": ["primary action"], "shot_type": "Medium shot",
                        "emotional_tone": "Focused", "quality": "strong",
                    }],
                },
            },
        )
        response = self.client.get("/projects/%s/analysis-results" % self.project_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("What PBJ found", response.text)
        self.assertIn("Golf swing.mov", response.text)
        self.assertIn("2.0–6.5s", response.text)
        self.assertIn("The golfer swings and follows through.", response.text)
        self.assertIn("Great shot", response.text)
        self.assertNotIn('name="provider"', response.text)

    def test_each_completed_cut_has_its_own_playback_page(self):
        history = self.client.get("/projects/%s/cuts" % self.project_id, follow_redirects=False)
        self.assertEqual(history.status_code, 303)
        self.assertIn("/cuts/export-flow-2", history.headers["location"])

        first = self.client.get("/projects/%s/cuts/export-flow-1" % self.project_id)
        second = self.client.get("/projects/%s/cuts/export-flow-2" % self.project_id)
        self.assertIn("EARLIER ROUGH CUT", first.text)
        self.assertIn("CURRENT FINAL CUT", second.text)
        self.assertIn("exports/export-flow-1/download", first.text)
        self.assertIn("exports/export-flow-2/download", second.text)
        self.assertIn("Original creative brief", first.text)
        self.assertIn("Next cut", first.text)
        self.assertIn("Revision prompt for Cut 2", second.text)
        self.assertIn("Make the ending faster", second.text)
        self.assertIn("Previous cut", second.text)

    def test_legacy_review_and_revision_redirect_to_ready(self):
        for suffix in ("review", "revision"):
            response = self.client.get("/projects/%s/%s" % (self.project_id, suffix), follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertIn("/projects/%s/ready" % self.project_id, response.headers["location"])

    def test_legacy_approval_redirects_to_ready(self):
        response = self.client.get("/projects/%s/approval" % self.project_id)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your revised cut is ready", response.text)

    def test_approval_requires_explicit_confirmation(self):
        response = self.client.post(
            "/projects/%s/approve" % self.project_id,
            data={},
        )
        self.assertEqual(response.status_code, 400)

    def test_approval_rejects_an_active_job_without_changing_its_state(self):
        self.store.update_project(
            self.project_id, status="exporting", active_export_id="export-active",
            active_task="Rendering the current cut", job_return_status="timeline_ready",
        )

        response = self.client.post(
            "/projects/%s/approve" % self.project_id,
            data={"confirmation": "approve"},
        )

        self.assertEqual(response.status_code, 409)
        saved = self.store.project(self.project_id)
        self.assertEqual(saved["status"], "exporting")
        self.assertEqual(saved["active_export_id"], "export-active")
        self.assertEqual(saved["active_task"], "Rendering the current cut")

    def test_approval_rejects_a_cut_from_an_older_timeline(self):
        project = self.store.project(self.project_id)
        export = dict(project["latest_export"])
        old_timeline = TimelineStore(self.store).load(self.project_id)
        snapshot_path = (
            self.store.project_dir(self.project_id) / "exports" /
            export["export_id"] / "timeline.json"
        )
        self.store.write_json(snapshot_path, old_timeline)
        export["timeline_path"] = str(snapshot_path.relative_to(self.store.data_dir))
        self.store.update_project(self.project_id, latest_export=export)
        revised = json.loads(json.dumps(old_timeline))
        revised["metadata"]["origin"] = "revision_feedback"
        refresh_hash(revised)
        TimelineStore(self.store).replace_with_ai_revision(
            self.project_id, revised, "Use the newer edit",
        )

        response = self.client.post(
            "/projects/%s/approve" % self.project_id,
            data={"confirmation": "approve"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("not the current saved edit", response.text)
        self.assertFalse(self.store.project(self.project_id).get("final_approval"))

    def test_repeated_approval_is_idempotent(self):
        project = self.store.project(self.project_id)
        export = dict(project["latest_export"])
        receipt_path = self.store.project_dir(self.project_id) / "exports" / export["export_id"] / "render_receipt.json"
        self.store.write_json(receipt_path, {"verification": {"passed": True}})
        export["render_receipt_path"] = str(receipt_path.relative_to(self.store.data_dir))
        self.store.write_json(
            self.store.project_dir(self.project_id) / "exports" / export["export_id"] / "export.json",
            export,
        )
        self.store.update_project(self.project_id, latest_export=export, status="timeline_ready")

        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            first = self.client.post(
                "/projects/%s/approve" % self.project_id, data={"confirmation": "approve"},
            )
            second = self.client.post(
                "/projects/%s/approve" % self.project_id, data={"confirmation": "approve"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        evaluations = list((self.store.style_dir(project["style_id"]) / "evaluations").glob("*.json"))
        self.assertEqual(len(evaluations), 1)

    def test_revision_rejects_duplicate_active_job(self):
        self.store.update_project(self.project_id, status="timeline_queued")

        response = self.client.post(
            "/projects/%s/revise" % self.project_id,
            data={"feedback": "Make the ending tighter"},
        )

        self.assertEqual(response.status_code, 409)

    def test_processing_copy_distinguishes_timeline_stages(self):
        self.store.update_project(self.project_id, status="planning_timeline")
        response = self.client.get("/projects/%s/production-progress" % self.project_id)
        self.assertIn("CREATING YOUR ROUGH CUT", response.text)
        self.assertIn("Building and validating the story", response.text)
        self.assertIn("Rendering the video", response.text)

    def test_failed_newer_edit_does_not_hide_behind_the_last_completed_cut(self):
        for failed_status in ("timeline_failed", "export_failed"):
            with self.subTest(status=failed_status):
                self.store.update_project(
                    self.project_id, status=failed_status,
                    last_error="The newer edit stopped safely.",
                )
                routed = self.client.get(
                    "/projects/%s" % self.project_id, follow_redirects=False,
                )
                self.assertEqual(routed.status_code, 303)
                self.assertEqual(
                    routed.headers["location"],
                    "/projects/%s/production-progress" % self.project_id,
                )
                failure = self.client.get(
                    "/projects/%s/production-progress" % self.project_id,
                )
                self.assertIn("The newer edit stopped safely.", failure.text)
                self.assertIn("View last completed cut", failure.text)

                prior_cut = self.client.get(
                    "/projects/%s/ready" % self.project_id,
                )
                self.assertIn("LAST COMPLETED CUT", prior_cut.text)
                self.assertIn("newer edit did not finish", prior_cut.text)
                self.assertIn("Return to the failed edit", prior_cut.text)
                self.assertNotIn("Approve this cut", prior_cut.text)
                self.assertNotIn("Request changes", prior_cut.text)

    def test_ready_page_hides_actions_while_a_timeline_task_is_active(self):
        self.store.update_project(
            self.project_id, status="approval_running",
            active_task="Saving your approved cut",
            job_return_status="timeline_ready",
        )

        response = self.client.get("/projects/%s/ready" % self.project_id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Saving your approved cut", response.text)
        self.assertNotIn("Approve this cut", response.text)
        self.assertNotIn("Request changes", response.text)

    def test_restart_marks_interrupted_job_as_retryable(self):
        self.store.update_project(
            self.project_id, status="planning_timeline", active_revision=1,
            active_task="Planning the cut",
        )
        main_module.recover_interrupted_jobs()
        recovered = self.store.project(self.project_id)
        self.assertEqual(recovered["status"], "timeline_failed")
        self.assertIsNone(recovered["active_revision"])
        self.assertIn("interrupted", recovered["last_error"].lower())

    def test_restart_returns_interrupted_approval_to_its_saved_timeline(self):
        self.store.update_project(
            self.project_id, status="approval_running", job_return_status="timeline_ready",
            active_task="Saving your approved cut",
        )

        main_module.recover_interrupted_jobs()

        recovered = self.store.project(self.project_id)
        self.assertEqual(recovered["status"], "timeline_ready")
        self.assertIsNone(recovered["job_return_status"])
        self.assertIsNone(recovered["active_task"])
        self.assertIn("interrupted", recovered["last_error"].lower())

    def test_restart_reopens_upload_interrupted_during_inspection(self):
        upload = self.store.create_upload_session(
            "Interrupted inspection", self.store.list_styles()[0]["style_id"],
            "pegasus", "Make a short edit", 20, device_id="test-device",
        )
        self.store.update_upload_session(upload["session_id"], status="inspecting")

        main_module.recover_interrupted_jobs()

        recovered = self.store.upload_session(upload["session_id"])
        self.assertEqual(recovered["status"], "uploading")
        self.assertTrue(recovered["inspection_interrupted_at"])

    def test_restart_recovers_interrupted_recipe_and_project_promotion(self):
        style = self.store.list_styles()[0]
        self.store.update_style(style["style_id"], status="analysis_queued")
        upload = self.store.create_upload_session(
            "Promotion recovery", style["style_id"], "pegasus", "Make a cut", 20,
            device_id="test-device",
        )
        project_id = "project-20260903-fedcba"
        project_dir = self.store.project_dir(project_id)
        staged_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        staged_dir.mkdir(parents=True)
        staged = staged_dir / "001-private.mov"
        staged.write_bytes(b"private-media")
        promoted = project_dir / "raw" / "001-private.mov"
        promoted.parent.mkdir(parents=True)
        promoted.hardlink_to(staged)
        self.store.write_json(project_dir / "manifest.json", {
            "project_id": project_id, "style_id": style["style_id"],
            "status": "analysis_queued", "raw_files": [{
                "file_id": "raw-001", "original_name": "private.mov",
                "stored_path": str(promoted.relative_to(self.store.data_dir)),
            }], "runs": [],
            "promotion_initialized": True,
        })
        self.store.update_upload_session(
            upload["session_id"], status="promoting", project_id=project_id,
            files=[{"original_name": "private.mov", "stored_path": str(staged.relative_to(self.store.data_dir))}],
            inspection_metadata={str(staged): {"duration_seconds": 10}},
        )

        main_module.recover_interrupted_jobs()

        self.assertEqual(self.store.style(style["style_id"])["status"], "analysis_failed")
        recovered = self.store.upload_session(upload["session_id"])
        self.assertEqual(recovered["status"], "promoted")
        self.assertEqual(recovered["files"], [])
        self.assertEqual(recovered["inspection_metadata"], {})
        self.assertEqual(recovered["name"], "")
        self.assertEqual(recovered["style_id"], "")
        self.assertEqual(recovered["provider"], "")
        self.assertEqual(recovered["prompt"], "")
        self.assertIsNone(recovered["intent_interpretation"])
        self.assertIsNone(recovered["recipe_match"])
        self.assertEqual(recovered["target_duration_seconds"], 0)
        self.assertIsNone(recovered["draft_id"])
        self.assertFalse(staged_dir.exists())
        self.assertEqual(promoted.read_bytes(), b"private-media")

    def test_restart_removes_incomplete_promotion_but_keeps_retryable_staging(self):
        style = self.store.list_styles()[0]
        upload = self.store.create_upload_session(
            "Incomplete promotion", style["style_id"], "pegasus", "Make a cut", 20,
            device_id="test-device",
        )
        staged_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        staged_dir.mkdir(parents=True)
        staged = staged_dir / "001-clip.mov"
        staged.write_bytes(b"retryable-media")
        project_id = "project-20260903-badbad"
        project_dir = self.store.project_dir(project_id)
        project_dir.mkdir(parents=True)
        self.store.write_json(project_dir / "manifest.json", {
            "project_id": project_id, "style_id": style["style_id"],
            "status": "footage_uploaded", "raw_files": [], "runs": [],
        })
        self.store.update_upload_session(
            upload["session_id"], status="promoting", project_id=project_id,
            files=[{"original_name": "clip.mov", "stored_path": str(staged.relative_to(self.store.data_dir))}],
        )

        main_module.recover_interrupted_jobs()

        recovered = self.store.upload_session(upload["session_id"])
        self.assertEqual(recovered["status"], "ready_for_brief")
        self.assertIsNone(recovered["project_id"])
        self.assertEqual(staged.read_bytes(), b"retryable-media")
        self.assertFalse(project_dir.exists())

    def test_restart_does_not_rewrite_an_already_scrubbed_promoted_session(self):
        upload = self.store.create_upload_session(
            "Completed promotion", self.store.list_styles()[0]["style_id"],
            "pegasus", "Make a cut", 20, device_id="test-device",
        )
        completed = self.store.update_upload_session(
            upload["session_id"], status="promoted", project_id=self.project_id,
            files=[], inspection_metadata={}, name="", style_id="", provider="",
            prompt="", intent_interpretation=None, recipe_match=None,
            target_duration_seconds=0, total_duration_seconds=0, draft_id=None,
        )

        main_module.recover_interrupted_jobs()

        recovered = self.store.upload_session(upload["session_id"])
        self.assertEqual(recovered["updated_at"], completed["updated_at"])

    def test_timeline_job_failure_does_not_persist_raw_exception_text(self):
        self.store.update_project(
            self.project_id, status="approval_running", job_return_status="timeline_ready",
        )

        main_module.fail_timeline_job(
            self.store, self.project_id,
            RuntimeError("private.mov access-code-123 private creative prompt"),
        )

        saved = self.store.project(self.project_id)
        serialized = json.dumps(saved)
        self.assertEqual(saved["last_error_details"]["code"], "timeline_task_failed")
        for forbidden in ("private.mov", "access-code-123", "private creative prompt"):
            self.assertNotIn(forbidden, serialized)

    def test_retired_analyzer_first_pages_only_redirect(self):
        for suffix in ("analysis", "analysis-progress", "analysis-review", "rough-cut", "rough-cut-progress"):
            response = self.client.get("/projects/%s/%s" % (self.project_id, suffix), follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertNotIn("text/html", response.headers.get("content-type", ""))

    def test_retired_flow_templates_do_not_return(self):
        templates_dir = settings.templates_dir
        retired = (
            "project_new.html", "project_start.html", "project_saved_style.html",
            "project_detail.html", "project_analysis.html", "project_analysis_progress.html",
            "project_analysis_review.html", "project_rough_cut.html",
            "project_rough_cut_progress.html", "project_review.html",
            "project_revision.html", "project_approval.html", "style_detail.html",
        )
        self.assertFalse([name for name in retired if (templates_dir / name).exists()])

    def test_retired_mutation_and_comparison_endpoints_are_removed(self):
        for suffix in ("analyze", "provider", "rough-cut", "compare"):
            response = self.client.post("/projects/%s/%s" % (self.project_id, suffix))
            self.assertIn(response.status_code, (404, 405))

    def test_shared_recipe_approval_requires_owner_access(self):
        candidate = self.store.create_style("Community candidate", [], {})
        self.store.update_style(
            candidate["style_id"], recipe={"summary": "Candidate", "rules": []},
            recipe_version="1.0.0", recipe_status="testing",
        )
        self.set_session(owner=False)
        response = self.client.post("/styles/%s/approve" % candidate["style_id"])
        self.assertEqual(response.status_code, 403)

    def test_active_project_and_recipe_cannot_be_deleted_mid_job(self):
        self.store.update_project(self.project_id, status="exporting")
        project_response = self.client.post("/projects/%s/delete" % self.project_id)
        self.assertEqual(project_response.status_code, 409)
        self.assertEqual(self.store.project(self.project_id)["status"], "exporting")

        style = self.store.create_style("Busy recipe", [], {})
        self.store.update_style(style["style_id"], status="analyzing_references")
        style_response = self.client.post("/styles/%s/delete" % style["style_id"])
        self.assertEqual(style_response.status_code, 409)
        self.assertEqual(self.store.style(style["style_id"])["status"], "analyzing_references")

    def test_project_private_recipe_is_isolated_to_its_device(self):
        private = self.store.create_style("Private references", [], {})
        self.store.update_style(private["style_id"], project_private=True, device_id="first-device")
        local_without_access_code = replace(settings, access_code="")
        with patch.object(main_module, "settings", local_without_access_code):
            self.set_session(owner=False, device_id="second-device")
            response = self.client.get("/styles/%s" % private["style_id"])
            self.assertEqual(response.status_code, 404)

            # Owner governance applies to shared recipes, not another device's
            # project-private reference recipe.
            self.set_session(owner=True, device_id="second-device")
            response = self.client.get("/styles/%s" % private["style_id"])
            self.assertEqual(response.status_code, 404)

    def test_hosted_shared_workspace_uses_one_private_identity(self):
        hosted = replace(
            settings, hosted_mode=True, shared_workspace=True,
            shared_workspace_id="pbj-private-workspace",
        )
        self.store.update_project(self.project_id, device_id="pbj-private-workspace")
        with patch.object(main_module, "settings", hosted):
            self.set_session(owner=False, device_id="different-browser")
            response = self.client.get("/projects/%s/ready" % self.project_id)
        self.assertEqual(response.status_code, 200)

    def test_hosted_workspace_does_not_accept_secrets_in_the_app(self):
        hosted = replace(settings, hosted_mode=True)
        with patch.object(main_module, "settings", hosted):
            response = self.client.post("/settings", data={"openai_key": "not-saved"})
        self.assertEqual(response.status_code, 403)

    def test_normal_project_flow_does_not_expose_analyzer_selection(self):
        self.client.cookies.clear()
        session = {
            "authorized": True,
            "owner": True,
            "device_id": "test-device",
            "project_draft": {
                "name": "Hidden analyzer",
                "description": "Make a clean chronological edit.",
                "style_id": self.store.list_styles()[0]["style_id"],
            },
        }
        signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("session", signed)
        response = self.client.get("/projects/new/footage")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="provider"', response.text)

    def test_interrupted_upload_session_reopens_with_completed_files(self):
        style_id = self.store.list_styles()[0]["style_id"]
        upload = self.store.create_upload_session(
            "Resume test", style_id, "pegasus", "Make a short edit", 20,
            device_id="test-device",
        )
        raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        saved = raw_dir / "001-saved.mov"
        saved.write_bytes(b"saved-video")
        self.store.update_upload_session(upload["session_id"], files=[{
            "file_id": "raw-001", "original_name": "saved.mov",
            "stored_path": str(saved.relative_to(self.store.data_dir)),
            "size_bytes": saved.stat().st_size,
        }])
        session = {
            "authorized": True, "owner": True, "device_id": "test-device",
            "active_upload_session_id": upload["session_id"],
            "project_draft": {"name": "Resume test", "description": "Make a short edit", "style_id": style_id},
        }
        signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("session", signed)

        response = self.client.get("/projects/new/footage")

        self.assertEqual(response.status_code, 200)
        self.assertIn("1 video saved", response.text)
        self.assertIn("Choose the remaining videos", response.text)
        self.assertIn('data-session-id="%s"' % upload["session_id"], response.text)
        self.assertIn("request.send(file)", response.text)
        self.assertIn("X-PBJ-Filename", response.text)
        self.assertIn("if(error.retryable", response.text)
        self.assertNotIn("body.append('footage'", response.text)

    def test_upload_resume_requires_the_exact_project_draft(self):
        original_style_id = self.store.list_styles()[0]["style_id"]
        other_style = self.store.create_style("Other recipe", [], {})
        self.store.update_style(
            other_style["style_id"],
            recipe={"summary": "Another direction", "rules": []},
            style_analysis={"summary": "Another direction", "rules": []},
            recipe_version="1.0.0", recipe_status="validated",
            approval={"approved": True, "approved_at": "now"},
        )
        mismatches = (
            ("Different name", "Make a short edit", original_style_id),
            ("Resume test", "Make a completely different edit", original_style_id),
            ("Resume test", "Make a short edit", other_style["style_id"]),
        )
        for name, prompt, draft_style_id in mismatches:
            with self.subTest(name=name, prompt=prompt, style_id=draft_style_id):
                self.client.cookies.clear()
                upload = self.store.create_upload_session(
                    "Resume test", original_style_id, "pegasus", "Make a short edit", 20,
                    device_id="test-device",
                )
                session = {
                    "authorized": True, "owner": True, "device_id": "test-device",
                    "active_upload_session_id": upload["session_id"],
                    "project_draft": {
                        "name": name, "description": prompt, "style_id": draft_style_id,
                    },
                }
                signed = TimestampSigner(settings.session_secret).sign(
                    b64encode(json.dumps(session).encode())
                ).decode()
                self.client.cookies.set("session", signed)

                response = self.client.get("/projects/new/footage")

                self.assertEqual(response.status_code, 200)
                self.assertNotIn('data-session-id="%s"' % upload["session_id"], response.text)
                # Changing the draft back to a match must not revive the stale
                # pointer; the first request cleared it from the browser session.
                self.client.post(
                    "/projects/new/describe",
                    data={"name": "Resume test", "description": "Make a short edit"},
                    follow_redirects=False,
                )
                revisited = self.client.get("/projects/new/footage")
                self.assertNotIn('data-session-id="%s"' % upload["session_id"], revisited.text)

        self.client.cookies.clear()
        upload = self.store.create_upload_session(
            "Resume test", original_style_id, "pegasus", "Make a short edit", 20,
            device_id="test-device", draft_id="draft-old",
        )
        session = {
            "authorized": True, "owner": True, "device_id": "test-device",
            "active_upload_session_id": upload["session_id"],
            "project_draft": {
                "draft_id": "draft-new", "name": "Resume test",
                "description": "Make a short edit", "style_id": original_style_id,
            },
        }
        signed = TimestampSigner(settings.session_secret).sign(
            b64encode(json.dumps(session).encode())
        ).decode()
        self.client.cookies.set("session", signed)
        response = self.client.get("/projects/new/footage")
        self.assertNotIn('data-session-id="%s"' % upload["session_id"], response.text)

    def test_new_project_action_rotates_draft_identity_even_for_the_same_brief(self):
        old_draft_id = "draft-old"
        upload = self.store.create_upload_session(
            "New Project", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device", draft_id=old_draft_id,
        )
        session = {
            "authorized": True, "owner": True, "device_id": "test-device",
            "active_upload_session_id": upload["session_id"],
            "project_draft": {
                "draft_id": old_draft_id, "name": "New Project",
                "description": "Make a short edit", "style_id": "",
            },
        }
        signed = TimestampSigner(settings.session_secret).sign(
            b64encode(json.dumps(session).encode())
        ).decode()
        self.client.cookies.set("session", signed)

        fresh = self.client.post("/projects/new/fresh", follow_redirects=False)
        self.assertEqual(fresh.status_code, 303)
        self.assertEqual(fresh.headers["location"], "/projects/new")
        describe = self.client.get("/projects/new")
        self.assertNotIn("Make a short edit", describe.text)
        self.client.post(
            "/projects/new/describe",
            data={"name": "New Project", "description": "Make a short edit"},
            follow_redirects=False,
        )
        created = self.client.post("/projects/upload-session", data={
            "name": "New Project", "prompt": "Make a short edit", "style_id": "",
        })

        self.assertEqual(created.status_code, 200)
        new_session = self.store.upload_session(created.json()["session_id"])
        self.assertNotEqual(new_session["draft_id"], old_draft_id)
        self.assertNotEqual(new_session["session_id"], upload["session_id"])

    def test_new_project_get_cannot_clear_an_existing_draft(self):
        session = {
            "authorized": True, "owner": True, "device_id": "test-device",
            "active_upload_session_id": "upload-kept",
            "project_draft": {
                "draft_id": "draft-kept", "name": "Keep me",
                "description": "Keep this saved brief", "style_id": "",
            },
        }
        signed = TimestampSigner(settings.session_secret).sign(
            b64encode(json.dumps(session).encode())
        ).decode()
        self.client.cookies.set("session", signed)

        response = self.client.get(
            "/projects/new?fresh=1",
            headers={"Sec-Fetch-Site": "cross-site"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Keep this saved brief", response.text)

    def test_promoted_upload_pointer_is_cleared_instead_of_reused(self):
        style_id = self.store.list_styles()[0]["style_id"]
        upload = self.store.create_upload_session(
            "Completed draft", style_id, "pegasus", "Make a short edit", 20,
            device_id="test-device",
        )
        self.store.update_upload_session(
            upload["session_id"], status="promoted", project_id=self.project_id,
        )
        session = {
            "authorized": True, "owner": True, "device_id": "test-device",
            "active_upload_session_id": upload["session_id"],
            "project_draft": {
                "name": "Completed draft", "description": "Make a short edit",
                "style_id": style_id,
            },
        }
        signed = TimestampSigner(settings.session_secret).sign(
            b64encode(json.dumps(session).encode())
        ).decode()
        self.client.cookies.set("session", signed)

        response = self.client.get("/projects/new/footage")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('data-session-id="%s"' % upload["session_id"], response.text)
        self.store.update_upload_session(upload["session_id"], status="uploading", project_id=None)
        revisited = self.client.get("/projects/new/footage")
        self.assertNotIn('data-session-id="%s"' % upload["session_id"], revisited.text)

    def test_upload_retry_does_not_duplicate_a_completed_file(self):
        upload = self.store.create_upload_session(
            "Retry test", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        endpoint = "/projects/upload-session/%s/file" % upload["session_id"]
        headers = {"X-PBJ-Filename": "clip.mov", "Content-Type": "video/quicktime"}
        first = self.client.post(endpoint, content=b"video-bytes", headers=headers)
        second = self.client.post(endpoint, content=b"video-bytes", headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["uploaded_files"], 1)
        saved = self.store.upload_session(upload["session_id"])["files"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["sha256"], "79fd615a866fe7f9eb4da8d9c41ab57e3bd48056df42fd2c13e4d461a87afbe3")

    def test_stable_upload_id_retries_without_rewriting_a_full_batch(self):
        upload = self.store.create_upload_session(
            "Retry identity", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        endpoint = "/projects/upload-session/%s/file" % upload["session_id"]
        headers = {
            "X-PBJ-Filename": "clip.mov", "X-PBJ-Upload-ID": "upload-stable-123",
            "Content-Type": "video/quicktime",
        }
        limited = replace(settings, max_upload_batch_bytes=10)

        with patch.object(main_module, "settings", limited):
            first = self.client.post(endpoint, content=b"0123456789", headers=headers)
            retry = self.client.post(endpoint, content=b"0123456789", headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(len(self.store.upload_session(upload["session_id"])["files"]), 1)

    def test_small_network_chunks_are_batched_before_disk_thread_writes(self):
        upload = self.store.create_upload_session(
            "Buffered upload", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        endpoint = "/projects/upload-session/%s/file" % upload["session_id"]
        chunk = b"x" * 4096
        chunk_count = 384
        original_to_thread = asyncio.to_thread
        disk_write_sizes = []

        async def body():
            for _ in range(chunk_count):
                yield chunk

        async def track_to_thread(function, *args, **kwargs):
            if getattr(function, "__name__", "") == "write":
                disk_write_sizes.append(len(args[0]))
            return await original_to_thread(function, *args, **kwargs)

        async def exercise():
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
                cookies={"session": self.client.cookies.get("session")},
            ) as client:
                return await client.post(endpoint, content=body(), headers={
                    "Content-Length": str(len(chunk) * chunk_count),
                    "X-PBJ-Filename": "chunked.mov",
                    "X-PBJ-Upload-ID": "upload-chunked-123",
                })

        with patch.object(main_module.asyncio, "to_thread", side_effect=track_to_thread):
            response = asyncio.run(exercise())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            disk_write_sizes,
            [main_module.UPLOAD_WRITE_BUFFER_BYTES, len(chunk) * 128],
        )
        self.assertLessEqual(max(disk_write_sizes), main_module.UPLOAD_WRITE_BUFFER_BYTES)
        saved = self.store.upload_session(upload["session_id"])["files"][0]
        self.assertEqual(saved["size_bytes"], len(chunk) * chunk_count)
        self.assertEqual(saved["sha256"], hashlib.sha256(chunk * chunk_count).hexdigest())

    def test_upload_reservation_prevents_overcommit_and_early_completion(self):
        upload = self.store.create_upload_session(
            "Reservation", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        endpoint = "/projects/upload-session/%s/file" % upload["session_id"]
        limited = replace(settings, max_upload_batch_bytes=10)

        async def exercise():
            started = asyncio.Event()
            release = asyncio.Event()

            async def slow_body():
                started.set()
                await release.wait()
                yield b"1234567"

            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
                cookies={"session": self.client.cookies.get("session")},
            ) as client:
                first_task = asyncio.create_task(client.post(
                    endpoint, content=slow_body(), headers={
                        "Content-Length": "7", "X-PBJ-Filename": "first.mov",
                        "X-PBJ-Upload-ID": "upload-first-123",
                    },
                ))
                await started.wait()
                second = await client.post(endpoint, content=b"7654321", headers={
                    "Content-Length": "7", "X-PBJ-Filename": "second.mov",
                    "X-PBJ-Upload-ID": "upload-second-123",
                })
                completion = await client.post(
                    "/projects/upload-session/%s/complete" % upload["session_id"],
                )
                release.set()
                first = await first_task
                return first, second, completion

        with patch.object(main_module, "settings", limited):
            first, second, completion = asyncio.run(exercise())

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 413)
        self.assertEqual(completion.status_code, 409)
        self.assertNotIn(upload["session_id"], main_module.upload_reserved_bytes)

    def test_same_name_and_size_with_different_content_are_distinct_uploads(self):
        upload = self.store.create_upload_session(
            "Identity test", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        endpoint = "/projects/upload-session/%s/file" % upload["session_id"]
        headers = {"X-PBJ-Filename": "clip.mov", "Content-Type": "video/quicktime"}

        first = self.client.post(endpoint, content=b"first-bytes!", headers=headers)
        second = self.client.post(endpoint, content=b"other-bytes!", headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        files = self.store.upload_session(upload["session_id"])["files"]
        self.assertEqual(len(files), 2)
        self.assertNotEqual(files[0]["sha256"], files[1]["sha256"])

    def test_upload_rejects_declared_batch_over_limit_before_writing_body(self):
        upload = self.store.create_upload_session(
            "Limit test", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        self.store.update_upload_session(upload["session_id"], files=[{
            "file_id": "raw-001", "original_name": "saved.mov",
            "stored_path": "upload_sessions/placeholder/raw/saved.mov",
            "size_bytes": settings.max_upload_batch_bytes,
            "sha256": "a" * 64,
        }])

        response = self.client.post(
            "/projects/upload-session/%s/file" % upload["session_id"],
            content=b"x",
            headers={"X-PBJ-Filename": "extra.mov", "Content-Type": "video/quicktime"},
        )

        self.assertEqual(response.status_code, 413)
        raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        self.assertFalse(raw_dir.exists())

    def test_upload_completion_inspects_with_bounded_parallelism_and_rejects_late_file(self):
        upload = self.store.create_upload_session(
            "Parallel inspection", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        raw_dir.mkdir(parents=True)
        files = []
        for index in range(4):
            path = raw_dir / ("%03d-video.mov" % (index + 1))
            path.write_bytes(b"video")
            files.append({
                "file_id": "raw-%03d" % (index + 1), "original_name": path.name,
                "stored_path": str(path.relative_to(self.store.data_dir)),
                "size_bytes": path.stat().st_size, "sha256": "a" * 64,
            })
        self.store.update_upload_session(upload["session_id"], files=files)

        def slow_inspection(_path):
            time.sleep(0.1)
            return {"duration_seconds": 5, "has_audio": True}

        started = time.perf_counter()
        with patch.object(main_module, "inspect_video", side_effect=slow_inspection):
            response = self.client.post("/projects/upload-session/%s/complete" % upload["session_id"])
        elapsed = time.perf_counter() - started

        self.assertEqual(response.status_code, 200)
        self.assertLess(elapsed, 0.35)
        late = self.client.post(
            "/projects/upload-session/%s/file" % upload["session_id"], content=b"late",
            headers={"X-PBJ-Filename": "late.mov", "Content-Type": "video/quicktime"},
        )
        self.assertEqual(late.status_code, 409)
        self.assertEqual(
            self.client.post("/projects/upload-session/%s/complete" % upload["session_id"]).status_code,
            200,
        )

    def test_failed_inspection_removes_only_bad_staging_and_batch_can_retry(self):
        upload = self.store.create_upload_session(
            "Recover inspection", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        raw_dir.mkdir(parents=True)
        bad = raw_dir / "001-clip.mov"
        good = raw_dir / "002-clip.mov"
        good.write_bytes(b"good-video")
        bad.write_bytes(b"bad-video")
        files = [{
            "file_id": "raw-%03d" % index,
            "original_name": "clip.mov",
            "stored_path": str(path.relative_to(self.store.data_dir)),
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        } for index, path in enumerate((bad, good), start=1)]
        self.store.update_upload_session(upload["session_id"], files=files)

        def inspect_with_one_failure(path):
            if path.name == bad.name:
                return {"inspection_error": "media_inspection_failed"}
            return {"duration_seconds": 5, "has_audio": True}

        endpoint = "/projects/upload-session/%s/complete" % upload["session_id"]
        with patch.object(main_module, "inspect_video", side_effect=inspect_with_one_failure):
            rejected = self.client.post(endpoint)

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(
            rejected.json()["detail"],
            "PBJ removed 1 video it could not read. Your other 1 video remains saved; "
            "choose a replacement and try again.",
        )
        saved = self.store.upload_session(upload["session_id"])
        self.assertEqual(saved["status"], "uploading")
        self.assertEqual([item["file_id"] for item in saved["files"]], ["raw-002"])
        self.assertTrue(good.exists())
        self.assertFalse(bad.exists())

        replacement = self.client.post(
            "/projects/upload-session/%s/file" % upload["session_id"],
            content=b"replacement-video",
            headers={
                "X-PBJ-Filename": "clip.mov",
                "X-PBJ-Upload-ID": "upload-replacement-123",
            },
        )
        self.assertEqual(replacement.status_code, 200)
        saved = self.store.upload_session(upload["session_id"])
        self.assertEqual([item["file_id"] for item in saved["files"]], ["raw-002", "raw-003"])
        self.assertEqual(len({item["stored_path"] for item in saved["files"]}), 2)
        self.assertEqual(good.read_bytes(), b"good-video")

        with patch.object(
            main_module, "inspect_video",
            return_value={"duration_seconds": 5, "has_audio": True},
        ):
            retried = self.client.post(endpoint)
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(self.store.upload_session(upload["session_id"])["status"], "ready_for_brief")

    def test_media_inspection_limit_is_global_across_upload_sessions(self):
        uploads = []
        for session_index in range(2):
            upload = self.store.create_upload_session(
                "Global inspection %d" % session_index,
                self.store.list_styles()[0]["style_id"], "pegasus",
                "Make a short edit", 20, device_id="test-device",
            )
            raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
            raw_dir.mkdir(parents=True)
            files = []
            for file_index in range(2):
                path = raw_dir / ("%03d-video.mov" % (file_index + 1))
                path.write_bytes(b"video")
                files.append({
                    "file_id": "raw-%03d" % (file_index + 1),
                    "original_name": path.name,
                    "stored_path": str(path.relative_to(self.store.data_dir)),
                    "size_bytes": path.stat().st_size,
                    "sha256": "%064d" % (session_index * 2 + file_index),
                })
            self.store.update_upload_session(upload["session_id"], files=files)
            uploads.append(upload)

        tracking_lock = Lock()
        active = 0
        max_active = 0

        def slow_inspection(_path):
            nonlocal active, max_active
            with tracking_lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                return {"duration_seconds": 5, "has_audio": True}
            finally:
                with tracking_lock:
                    active -= 1

        async def exercise():
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
                cookies={"session": self.client.cookies.get("session")},
            ) as client:
                return await asyncio.gather(*(
                    client.post(
                        "/projects/upload-session/%s/complete" % upload["session_id"],
                    )
                    for upload in uploads
                ))

        with patch.object(main_module, "inspect_video", side_effect=slow_inspection):
            responses = asyncio.run(exercise())

        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(max_active, 2)

    def test_repeated_project_finish_creates_and_queues_only_one_project(self):
        style_id = self.store.list_styles()[0]["style_id"]
        upload = self.store.create_upload_session(
            "One project", style_id, "pegasus", "Make a short chronological cut", 20,
            device_id="test-device",
        )
        raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        raw_dir.mkdir(parents=True)
        source = raw_dir / "001-clip.mov"
        source.write_bytes(b"project-source")
        self.store.update_upload_session(
            upload["session_id"], status="ready_for_brief",
            files=[{
                "file_id": "raw-001", "original_name": "clip.mov",
                "stored_path": str(source.relative_to(self.store.data_dir)),
                "size_bytes": source.stat().st_size,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }],
            inspection_metadata={str(source): {"duration_seconds": 10, "has_audio": True}},
            total_duration_seconds=10,
        )
        before = {item["project_id"] for item in self.store.list_projects()}
        original_create = self.store.create_project

        def slow_create(*args, **kwargs):
            time.sleep(0.1)
            return original_create(*args, **kwargs)

        async def no_op(_project_id):
            return None

        async def exercise():
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
                cookies={"session": self.client.cookies.get("session")},
                follow_redirects=False,
            ) as client:
                return await asyncio.gather(
                    client.post("/projects/new/brief", data={"session_id": upload["session_id"]}),
                    client.post("/projects/new/brief", data={"session_id": upload["session_id"]}),
                )

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test", "TWELVE_LABS_API_KEY": "test"}),
            patch.object(self.store, "create_project", side_effect=slow_create),
            patch.object(main_module, "_run_complete_production", new=no_op),
        ):
            responses = asyncio.run(exercise())

        self.assertTrue(all(response.status_code in (303, 409) for response in responses))
        self.assertIn(303, [response.status_code for response in responses])
        created = {item["project_id"] for item in self.store.list_projects()} - before
        self.assertEqual(len(created), 1)
        saved_session = self.store.upload_session(upload["session_id"])
        self.assertEqual(saved_session["status"], "promoted")
        self.assertEqual(saved_session["project_id"], next(iter(created)))
        self.assertEqual(saved_session["files"], [])

    def test_failed_promotion_commit_stays_retryable_without_starting_work(self):
        style_id = self.store.list_styles()[0]["style_id"]
        upload = self.store.create_upload_session(
            "Commit recovery", style_id, "pegasus", "Make a short cut", 20,
            device_id="test-device",
        )
        staged_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        staged_dir.mkdir(parents=True)
        staged = staged_dir / "001-clip.mov"
        staged.write_bytes(b"promotion-source")
        self.store.update_upload_session(
            upload["session_id"], status="ready_for_brief",
            files=[{
                "file_id": "raw-001", "original_name": "clip.mov",
                "stored_path": str(staged.relative_to(self.store.data_dir)),
                "size_bytes": staged.stat().st_size,
                "sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
            }],
            inspection_metadata={str(staged): {"duration_seconds": 10, "has_audio": True}},
            total_duration_seconds=10,
        )
        before = {item["project_id"] for item in self.store.list_projects()}
        original_update = self.store.update_upload_session
        promotion_commits = 0
        background_runs = 0

        def fail_first_promotion_commit(session_id, **changes):
            nonlocal promotion_commits
            if changes.get("status") == "promoted":
                promotion_commits += 1
                if promotion_commits == 1:
                    raise OSError("simulated manifest commit failure")
            return original_update(session_id, **changes)

        async def should_not_run(_project_id):
            nonlocal background_runs
            background_runs += 1

        with (
            patch.dict("os.environ", {"OPENAI_API_KEY": "test", "TWELVE_LABS_API_KEY": "test"}),
            patch.object(self.store, "update_upload_session", side_effect=fail_first_promotion_commit),
            patch.object(main_module, "_run_complete_production", new=should_not_run),
        ):
            with self.assertRaises(OSError):
                self.client.post(
                    "/projects/new/brief", data={"session_id": upload["session_id"]},
                )

        created = {item["project_id"] for item in self.store.list_projects()} - before
        self.assertEqual(len(created), 1)
        project_id = next(iter(created))
        self.assertEqual(background_runs, 0)
        self.assertEqual(self.store.project(project_id)["status"], "analysis_failed")
        interrupted = self.store.upload_session(upload["session_id"])
        self.assertEqual(interrupted["status"], "promoting")
        self.assertEqual(interrupted["project_id"], project_id)
        self.assertEqual(staged.read_bytes(), b"promotion-source")
        self.assertFalse(any(
            item.get("source_key") == "raw:%s" % project_id
            for item in self.store.list_learning_signals(style_id)
        ))

        retry = self.client.get(
            "/projects/new/brief", params={"session_id": upload["session_id"]},
            follow_redirects=False,
        )
        self.assertEqual(retry.status_code, 303)
        recovered = self.store.upload_session(upload["session_id"])
        self.assertEqual(recovered["status"], "promoted")
        self.assertEqual(recovered["files"], [])
        self.assertFalse(staged_dir.exists())
        raw = self.store.project(project_id)["raw_files"][0]
        self.assertEqual(raw["original_name"], "clip.mov")
        self.assertEqual(Path(raw["stored_path"]).name, "001-clip.mov")
        self.assertEqual(
            self.store.resolve_data_path(raw["stored_path"]).read_bytes(), b"promotion-source",
        )

    def test_health_stays_responsive_while_uploaded_media_is_inspected(self):
        upload = self.store.create_upload_session(
            "Inspection test", self.store.list_styles()[0]["style_id"], "pegasus",
            "Make a short edit", 20, device_id="test-device",
        )
        raw_dir = self.store.upload_session_dir(upload["session_id"]) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        media = raw_dir / "001-video.mov"
        media.write_bytes(b"video")
        self.store.update_upload_session(upload["session_id"], files=[{
            "file_id": "raw-001", "original_name": "video.mov",
            "stored_path": str(media.relative_to(self.store.data_dir)), "size_bytes": media.stat().st_size,
        }])

        def slow_inspection(_path):
            time.sleep(0.3)
            return {"duration_seconds": 5, "has_audio": True}

        async def exercise():
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
                cookies={"session": self.client.cookies.get("session")},
            ) as client:
                started = asyncio.get_running_loop().time()
                completion = asyncio.create_task(client.post(
                    "/projects/upload-session/%s/complete" % upload["session_id"]
                ))
                await asyncio.sleep(0.03)
                health = await client.get("/health")
                responsive_after = asyncio.get_running_loop().time() - started
                completed = await completion
                return health, responsive_after, completed

        with patch.object(main_module, "inspect_video", side_effect=slow_inspection):
            health, responsive_after, completed = asyncio.run(exercise())
        self.assertEqual(health.status_code, 200)
        self.assertLess(responsive_after, 0.2)
        self.assertEqual(completed.status_code, 200)

    def test_progress_pages_keep_current_screen_during_transient_gateway_failure(self):
        self.store.update_project(self.project_id, status="analysis_queued")
        response = self.client.get("/projects/%s/production-progress" % self.project_id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("pbjSafeRefresh(3000)", response.text)
        self.assertIn("if(response.ok&&contentType.includes('text/html'))", response.text)
        self.assertNotIn("location.reload()", response.text)

    def test_project_cards_use_canonical_render_and_status_fields(self):
        self.store.update_project(self.project_id, status="exporting")
        working = self.client.get("/projects")
        self.assertEqual(working.status_code, 200)
        self.assertIn("Rendered cut", working.text)
        self.assertIn("Working", working.text)
        self.assertNotIn("2 timelines", working.text)

        self.store.update_project(self.project_id, status="export_failed")
        failed = self.client.get("/projects")
        self.assertIn("Attention", failed.text)

        self.store.update_project(self.project_id, status="timeline_ready")
        ready = self.client.get("/projects")
        self.assertIn("Ready", ready.text)

    def test_versioned_ui_css_has_a_working_cache_validator(self):
        first = self.client.get("/ui.css?v=22")
        self.assertEqual(first.status_code, 200)
        self.assertGreater(len(first.content), 0)
        self.assertIn("max-age=3600", first.headers["cache-control"])
        self.assertTrue(first.headers["etag"])
        self.assertNotIn("set-cookie", first.headers)
        self.assertNotIn("vary", first.headers)

        cached = self.client.get("/ui.css?v=22", headers={"If-None-Match": first.headers["etag"]})
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")

    def test_client_diagnostics_store_only_allowlisted_private_fields(self):
        response = self.client.post("/diagnostics/client", json={
            "event": "upload_failed",
            "upload_session_id": "upload-20260903-abcdef",
            "stage": "file_upload",
            "file_index": 2,
            "total_files": 16,
            "file_size_bytes": 123456,
            "percent": 50,
            "error_code": "xhr_network",
            "filename": "private-vacation.mov",
            "prompt": "a private creative direction",
            "access_code": "never-store-this",
            "raw_error": "sensitive stack trace",
            "user_agent": "secret-from-user-agent",
            "client_recorded_at": "prompt-like-client-time",
            "connection_type": "private-connection-secret",
        })

        self.assertEqual(response.status_code, 204)
        log_text = (self.store.diagnostics_dir / "client-events.jsonl").read_text()
        saved = json.loads(log_text)
        self.assertEqual(saved["event"], "upload_failed")
        self.assertEqual(saved["file_index"], 2)
        self.assertEqual(saved["error_code"], "xhr_network")
        self.assertIsNone(saved["connection_type"])
        for forbidden in (
            "private-vacation.mov", "private creative direction", "never-store-this",
            "sensitive stack trace", "secret-from-user-agent", "prompt-like-client-time",
            "private-connection-secret",
        ):
            self.assertNotIn(forbidden, log_text)

        download = self.client.get("/diagnostics/download")
        self.assertEqual(download.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertIn("pbj-diagnostics/client-events.jsonl", archive.namelist())
            self.assertIn("upload_failed", archive.read("pbj-diagnostics/client-events.jsonl").decode())

        self.set_session(owner=False)
        self.assertEqual(self.client.get("/diagnostics/download").status_code, 403)

    def test_client_diagnostics_reject_unknown_events(self):
        response = self.client.post("/diagnostics/client", json={"event": "capture_everything"})
        self.assertEqual(response.status_code, 400)

    def test_recipe_lab_does_not_expose_analyzer_or_refresh_controls(self):
        style_id = self.store.list_styles()[0]["style_id"]
        response = self.client.get("/styles/%s/analysis" % style_id)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="providers"', response.text)
        self.assertNotIn('name="refresh"', response.text)

    def test_recipe_lab_requires_explicit_shared_contribution_consent(self):
        response = self.client.get("/styles/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="contribution_consent"', response.text)
        self.assertIn("visible to beta testers", response.text)


if __name__ == "__main__":
    unittest.main()
