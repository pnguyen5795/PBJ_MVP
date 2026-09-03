import hashlib
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


class TroyFaceliftFoundationTests(unittest.TestCase):
    def test_foundation_is_loaded_by_authenticated_and_access_shells(self):
        base = (ROOT_DIR / "app" / "templates" / "base.html").read_text()
        access = (ROOT_DIR / "app" / "templates" / "access.html").read_text()
        self.assertIn("/ui.css?v=22", base)
        self.assertIn("/ui.css?v=22", access)

    def test_black_and_purple_mobile_tokens_are_present(self):
        css = (ROOT_DIR / "app" / "static" / "troy-foundation.css").read_text()
        self.assertIn("--pbj-accent: #8b5cf6", css)
        self.assertIn("background: #000", css)
        self.assertIn("--pbj-button-height: 56px", css)
        self.assertIn("--pbj-tap-min: 44px", css)
        self.assertIn("env(safe-area-inset-top", css)
        self.assertIn("prefers-reduced-motion: reduce", css)

    def test_approved_sandwich_assets_match_troy_source_hashes(self):
        expected = {
            "sandwich-logo.png": "a87a9b0ee2ef8c767e95954ae39f0a4543e1c0ea97c6d73f55b7c73e3853b9d4",
            "sandwich/bottom-bread.png": "1ec8afd2d40af159e431bd18d270801b75a1cddbc3f512bb27884603e68e4a0f",
            "sandwich/jelly.png": "5d83476119cd99830059d89a690e45e37239c2fb8bb4ab400f30d8d285999f61",
            "sandwich/peanut-butter.png": "19c09aee9843350627885a5ca765681722870da51ba0635ee635887e3211b9f0",
            "sandwich/top-bread.png": "f67e164a3bb8934d8769105322b4c6176530a51d2b406abe071ff67b37959901",
        }
        brand_root = ROOT_DIR / "app" / "static" / "brand"
        for relative_path, expected_hash in expected.items():
            actual_hash = hashlib.sha256((brand_root / relative_path).read_bytes()).hexdigest()
            self.assertEqual(actual_hash, expected_hash, relative_path)

    def test_service_worker_precaches_foundation_and_artwork(self):
        worker = (ROOT_DIR / "app" / "static" / "service-worker.js").read_text()
        self.assertIn("/static/troy-foundation.css", worker)
        self.assertIn("/static/brand/sandwich-logo.png", worker)
        self.assertIn("/static/brand/sandwich/top-bread.png", worker)

    def test_facelift_contract_excludes_troy_studio_and_mock_logic(self):
        plan = (ROOT_DIR / "docs" / "TROY_FACELIFT_PLAN.md").read_text()
        self.assertIn("PBJ has no manual editing Studio", plan)
        self.assertIn("rendered rough-cut review", plan)
        self.assertIn("Studio | Excluded", plan)
        self.assertIn("simulated rendering", plan)


if __name__ == "__main__":
    unittest.main()
