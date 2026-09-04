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

    def test_installable_shell_removes_retired_offline_cache(self):
        manifest = json.loads(self.read("app/static/manifest.webmanifest"))
        self.assertEqual(manifest["orientation"], "any")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        base = self.read("app/templates/base.html")
        access = self.read("app/templates/access.html")
        self.assertIn("/ui.css?v=22", base)
        self.assertIn("/ui.css?v=22", access)
        self.assertIn('rel="manifest" href="/manifest.webmanifest"', base)
        self.assertIn('rel="manifest" href="/manifest.webmanifest"', access)
        for template in (base, access):
            self.assertIn("navigator.serviceWorker.getRegistrations()", template)
            self.assertIn("item.unregister()", template)
            self.assertIn("key.startsWith('pbj-shell-')", template)
            self.assertIn("caches.delete(key)", template)
            self.assertNotIn("serviceWorker.register", template)
        self.assertFalse((ROOT / "app" / "static" / "service-worker.js").exists())
        self.assertFalse((ROOT / "app" / "templates" / "offline.html").exists())

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
