import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase5Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_openreel_visuals_are_scoped_to_pbj_sessions(self):
        patch = self.read("integrations/openreel/openreel-pbj.patch")
        self.assertIn('data-pbj-session={isPBJProject ? "true" : undefined}', patch)
        self.assertIn('root.dataset.pbjSession = "true"', patch)
        self.assertIn('delete root.dataset.pbjSession', patch)
        self.assertIn('html[data-pbj-session="true"]', patch)

    def test_pbj_session_uses_facelift_palette_and_primary_action(self):
        patch = self.read("integrations/openreel/openreel-pbj.patch")
        self.assertIn("--bg: #fff8f1", patch)
        self.assertIn("--accent: #8b5cf6", patch)
        self.assertIn(".pbj-export-primary", patch)
        self.assertIn("background: #000", patch)
        self.assertIn("Export & Approve", patch)

    def test_openreel_shell_accounts_for_iphone_safe_areas(self):
        patch = self.read("integrations/openreel/openreel-pbj.patch")
        self.assertIn("env(safe-area-inset-top)", patch)
        self.assertIn("env(safe-area-inset-left)", patch)
        self.assertIn("env(safe-area-inset-right)", patch)
        self.assertIn("env(safe-area-inset-bottom)", patch)

    def test_phase_does_not_import_troy_studio_or_editor_logic(self):
        patch = self.read("integrations/openreel/openreel-pbj.patch")
        self.assertNotIn("Swag420Money", patch)
        self.assertNotIn("TroyStudio", patch)
        self.assertNotIn("ClerkProvider", patch)
        self.assertNotIn("mockProjects", patch)

    def test_documented_boundary_keeps_openreel_tool_ownership(self):
        notes = self.read("integrations/openreel/overlay/APP_PATCH.md")
        self.assertIn("Standalone OpenReel sessions retain", notes)
        self.assertIn("Do not add callbacks to individual editor tools", notes)
        self.assertIn("OpenReel owns move, trim, split", notes)


if __name__ == "__main__":
    unittest.main()
