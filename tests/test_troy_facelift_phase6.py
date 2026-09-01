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
        for asset in ("mobile-v2.css", "troy-foundation.css"):
            self.assertIn(asset, base)
            self.assertIn(asset, access)
            self.assertIn(f"/static/{asset}?v=11", worker)
        self.assertGreaterEqual(base.count("?v=11"), 2)
        self.assertGreaterEqual(access.count("?v=11"), 2)
        self.assertIn('const CACHE = "pbj-shell-v11"', worker)

    def test_reduced_motion_and_touch_safe_controls_remain_available(self):
        foundation = self.read("app/static/troy-foundation.css")
        self.assertIn("@media (prefers-reduced-motion: reduce)", foundation)
        self.assertIn("animation-duration: .01ms !important", foundation)
        self.assertIn("--pbj-button-height: 56px", foundation)
        self.assertIn("--pbj-tap-min: 44px", foundation)
        self.assertIn("min-height: 44px", foundation)

    def test_upload_and_lifecycle_recovery_contracts_remain_present(self):
        upload = self.read("app/templates/project_footage.html")
        sync = self.read("integrations/openreel/overlay/apps/web/src/pbj/pbj-sync.ts")
        self.assertIn("const workers=phoneLayout?1:2", upload)
        self.assertIn("(max-width: 900px) and (max-height: 500px)", upload)
        self.assertIn('document.addEventListener("visibilitychange"', sync)
        self.assertIn('window.addEventListener("pagehide"', sync)
        self.assertIn("byteLength <= 60_000", sync)

    def test_openreel_patch_keeps_phone_layout_when_rotated(self):
        patch = self.read("integrations/openreel/openreel-pbj.patch")
        self.assertIn("MOBILE_EDITOR_LANDSCAPE_MAX_WIDTH = 900", patch)
        self.assertIn("MOBILE_EDITOR_LANDSCAPE_MAX_HEIGHT = 500", patch)
        self.assertIn("isMobileEditorViewport(window.innerWidth, window.innerHeight)", patch)
        self.assertIn("(max-width: 900px) and (max-height: 500px)", patch)
        self.assertIn("pbj-toolbar-mobile", patch)
        self.assertIn("pbj-toolbar-desktop", patch)


if __name__ == "__main__":
    unittest.main()
