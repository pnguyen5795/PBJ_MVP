import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase7Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_runtime_does_not_contain_excluded_troy_architecture(self):
        runtime = "\n".join(
            path.read_text(errors="ignore")
            for root in (ROOT / "app", ROOT / "integrations" / "openreel" / "overlay")
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".html", ".css", ".js", ".ts", ".tsx"}
        )
        for excluded in ("ClerkProvider", "useClerk", "mockProjects", "TroyStudio", "StudioPage"):
            self.assertNotIn(excluded, runtime)

    def test_readable_overlay_matches_phase6_rotation_and_recovery_contracts(self):
        compat = self.read("integrations/openreel/overlay/apps/web/src/pbj/pbj-editor-compat.ts")
        loader = self.read("integrations/openreel/overlay/apps/web/src/pbj/pbj-project-loader.ts")
        sync = self.read("integrations/openreel/overlay/apps/web/src/pbj/pbj-sync.ts")
        self.assertIn("MOBILE_EDITOR_LANDSCAPE_MAX_WIDTH = 900", compat)
        self.assertIn("MOBILE_EDITOR_LANDSCAPE_MAX_HEIGHT = 500", compat)
        self.assertIn("display-mode: standalone", loader)
        self.assertIn('window.addEventListener("pagehide"', sync)
        self.assertIn("byteLength <= 60_000", sync)

    def test_notices_and_acceptance_preserve_permission_and_user_gate(self):
        notices = self.read("THIRD_PARTY_NOTICES.md")
        acceptance = self.read("docs/FACELIFT_ACCEPTANCE.md")
        self.assertIn("10c8efdf2f2187604a934d082d038db8729a75d9", notices)
        self.assertIn("No Troy Studio", notices)
        self.assertIn("Approve and merge", acceptance)
        self.assertIn("Request changes", acceptance)
        self.assertIn("awaiting physical-iPhone acceptance", acceptance)

    def test_phase7_plan_cannot_claim_completion_before_owner_approval(self):
        plan = self.read("docs/TROY_FACELIFT_PLAN.md")
        self.assertIn("awaiting explicit", plan)
        self.assertIn("Do not mark Phase 7 complete", plan)
        self.assertIn("explicitly accepts", plan)


if __name__ == "__main__":
    unittest.main()
