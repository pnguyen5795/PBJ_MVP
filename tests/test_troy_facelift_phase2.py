import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase2Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_access_uses_real_pbj_authorization_with_troy_visuals(self):
        template = self.read("app/templates/access.html")
        self.assertIn('action="/access"', template)
        self.assertIn('name="code"', template)
        self.assertIn("pbj-access__mark", template)
        self.assertIn("/static/brand/sandwich-logo.png", template)
        self.assertNotIn("Clerk", template)
        self.assertNotIn("Continue With Apple", template)

    def test_home_uses_real_project_state_and_canonical_actions(self):
        template = self.read("app/templates/welcome.html")
        self.assertIn("{% for project in projects %}", template)
        self.assertIn('href="/projects/new"', template)
        self.assertIn('href="/projects"', template)
        self.assertIn("pbj-home__recents", template)
        self.assertNotIn("activeRenders", template)

    def test_projects_keep_real_routes_and_deliberate_delete(self):
        template = self.read("app/templates/dashboard.html")
        self.assertIn("project.project_id", template)
        self.assertIn('action="/projects/{{ project.project_id }}/delete"', template)
        self.assertIn("return confirm(", template)
        self.assertIn("pbj-project-grid", template)
        self.assertNotIn("FakeProject", template)

    def test_more_and_connections_keep_owner_boundary(self):
        more = self.read("app/templates/more.html")
        settings = self.read("app/templates/settings.html")
        self.assertIn("request.session.owner", more)
        self.assertIn('action="/owner-access"', more)
        self.assertIn('action="/settings"', settings)
        self.assertIn('href="/more"', settings)
        self.assertNotIn("Sign Out", settings)

    def test_phase2_mobile_layout_has_two_column_projects_and_one_column_settings(self):
        css = self.read("app/static/troy-foundation.css")
        self.assertIn(".pbj-project-grid", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", css)
        self.assertIn(".pbj-settings-layout", css)
        self.assertIn(".pbj-settings-layout { grid-template-columns: 1fr; }", css)
        self.assertIn("min-height: 44px", css)


if __name__ == "__main__":
    unittest.main()
