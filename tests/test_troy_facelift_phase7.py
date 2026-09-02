import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase7Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_runtime_does_not_contain_excluded_troy_architecture(self):
        runtime = "\n".join(
            path.read_text(errors="ignore")
            for root in (ROOT / "app",)
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".py", ".html", ".css", ".js", ".ts", ".tsx"}
        )
        for excluded in ("ClerkProvider", "useClerk", "mockProjects", "TroyStudio", "StudioPage"):
            self.assertNotIn(excluded, runtime)

    def test_openreel_runtime_is_removed(self):
        self.assertFalse((ROOT / "integrations" / "openreel").exists())
        self.assertFalse((ROOT / "app" / "openreel_adapter.py").exists())
        self.assertNotIn("openreel", self.read("start_app.command").casefold())

    def test_notices_and_acceptance_preserve_permission_and_user_gate(self):
        notices = self.read("THIRD_PARTY_NOTICES.md")
        acceptance = self.read("docs/FACELIFT_ACCEPTANCE.md")
        self.assertIn("10c8efdf2f2187604a934d082d038db8729a75d9", notices)
        self.assertIn("No Troy Studio", notices)
        self.assertIn("approve and merge", acceptance)
        self.assertIn("request changes", acceptance)
        self.assertIn("awaiting physical-iPhone acceptance", acceptance)

    def test_phase7_plan_cannot_claim_completion_before_owner_approval(self):
        plan = self.read("docs/TROY_FACELIFT_PLAN.md")
        self.assertIn("Awaiting explicit owner acceptance", plan)
        self.assertIn("Do not mark complete", plan)
        self.assertIn("owner accepts", plan)

    def test_shared_shell_has_no_bottom_navigation_or_reserved_bar_space(self):
        base = self.read("app/templates/base.html")
        mobile_css = self.read("app/static/mobile-v2.css")
        foundation = self.read("app/static/troy-foundation.css")
        self.assertNotIn("mobile-tabbar", base)
        self.assertNotIn("mobile-tabbar", mobile_css)
        self.assertNotIn("mobile-tabbar", foundation)
        self.assertNotIn("padding-bottom:calc(78px", mobile_css)
        self.assertNotIn("bottom:calc(80px", mobile_css)


if __name__ == "__main__":
    unittest.main()
