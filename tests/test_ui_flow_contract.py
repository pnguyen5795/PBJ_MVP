import json
import io
import tempfile
import unittest
import zipfile
from base64 import b64encode
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import app.main as main_module
from app.config import settings
from app.storage import JsonStore
from app.timeline.contracts import empty_timeline
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

    def test_processing_copy_distinguishes_timeline_stages(self):
        self.store.update_project(self.project_id, status="planning_timeline")
        response = self.client.get("/projects/%s/production-progress" % self.project_id)
        self.assertIn("CREATING YOUR ROUGH CUT", response.text)
        self.assertIn("Building and validating the story", response.text)
        self.assertIn("Rendering the video", response.text)

    def test_restart_marks_interrupted_job_as_retryable(self):
        self.store.update_project(
            self.project_id, status="preparing_proxies", active_revision=1,
            active_task="Preparing the handoff",
        )
        main_module.recover_interrupted_jobs()
        recovered = self.store.project(self.project_id)
        self.assertEqual(recovered["status"], "timeline_failed")
        self.assertIsNone(recovered["active_revision"])
        self.assertIn("interrupted", recovered["last_error"].lower())

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

    def test_project_private_recipe_is_isolated_to_its_device(self):
        private = self.store.create_style("Private references", [], {})
        self.store.update_style(private["style_id"], project_private=True, device_id="first-device")
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
