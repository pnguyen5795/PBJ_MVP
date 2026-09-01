import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase4Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_cooking_uses_real_project_statuses_and_three_real_stages(self):
        template = self.read("app/templates/production_progress.html")
        for status in (
            "analysis_queued", "analyzing_footage", "footage_analyzed",
            "timeline_queued", "planning_timeline", "preparing_proxies",
        ):
            self.assertIn(status, template)
        self.assertIn("Understanding your footage", template)
        self.assertIn("Building and validating the story", template)
        self.assertIn("Preparing the handoff", template)
        self.assertIn("No combined video is rendered", template)

    def test_cooking_does_not_import_simulated_progress_or_eta(self):
        template = self.read("app/templates/production_progress.html")
        self.assertNotIn("FAKE_ETA", template)
        self.assertNotIn("% done", template)
        self.assertNotIn("Math.round", template)
        self.assertNotIn("COOKING_NARRATION", template)
        self.assertNotIn("onComplete", template)

    def test_failures_preserve_retry_and_brief_recovery_paths(self):
        template = self.read("app/templates/production_progress.html")
        for status in ("analysis_failed", "rough_cut_failed", "timeline_failed", "export_failed"):
            self.assertIn(status, template)
        self.assertIn('/projects/{{ project.project_id }}/retry', template)
        self.assertIn('/projects/{{ project.project_id }}/brief', template)
        self.assertIn("project.last_error", template)
        self.assertIn("Technical details", template)

    def test_timeline_ready_has_one_openreel_primary_action(self):
        template = self.read("app/templates/project_ready.html")
        self.assertEqual(template.count('/openreel"'), 1)
        self.assertIn("Open in Editor", template)
        self.assertIn("validated your first timeline", template)
        self.assertIn("latest valid project snapshot", template)
        self.assertNotIn("/static/editor/", template)
        self.assertNotIn("Studio", template)

    def test_reference_learning_uses_real_reload_and_error_state(self):
        template = self.read("app/templates/project_references_progress.html")
        self.assertIn("style.last_error", template)
        self.assertIn("location.reload()", template)
        self.assertIn("Try different examples", template)
        self.assertIn("real analysis is ready", template)


if __name__ == "__main__":
    unittest.main()
