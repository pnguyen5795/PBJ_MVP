import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase3Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_creation_steps_use_troys_real_screen_compositions(self):
        expected = {
            "project_describe.html": "pbj-np2",
            "project_references.html": "pbj-teach-it",
            "project_footage.html": "pbj-np1",
            "project_brief.html": "pbj-np2",
        }
        for name, screen_class in expected.items():
            template = self.read("app/templates/" + name)
            self.assertIn(screen_class, template)
            self.assertIn("pbj-screen-exact", template)
            self.assertNotIn("pbj-create-top", template)
            self.assertNotIn("pbj-progress", template)

    def test_canonical_routes_and_back_paths_are_unchanged(self):
        describe = self.read("app/templates/project_describe.html")
        references = self.read("app/templates/project_references.html")
        footage = self.read("app/templates/project_footage.html")
        brief = self.read("app/templates/project_new_brief.html")
        self.assertIn('action="/projects/new/describe"', describe)
        self.assertIn('action="/projects/new/references"', references)
        self.assertIn('href="/projects/new/references"', footage)
        self.assertIn('action="/projects/new/brief"', brief)
        self.assertIn('name="session_id"', brief)

    def test_resumable_upload_contract_and_limits_remain_present(self):
        footage = self.read("app/templates/project_footage.html")
        self.assertIn('data-session-upload="true"', footage)
        self.assertIn("/projects/upload-session", footage)
        self.assertIn("2147483648", footage)
        self.assertIn("max-width: 720px", footage)
        self.assertIn("Array.from({length:workers}", footage)
        self.assertIn("history.replaceState", footage)
        self.assertIn("visibilitychange", footage)
        self.assertIn("Connection paused. Retrying", footage)
        self.assertIn("alreadyUploaded", footage)
        self.assertIn("Photos or Files", footage)
        self.assertIn("The length of your cut will come from your creative brief", footage)
        self.assertNotIn("Target length", footage)
        self.assertNotIn('name="target_seconds"', footage)

    def test_references_remain_optional_private_and_supplied(self):
        references = self.read("app/templates/project_references.html")
        self.assertIn('name="skip" value="true"', references)
        self.assertIn('accept="video/*"', references)
        self.assertIn("up to 5 videos", references.casefold())
        self.assertIn("privately for this project", references)
        self.assertNotIn("presetStyles", references)

    def test_normal_creation_screens_do_not_expose_recipe_selection(self):
        combined = "\n".join(
            self.read("app/templates/" + name)
            for name in (
                "project_describe.html",
                "project_references.html",
                "project_footage.html",
                "project_new_brief.html",
            )
        ).casefold()
        self.assertNotIn("choose a recipe", combined)
        self.assertNotIn("select a recipe", combined)
        self.assertNotIn("recipe marketplace", combined)
        self.assertNotIn("troy", combined)


if __name__ == "__main__":
    unittest.main()
