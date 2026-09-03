import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TroyFaceliftPhase6Tests(unittest.TestCase):
    def read(self, relative_path: str) -> str:
        return (ROOT / relative_path).read_text()

    def test_rotated_iphone_keeps_pbj_mobile_shell(self):
        legacy_mobile = self.read("app/static/mobile-v2.css")
        foundation = self.read("app/static/troy-foundation.css")
        short_landscape = "(max-width:900px) and (max-height:500px)"
        self.assertIn(short_landscape, legacy_mobile)
        self.assertIn("(max-width: 900px) and (max-height: 500px)", foundation)

    def test_pwa_allows_rotation_and_versioned_facelift_assets(self):
        manifest = json.loads(self.read("app/static/manifest.webmanifest"))
        self.assertEqual(manifest["orientation"], "any")
        base = self.read("app/templates/base.html")
        access = self.read("app/templates/access.html")
        worker = self.read("app/static/service-worker.js")
        for asset in ("mobile-v2.css", "troy-foundation.css", "troy-screens.css"):
            self.assertIn(f"/static/{asset}?v=21", worker)
        self.assertIn("/ui.css?v=22", base)
        self.assertIn("/ui.css?v=22", access)
        self.assertIn("getRegistrations", base)
        self.assertIn("getRegistrations", access)
        self.assertIn('const CACHE = "pbj-shell-v21"', worker)
        self.assertIn('caches.match("/offline")', worker)
        self.assertIn("if (!response.ok)", worker)

    def test_mobile_shell_keeps_content_inside_gutters_and_safe_areas(self):
        screens = self.read("app/static/troy-screens.css")
        self.assertIn("calc(var(--pbj-safe-top) + 16px)", screens)
        self.assertIn("max(var(--pbj-gutter),var(--pbj-safe-left))", screens)
        self.assertIn("max(var(--pbj-gutter),var(--pbj-safe-right))", screens)
        self.assertIn("main:has(> .pbj-screen-exact)", screens)

    def test_reduced_motion_and_touch_safe_controls_remain_available(self):
        foundation = self.read("app/static/troy-foundation.css")
        self.assertIn("@media (prefers-reduced-motion: reduce)", foundation)
        self.assertIn("animation-duration: .01ms !important", foundation)
        self.assertIn("--pbj-button-height: 56px", foundation)
        self.assertIn("--pbj-tap-min: 44px", foundation)
        self.assertIn("min-height: 44px", foundation)

    def test_upload_and_lifecycle_recovery_contracts_remain_present(self):
        upload = self.read("app/templates/project_footage.html")
        self.assertIn("const workers=phoneLayout?1:2", upload)
        self.assertIn("(max-width: 900px) and (max-height: 500px)", upload)

    def test_rough_cut_player_is_mobile_safe(self):
        template = self.read("app/templates/project_ready.html")
        screens = self.read("app/static/troy-screens.css")
        self.assertIn("playsinline", template)
        self.assertIn("pbj-roughcut-player", screens)
        self.assertIn("max-height:62vh", screens)


if __name__ == "__main__":
    unittest.main()
