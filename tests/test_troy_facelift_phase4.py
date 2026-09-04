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
            "timeline_queued", "planning_timeline", "export_queued", "exporting",
        ):
            self.assertIn(status, template)
        self.assertIn("Understanding your footage", template)
        self.assertIn("Building and validating the story", template)
        self.assertIn("Rendering the video", template)
        self.assertIn("FFmpeg", template)

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
        self.assertIn("project.last_error", template)
        self.assertIn('/projects/{{ project.project_id }}/brief', template)
        self.assertIn("project.last_error", template)
        self.assertIn("Technical details", template)

    def test_rough_cut_ready_has_review_actions_without_an_editor(self):
        template = self.read("app/templates/project_ready.html")
        self.assertNotIn("openreel", template.casefold())
        self.assertIn("Approve this cut", template)
        self.assertIn("Request changes", template)
        self.assertIn("Create a new version", template)
        self.assertIn("View footage analysis", template)
        self.assertIn('class="button secondary wide"', template)
        self.assertIn("<video", template)
        self.assertNotIn("/static/editor/", template)
        self.assertNotIn("Studio", template)

    def test_reference_learning_uses_real_reload_and_error_state(self):
        template = self.read("app/templates/project_references_progress.html")
        self.assertIn("style.last_error", template)
        self.assertIn("pbjSafeRefresh(3000)", template)
        self.assertNotIn("location.reload()", template)
        self.assertIn("Try different examples", template)
        self.assertIn("Try this analysis again", template)
        self.assertIn("/projects/new/references-retry", template)
        self.assertIn("real analysis is ready", template)


if __name__ == "__main__":
    unittest.main()
