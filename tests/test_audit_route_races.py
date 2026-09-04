import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import app.main as main_module
from app.storage import JsonStore
from app.timeline.contracts import empty_timeline
from app.timeline.storage import TimelineStore


class AuditRouteRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name) / "data")
        self.style = self.store.create_style("Route race recipe", [], {})
        self.project = self.store.create_project(
            "Route race project", self.style["style_id"], "pegasus",
            "Make a short edit", 20, [], {}, device_id="test-device",
        )
        self.project_id = self.project["project_id"]
        TimelineStore(self.store).initialize(
            self.project_id, empty_timeline(self.project_id, []),
        )
        self.store.update_project(self.project_id, status="timeline_ready")

    def tearDown(self):
        self.temp.cleanup()

    def test_timeline_retry_reuses_exact_pending_revision_feedback(self):
        feedback = "Keep the smile and shorten the setup"
        self.store.update_project(
            self.project_id, status="timeline_failed",
            content_map={"all_segments": []},
            pending_revision_feedback=feedback,
        )
        tasks = MagicMock()

        with patch.object(main_module, "store", self.store):
            response = asyncio.run(main_module.retry_failed_rough_cut(
                self.project_id, tasks,
            ))

        self.assertEqual(response.status_code, 303)
        tasks.add_task.assert_called_once_with(
            main_module._run_revision, self.project_id, feedback,
        )
        self.assertEqual(self.store.project(self.project_id)["status"], "timeline_queued")

    def test_initial_timeline_retry_does_not_invent_revision_feedback(self):
        self.store.update_project(
            self.project_id, status="timeline_failed",
            content_map={"all_segments": []},
            pending_revision_feedback=None,
        )
        tasks = MagicMock()

        with patch.object(main_module, "store", self.store):
            response = asyncio.run(main_module.retry_failed_rough_cut(
                self.project_id, tasks,
            ))

        self.assertEqual(response.status_code, 303)
        tasks.add_task.assert_called_once_with(
            main_module._run_revision, self.project_id, "",
        )


if __name__ == "__main__":
    unittest.main()
