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
        retired = {
            "/projects/{project_id}/editor",
            "/projects/{project_id}/openreel",
            "/api/projects/{project_id}/timeline",
            "/api/projects/{project_id}/timeline/transactions",
            "/api/projects/{project_id}/timeline/undo",
            "/api/projects/{project_id}/timeline/redo",
            "/api/projects/{project_id}/timeline/proposals",
            "/api/projects/{project_id}/timeline/proposals/{proposal_id}/apply",
            "/api/projects/{project_id}/timeline/proposals/{proposal_id}/reject",
            "/api/projects/{project_id}/assets/{asset_id}/preview",
            "/api/projects/{project_id}/assets/{asset_id}/waveform",
            "/api/projects/{project_id}/assets/{asset_id}/thumbnail/{index}",
            "/api/projects/{project_id}/assets",
            "/api/projects/{project_id}/exports",
            "/api/projects/{project_id}/exports/{export_id}",
        }
        self.assertTrue(retired.isdisjoint(route_paths), retired & route_paths)
        canonical = {
            "/projects/{project_id}/ready",
            "/projects/{project_id}/revise",
            "/projects/{project_id}/approve",
            "/projects/{project_id}/exports/{export_id}/progress",
            "/projects/{project_id}/exports/{export_id}/complete",
            "/projects/{project_id}/exports/{export_id}/download",
        }
        self.assertTrue(canonical.issubset(route_paths), canonical - route_paths)

    def test_runtime_launcher_starts_only_pbj(self):
        launcher = (ROOT_DIR / "start_app.command").read_text().casefold()
        self.assertIn("uvicorn app.main:app", launcher)
        self.assertNotIn("openreel", launcher)
        self.assertNotIn("pnpm", launcher)
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
