import json
import tempfile
import unittest
from base64 import b64encode
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import app.main as main_module
from app.config import settings
from app.providers import PROVIDERS, PegasusAnalyzer, readiness_for_provider
from app.storage import JsonStore


class LegacyProviderCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name) / "data")
        self.style = self.store.create_style("Current recipe", [], {})
        self.store_patch = patch.object(main_module, "store", self.store)
        self.store_patch.start()
        self.client = TestClient(main_module.app)
        session = {"authorized": True, "owner": True, "device_id": "test-device"}
        signed = TimestampSigner(settings.session_secret).sign(
            b64encode(json.dumps(session).encode())
        ).decode()
        self.client.cookies.set("session", signed)

    def tearDown(self):
        self.client.close()
        self.store_patch.stop()
        self.temp.cleanup()

    def create_legacy_project(self):
        return self.store.create_project(
            "Historical project", self.style["style_id"], "gemini",
            "Make a short cut", 30, [], {}, device_id="test-device",
        )

    def record_legacy_asset(self, owner_dir, file_id="raw-001"):
        self.store.record_remote_asset(
            owner_dir, "gemini", file_id,
            {"id": "files/private-legacy-id", "status": "ready", "retained": True},
        )

    def test_retired_provider_is_not_restored_and_has_safe_readiness(self):
        self.assertEqual(PROVIDERS, {"pegasus": PegasusAnalyzer})
        readiness = readiness_for_provider("gemini")
        self.assertFalse(readiness.configured)
        self.assertEqual(readiness.provider, "unsupported")
        self.assertNotIn("gemini", readiness.message.lower())

    def test_remote_cleanup_for_retired_provider_is_classified_without_claiming_deletion(self):
        self.record_legacy_asset(self.store.style_dir(self.style["style_id"]), "reference-001")

        response = self.client.post(
            "/assets/delete",
            data={
                "owner_type": "style", "owner_id": self.style["style_id"],
                "provider": "gemini", "asset_id": "files/private-legacy-id",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertNotIn("gemini", response.text.lower())
        self.assertNotIn("private-legacy-id", response.text)
        saved = self.store.remote_assets()[0]
        self.assertEqual(saved["status"], "cleanup_unavailable")
        self.assertTrue(saved["retained"])
        self.assertEqual(saved["cleanup"]["status"], "unsupported_provider")
        self.assertNotIn("private-legacy-id", str(saved["cleanup"]))
        self.assertEqual(self.store.remote_cleanup_tombstones(), [])
        assets = self.client.get("/assets")
        self.assertIn("Retired provider copy", assets.text)
        self.assertIn("cleanup unavailable", assets.text)
        self.assertNotIn("private-legacy-id", assets.text)
        self.assertNotIn("gemini", assets.text.lower())

    def test_project_with_retired_remote_asset_can_still_be_deleted_locally(self):
        project = self.create_legacy_project()
        self.record_legacy_asset(self.store.project_dir(project["project_id"]))

        response = self.client.post(
            "/projects/%s/delete" % project["project_id"], follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("remote_cleanup=unavailable", response.headers["location"])
        self.assertFalse(self.store.project_dir(project["project_id"]).exists())
        tombstones = self.store.remote_cleanup_tombstones()
        self.assertEqual(len(tombstones), 1)
        self.assertEqual(tombstones[0]["status"], "cleanup_unavailable")
        self.assertEqual(tombstones[0]["remote_retention"], "unknown")
        self.assertEqual(tombstones[0]["local_context"], "project_deletion")
        self.assertEqual(tombstones[0]["remote_asset_id"], "files/private-legacy-id")
        serialized = json.dumps(tombstones)
        self.assertNotIn(project["project_id"], serialized)

        dashboard = self.client.get(response.headers["location"])
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("remote cleanup could not be verified", dashboard.text.casefold())
        self.assertIn("may still exist", dashboard.text)
        assets = self.client.get("/assets")
        self.assertEqual(assets.status_code, 200)
        self.assertIn("Unverified remote cleanup", assets.text)
        self.assertIn("Recorded during project deletion", assets.text)
        self.assertNotIn("private-legacy-id", assets.text)
        self.assertNotIn(project["project_id"], assets.text)
        self.assertNotIn("gemini", assets.text.lower())

    def test_style_with_retired_remote_asset_can_still_be_archived_locally(self):
        historical = self.store.create_style("Historical recipe", [], {})
        self.record_legacy_asset(
            self.store.style_dir(historical["style_id"]), "reference-001",
        )

        response = self.client.post(
            "/styles/%s/delete" % historical["style_id"], follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("remote_cleanup=unavailable", response.headers["location"])
        self.assertFalse(self.store.style_dir(historical["style_id"]).exists())
        archives = list(self.store.deleted_styles_dir.glob(historical["style_id"] + "-*"))
        self.assertEqual(len(archives), 1)
        saved = self.store.read_json(archives[0] / "remote_assets.json")["assets"][0]
        self.assertEqual(saved["status"], "cleanup_unavailable")
        self.assertTrue(saved["retained"])
        tombstones = self.store.remote_cleanup_tombstones()
        self.assertEqual(len(tombstones), 1)
        self.assertEqual(tombstones[0]["local_context"], "style_archive")
        self.assertEqual(tombstones[0]["remote_asset_id"], "files/private-legacy-id")
        serialized = json.dumps(tombstones)
        self.assertNotIn(historical["style_id"], serialized)

        welcome = self.client.get(response.headers["location"])
        self.assertEqual(welcome.status_code, 200)
        self.assertIn("Recipe archived locally", welcome.text)
        self.assertIn("remote cleanup could not be verified", welcome.text.casefold())
        assets = self.client.get("/assets")
        self.assertEqual(assets.status_code, 200)
        self.assertIn("Recorded during recipe archive", assets.text)
        self.assertNotIn("private-legacy-id", assets.text)
        self.assertNotIn(historical["style_id"], assets.text)
        self.assertNotIn("gemini", assets.text.lower())

    def test_cleanup_tombstone_is_minimal_and_deduplicated(self):
        first = self.store.record_remote_cleanup_tombstone(
            "project", "project-20260903-abcdef", "gemini", "files/private-id",
            local_context="project_deletion",
        )
        second = self.store.record_remote_cleanup_tombstone(
            "project", "project-20260903-abcdef", "gemini", "files/private-id",
            local_context="project_deletion",
        )

        self.assertEqual(first["cleanup_id"], second["cleanup_id"])
        self.assertEqual(len(self.store.remote_cleanup_tombstones()), 1)
        serialized = json.dumps(first)
        self.assertNotIn("project-20260903-abcdef", serialized)
        self.assertEqual(first["remote_asset_id"], "files/private-id")

    def test_historical_project_brief_and_retry_fail_safely_instead_of_keyerror(self):
        project = self.create_legacy_project()

        response = self.client.post(
            "/projects/%s/brief" % project["project_id"],
            data={"prompt": "Make a 30 second cut", "target_seconds": "30"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("gemini", response.text.lower())
        self.assertEqual(self.store.project(project["project_id"])["status"], "footage_uploaded")

        self.store.update_project(project["project_id"], status="analysis_failed")
        response = self.client.post("/projects/%s/retry" % project["project_id"])
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("gemini", response.text.lower())
        self.assertEqual(self.store.project(project["project_id"])["status"], "analysis_failed")

    def test_historical_upload_session_fails_safely_instead_of_keyerror(self):
        upload = self.store.create_upload_session(
            "Historical upload", self.style["style_id"], "gemini",
            "Make a 30 second cut", 30, device_id="test-device",
        )
        self.store.update_upload_session(upload["session_id"], status="ready_for_brief")

        response = self.client.post(
            "/projects/new/brief", data={"session_id": upload["session_id"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("gemini", response.text.lower())
        self.assertEqual(
            self.store.upload_session(upload["session_id"])["status"], "ready_for_brief",
        )


if __name__ == "__main__":
    unittest.main()
