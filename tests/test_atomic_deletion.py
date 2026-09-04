import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

import app.main as main_module
from app.storage import JsonStore
from app.timeline.lifecycle import begin_timeline_job


def owner_request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "session": {
            "authorized": True,
            "owner": True,
            "device_id": "test-device",
        },
    })


class AtomicDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name) / "data")
        self.style = self.store.create_style("Deletion recipe", [], {})
        self.project = self.store.create_project(
            "Deletion project", self.style["style_id"], "pegasus",
            "Make a short cut", 20, [], {}, device_id="test-device",
        )
        self.store.update_project(self.project["project_id"], status="timeline_ready")

    def tearDown(self):
        self.temp.cleanup()

    def test_project_deletion_claim_blocks_new_work_during_remote_cleanup(self):
        project_id = self.project["project_id"]
        self.store.record_remote_asset(
            self.store.project_dir(project_id), "pegasus", "raw-001",
            {"id": "asset-project", "status": "ready", "retained": True},
        )

        async def exercise():
            started = asyncio.Event()
            release = asyncio.Event()

            async def paused_cleanup(*_args):
                started.set()
                await release.wait()
                return True

            with (
                patch.object(main_module, "store", self.store),
                patch.object(main_module, "cleanup_remote_asset", new=paused_cleanup),
            ):
                deletion = asyncio.create_task(main_module.delete_project(
                    owner_request("/projects/%s/delete" % project_id), project_id,
                ))
                await asyncio.wait_for(started.wait(), 1)
                self.assertEqual(
                    self.store.project(project_id)["status"], "project_deleting",
                )
                with self.assertRaisesRegex(ValueError, "current project task"):
                    begin_timeline_job(
                        self.store, project_id, "approval_running", "New work",
                    )
                release.set()
                response = await asyncio.wait_for(deletion, 1)
                return response

        response = asyncio.run(exercise())
        self.assertEqual(response.status_code, 303)
        self.assertFalse(self.store.project_dir(project_id).exists())

    def test_project_cleanup_failure_restores_exact_prior_state(self):
        project_id = self.project["project_id"]
        self.store.update_project(project_id, status="approved")
        self.store.record_remote_asset(
            self.store.project_dir(project_id), "pegasus", "raw-001",
            {"id": "asset-project", "status": "ready", "retained": True},
        )

        async def failed_cleanup(*_args):
            raise RuntimeError("provider detail must not be persisted")

        async def exercise():
            with (
                patch.object(main_module, "store", self.store),
                patch.object(main_module, "cleanup_remote_asset", new=failed_cleanup),
            ):
                return await main_module.delete_project(
                    owner_request("/projects/%s/delete" % project_id), project_id,
                )

        with self.assertRaises(main_module.HTTPException) as raised:
            asyncio.run(exercise())
        self.assertEqual(raised.exception.status_code, 502)
        saved = self.store.project(project_id)
        self.assertEqual(saved["status"], "approved")
        self.assertIsNone(saved["deletion_return_status"])
        self.assertNotIn("provider detail", str(saved))

    def test_style_deletion_claim_blocks_a_new_linked_project(self):
        self.store.delete_project(self.project["project_id"])
        style_id = self.style["style_id"]
        self.store.record_remote_asset(
            self.store.style_dir(style_id), "pegasus", "reference-001",
            {"id": "asset-style", "status": "ready", "retained": True},
        )
        source = Path(self.temp.name) / "new.mov"
        source.write_bytes(b"new media")
        attempted_id = "project-20260903-abcdef"

        async def exercise():
            started = asyncio.Event()
            release = asyncio.Event()

            async def paused_cleanup(*_args):
                started.set()
                await release.wait()
                return True

            with (
                patch.object(main_module, "store", self.store),
                patch.object(main_module, "cleanup_remote_asset", new=paused_cleanup),
            ):
                deletion = asyncio.create_task(main_module.delete_style(
                    owner_request("/styles/%s/delete" % style_id), style_id,
                ))
                await asyncio.wait_for(started.wait(), 1)
                self.assertEqual(self.store.style(style_id)["status"], "style_deleting")
                with self.assertRaisesRegex(ValueError, "being archived"):
                    self.store.create_project(
                        "Too late", style_id, "pegasus", "Make a cut", 20,
                        [source], {str(source): {"duration_seconds": 1}},
                        project_id_override=attempted_id,
                    )
                self.assertFalse(self.store.project_dir(attempted_id).exists())
                release.set()
                return await asyncio.wait_for(deletion, 1)

        response = asyncio.run(exercise())
        self.assertEqual(response.status_code, 303)
        self.assertFalse(self.store.style_dir(style_id).exists())
        self.assertTrue(list(self.store.deleted_styles_dir.glob(style_id + "-*")))

    def test_style_claim_checks_linked_projects_atomically(self):
        with self.assertRaisesRegex(ValueError, "existing project"):
            self.store.begin_style_deletion(
                self.style["style_id"],
                reject_statuses=main_module.ACTIVE_STYLE_JOB_STATES,
            )
        self.assertNotEqual(
            self.store.style(self.style["style_id"])["status"], "style_deleting",
        )

    def test_style_cleanup_failure_restores_exact_prior_state(self):
        self.store.delete_project(self.project["project_id"])
        style_id = self.style["style_id"]
        self.store.update_style(style_id, status="approved")
        self.store.record_remote_asset(
            self.store.style_dir(style_id), "pegasus", "reference-001",
            {"id": "asset-style", "status": "ready", "retained": True},
        )

        async def failed_cleanup(*_args):
            raise RuntimeError("private provider failure")

        async def exercise():
            with (
                patch.object(main_module, "store", self.store),
                patch.object(main_module, "cleanup_remote_asset", new=failed_cleanup),
            ):
                return await main_module.delete_style(
                    owner_request("/styles/%s/delete" % style_id), style_id,
                )

        with self.assertRaises(main_module.HTTPException) as raised:
            asyncio.run(exercise())
        self.assertEqual(raised.exception.status_code, 502)
        style = self.store.style(style_id)
        self.assertEqual(style["status"], "approved")
        self.assertIsNone(style["deletion_return_status"])
        self.assertNotIn("private provider failure", str(style))

    def test_style_archive_cannot_orphan_an_unfinished_upload(self):
        self.store.delete_project(self.project["project_id"])
        upload = self.store.create_upload_session(
            "Unfinished", self.style["style_id"], "pegasus",
            "Make a cut", 20, device_id="test-device",
        )

        with self.assertRaisesRegex(ValueError, "unfinished project upload"):
            self.store.begin_style_deletion(
                self.style["style_id"],
                reject_statuses=main_module.ACTIVE_STYLE_JOB_STATES,
            )

        self.store.update_style(
            self.style["style_id"], status="style_deleting",
            deletion_return_status="approved",
        )
        with self.assertRaisesRegex(ValueError, "being archived"):
            self.store.create_upload_session(
                "Too late", self.style["style_id"], "pegasus", "Make a cut", 20,
            )
        self.assertTrue(self.store.upload_session(upload["session_id"]))

    def test_restart_restores_interrupted_project_and_style_deletions(self):
        project_id = self.project["project_id"]
        style_id = self.style["style_id"]
        self.store.update_project(
            project_id, status="project_deleting",
            deletion_return_status="timeline_ready", active_task="Deleting",
        )
        self.store.update_style(
            style_id, status="style_deleting",
            deletion_return_status="approved", active_task="Archiving",
        )

        with patch.object(main_module, "store", self.store):
            main_module.recover_interrupted_jobs()

        project = self.store.project(project_id)
        style = self.store.style(style_id)
        self.assertEqual(project["status"], "timeline_ready")
        self.assertEqual(project["last_error_details"]["code"], "project_deletion_interrupted")
        self.assertEqual(style["status"], "approved")
        self.assertEqual(style["last_error_details"]["code"], "recipe_deletion_interrupted")


if __name__ == "__main__":
    unittest.main()
