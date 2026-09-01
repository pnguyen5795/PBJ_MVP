import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import ROOT_DIR, env_flag, settings
from app.main import app


class TimelinePhaseZeroTests(TestCase):
    def test_feature_flag_parser_is_explicit(self):
        for value in ("1", "true", "TRUE", "yes", "On"):
            with patch.dict(os.environ, {"PBJ_TEST_TIMELINE_FLAG": value}):
                self.assertTrue(env_flag("PBJ_TEST_TIMELINE_FLAG"))
        for value in ("0", "false", "no", "off", "unexpected"):
            with patch.dict(os.environ, {"PBJ_TEST_TIMELINE_FLAG": value}):
                self.assertFalse(env_flag("PBJ_TEST_TIMELINE_FLAG", True))

    def test_retired_timeline_editor_flag_is_absent(self):
        example = (ROOT_DIR / ".env.example").read_text()
        self.assertNotIn("PBJ_TIMELINE_EDITOR", example)
        self.assertFalse(hasattr(app.state, "timeline_editor_enabled"))

    def test_old_editor_assets_and_route_are_removed(self):
        self.assertFalse((ROOT_DIR / "frontend" / "editor").exists())
        self.assertFalse((ROOT_DIR / "app" / "static" / "editor").exists())
        with TestClient(app) as client:
            response = client.get("/static/editor/index.html")
        self.assertEqual(response.status_code, 404)

        route_paths = {getattr(route, "path", "") for route in app.routes}
        self.assertNotIn("/projects/{project_id}/editor", route_paths)
        self.assertIn("/projects/{project_id}/ready", route_paths)
        self.assertIn("/projects/{project_id}/openreel", route_paths)

    def test_runtime_launcher_starts_pbj_and_openreel(self):
        launcher = (ROOT_DIR / "start_app.command").read_text().casefold()
        self.assertIn("uvicorn app.main:app", launcher)
        self.assertIn("@openreel/web dev", launcher)
        self.assertIn("openreel_port=5173", launcher)
        self.assertIn("trap cleanup", launcher)
        self.assertTrue(os.access(ROOT_DIR / "start_app.command", os.X_OK))

    def test_third_party_provenance_is_machine_readable(self):
        manifest_path = ROOT_DIR / "docs" / "third_party_sources.json"
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["schema_version"], 1)
        self.assertTrue(manifest["dependencies"])
        self.assertTrue(manifest["reviewed_sources"])
        self.assertTrue(all(source["status"] in {
            "reviewed_not_imported", "adapted_integration_overlay"
        } for source in manifest["reviewed_sources"]))
        self.assertTrue(manifest["adapted_sources"])


if __name__ == "__main__":
    import unittest

    unittest.main()
