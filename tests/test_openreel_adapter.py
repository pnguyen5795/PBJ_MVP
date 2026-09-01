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
from app.openreel_adapter import (
    OPENREEL_ADAPTER_SCHEMA,
    OPENREEL_RENDER_RECEIPT_SCHEMA,
    OPENREEL_SNAPSHOT_SCHEMA,
    project_openreel,
)
from app.storage import JsonStore
from app.timeline.contracts import asset_from_raw, empty_timeline, refresh_hash
from app.timeline.storage import TimelineStore


class OpenReelProjectionTests(unittest.TestCase):
    def fixture(self):
        project_id = "project-20260830-a1b2c3"
        raw = {
            "file_id": "raw-001",
            "original_name": "portrait.mov",
            "stored_path": f"projects/{project_id}/raw/portrait.mov",
            "sha256": "a" * 64,
            "metadata": {
                "duration_seconds": 12,
                "has_audio": True,
                "width": 1080,
                "height": 1920,
            },
        }
        timeline = empty_timeline(project_id, [asset_from_raw(raw)])
        timeline["tracks"][0]["clips"] = [{
            "clip_id": "clip-001",
            "kind": "video",
            "asset_id": "raw-001",
            "source_in_us": 1_000_000,
            "source_out_us": 5_000_000,
            "timeline_start_frame": 30,
            "duration_frames": 120,
            "playback_rate": 1.0,
            "linked_group_id": "sync-001",
            "transform": {
                "mode": "fit",
                "x": 0.5,
                "y": 0.5,
                "scale": 1.0,
                "crop": {"preset": "1:1", "x": 0.2, "y": 0, "width": 0.6, "height": 1},
            },
        }]
        timeline["revision"] = 7
        refresh_hash(timeline)
        return {"project_id": project_id, "name": "Adapter fixture", "raw_files": [raw]}, timeline

    def test_projection_matches_openreel_project_shape_and_preserves_authority(self):
        project, timeline = self.fixture()
        result = project_openreel(project, timeline)
        self.assertEqual(result["schemaVersion"], OPENREEL_ADAPTER_SCHEMA)
        self.assertEqual(result["authority"]["revision"], 7)
        self.assertEqual(result["authority"]["timelineHash"], timeline["timeline_hash"])
        self.assertEqual(result["project"]["id"], project["project_id"])
        self.assertEqual(result["project"]["settings"]["frameRate"], 30)
        self.assertEqual(result["project"]["mediaLibrary"]["items"][0]["id"], "raw-001")
        self.assertNotIn("audio-original", {
            track["id"] for track in result["project"]["timeline"]["tracks"]
        })

        clip = result["project"]["timeline"]["tracks"][0]["clips"][0]
        self.assertEqual(clip["id"], "clip-001")
        self.assertEqual(clip["mediaId"], "raw-001")
        self.assertEqual(clip["startTime"], 1.0)
        self.assertEqual(clip["duration"], 4.0)
        self.assertEqual(clip["inPoint"], 1.0)
        self.assertEqual(clip["outPoint"], 5.0)
        self.assertEqual(clip["metadata"]["pbj"]["timelineStartFrame"], 30)
        self.assertEqual(clip["metadata"]["pbj"]["sourceOutUs"], 5_000_000)

    def test_projection_accepts_fractional_media_frame_rate(self):
        project, timeline = self.fixture()
        timeline["assets"][0]["media_metadata"]["frame_rate"] = "28300/947"
        result = project_openreel(project, timeline)
        self.assertAlmostEqual(
            result["project"]["mediaLibrary"]["items"][0]["metadata"]["frameRate"],
            28300 / 947,
        )

    def test_projection_endpoint_requires_ready_timeline_and_returns_project(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStore(Path(folder))
            project, timeline = self.fixture()
            style = store.create_style("Adapter style", [], {})
            project["style_id"] = style["style_id"]
            root = store.projects_dir / project["project_id"]
            root.mkdir(parents=True)
            store.write_json(root / "manifest.json", {**project, "status": "timeline_ready", "device_id": None})
            TimelineStore(store).initialize(project["project_id"], timeline)

            with patch.object(main_module, "store", store):
                client = TestClient(main_module.app)
                session = {"authorized": True, "owner": True, "device_id": "test-device"}
                signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
                client.cookies.set("session", signed)
                response = client.get(f"/api/projects/{project['project_id']}/openreel/project")
                client.close()

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["project"]["name"], "Adapter fixture")
            self.assertEqual(payload["authority"]["system"], "pbj")
            self.assertEqual(payload["authority"]["loadedFrom"], "first_timeline")

    def test_openreel_saves_whole_project_snapshot_without_mutating_source_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStore(Path(folder))
            project, timeline = self.fixture()
            style = store.create_style("Adapter style", [], {})
            project["style_id"] = style["style_id"]
            root = store.projects_dir / project["project_id"]
            root.mkdir(parents=True)
            store.write_json(root / "manifest.json", {**project, "status": "timeline_ready", "device_id": None})
            TimelineStore(store).initialize(project["project_id"], timeline)

            with patch.object(main_module, "store", store):
                client = TestClient(main_module.app)
                session = {"authorized": True, "owner": True, "device_id": "test-device"}
                signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
                client.cookies.set("session", signed)
                handoff = client.get(f"/api/projects/{project['project_id']}/openreel/project").json()
                edited = handoff["project"]
                edited["timeline"]["tracks"][0]["clips"][0]["duration"] = 3.0
                response = client.post(
                    handoff["authority"]["snapshotUrl"],
                    json={
                        "schema_version": OPENREEL_SNAPSHOT_SCHEMA,
                        "source_timeline_revision": handoff["authority"]["revision"],
                        "source_timeline_hash": handoff["authority"]["timelineHash"],
                        "project": edited,
                    },
                )
                latest = client.get(handoff["authority"]["latestSnapshotUrl"]).json()
                export_response = client.post(
                    handoff["authority"]["exportIntentUrl"],
                    json={
                        "snapshot_id": response.json()["snapshot_id"],
                        "approval_confirmation": True,
                    },
                )
                receipt = {
                    "schema_version": OPENREEL_RENDER_RECEIPT_SCHEMA,
                    "snapshot_id": response.json()["snapshot_id"],
                    "renderer": {"name": "openreel", "source_revision": "5f3c85e5"},
                    "output": {
                        "sha256": "b" * 64,
                        "size_bytes": 1_024,
                        "mime_type": "video/mp4",
                        "delivered_to_user": True,
                    },
                    "verification": {
                        "passed": True,
                        "checks": {
                            "render_completed": True,
                            "nonempty_output": True,
                            "project_identity": True,
                            "snapshot_identity": True,
                        },
                    },
                }
                completion = client.post(export_response.json()["completion_url"], json=receipt)
                completion_retry = client.post(export_response.json()["completion_url"], json=receipt)
                before_approval = store.project(project["project_id"])
                unconfirmed_approval = client.post(completion.json()["approval_url"], json={
                    "approval_confirmation": False,
                    "output_sha256": "b" * 64,
                })
                wrong_output_approval = client.post(completion.json()["approval_url"], json={
                    "approval_confirmation": True,
                    "output_sha256": "c" * 64,
                })
                approval = client.post(completion.json()["approval_url"], json={
                    "approval_confirmation": True,
                    "output_sha256": "b" * 64,
                })
                approval_retry = client.post(completion.json()["approval_url"], json={
                    "approval_confirmation": True,
                    "output_sha256": "b" * 64,
                })
                resumed = client.get(f"/api/projects/{project['project_id']}/openreel/project").json()
                source = client.get(f"/api/projects/{project['project_id']}/timeline").json()
                client.close()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(export_response.status_code, 200)
            self.assertEqual(export_response.json()["status"], "awaiting_openreel_render")
            self.assertEqual(completion.status_code, 200)
            self.assertEqual(completion.json()["status"], "render_complete_pending_approval")
            self.assertTrue(completion.json()["approval_required"])
            self.assertEqual(completion_retry.status_code, 200)
            self.assertNotIn("final_approval", before_approval)
            self.assertNotEqual(before_approval.get("status"), "approved")
            self.assertEqual(unconfirmed_approval.status_code, 422)
            self.assertEqual(wrong_output_approval.status_code, 422)
            self.assertEqual(approval.status_code, 200)
            self.assertTrue(approval.json()["approved"])
            self.assertEqual(approval_retry.status_code, 200)
            self.assertEqual(latest["openreel_project"]["timeline"]["tracks"][0]["clips"][0]["duration"], 3.0)
            self.assertEqual(resumed["project"]["timeline"]["tracks"][0]["clips"][0]["duration"], 3.0)
            self.assertEqual(resumed["authority"]["loadedFrom"], "latest_snapshot")
            self.assertEqual(resumed["authority"]["snapshotId"], response.json()["snapshot_id"])
            self.assertEqual(source["revision"], 7)
            self.assertEqual(source["timeline_hash"], timeline["timeline_hash"])
            export_record = store.project(project["project_id"])["latest_openreel_export_intent"]
            self.assertEqual(export_record["snapshot_id"], response.json()["snapshot_id"])
            self.assertEqual(export_record["render_owner"], "openreel")
            self.assertEqual(export_record["approval_owner"], "pbj")
            self.assertTrue((store.data_dir / export_record["snapshot_path"]).exists())
            self.assertTrue((store.data_dir / export_record["render_receipt_path"]).exists())
            self.assertEqual(export_record["output_sha256"], "b" * 64)
            manifest = store.project(project["project_id"])
            self.assertTrue(manifest["final_approval"]["approved"])
            self.assertEqual(manifest.get("status"), "approved")
            approved_examples = [
                item for item in store.list_approved_examples()
                if item.get("project_id") == project["project_id"]
            ]
            self.assertEqual(len(approved_examples), 1)
            self.assertEqual(approved_examples[0]["approved_openreel_project"]["id"], project["project_id"])
            approval_signals = [
                item for item in store.list_learning_signals(style["style_id"])
                if item.get("type") == "approved_openreel_export"
            ]
            self.assertEqual(len(approval_signals), 1)

    def test_openreel_restores_latest_snapshot_after_pbj_process_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            data_dir = Path(folder)
            initial_store = JsonStore(data_dir)
            project, timeline = self.fixture()
            style = initial_store.create_style("Adapter style", [], {})
            project["style_id"] = style["style_id"]
            root = initial_store.projects_dir / project["project_id"]
            root.mkdir(parents=True)
            initial_store.write_json(
                root / "manifest.json",
                {**project, "status": "timeline_ready", "device_id": None},
            )
            TimelineStore(initial_store).initialize(project["project_id"], timeline)

            session = {"authorized": True, "owner": True, "device_id": "test-device"}
            signed = TimestampSigner(settings.session_secret).sign(
                b64encode(json.dumps(session).encode())
            ).decode()

            with patch.object(main_module, "store", initial_store):
                client = TestClient(main_module.app)
                client.cookies.set("session", signed)
                handoff = client.get(
                    f"/api/projects/{project['project_id']}/openreel/project"
                ).json()
                edited = handoff["project"]
                edited["timeline"]["tracks"][0]["clips"][0]["duration"] = 2.5
                saved = client.post(
                    handoff["authority"]["snapshotUrl"],
                    json={
                        "schema_version": OPENREEL_SNAPSHOT_SCHEMA,
                        "source_timeline_revision": handoff["authority"]["revision"],
                        "source_timeline_hash": handoff["authority"]["timelineHash"],
                        "project": edited,
                    },
                )
                client.close()

            self.assertEqual(saved.status_code, 200)

            restarted_store = JsonStore(data_dir)
            with patch.object(main_module, "store", restarted_store):
                restarted_client = TestClient(main_module.app)
                restarted_client.cookies.set("session", signed)
                resumed = restarted_client.get(
                    f"/api/projects/{project['project_id']}/openreel/project"
                )
                restarted_client.close()

            self.assertEqual(resumed.status_code, 200)
            payload = resumed.json()
            self.assertEqual(payload["authority"]["loadedFrom"], "latest_snapshot")
            self.assertEqual(payload["authority"]["snapshotId"], saved.json()["snapshot_id"])
            self.assertEqual(
                payload["project"]["timeline"]["tracks"][0]["clips"][0]["duration"],
                2.5,
            )

    def test_openreel_export_requires_deliberate_approval_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStore(Path(folder))
            project, timeline = self.fixture()
            style = store.create_style("Adapter style", [], {})
            project["style_id"] = style["style_id"]
            root = store.projects_dir / project["project_id"]
            root.mkdir(parents=True)
            store.write_json(root / "manifest.json", {**project, "status": "timeline_ready", "device_id": None})
            TimelineStore(store).initialize(project["project_id"], timeline)
            with patch.object(main_module, "store", store):
                client = TestClient(main_module.app)
                session = {"authorized": True, "owner": True, "device_id": "test-device"}
                signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
                client.cookies.set("session", signed)
                handoff = client.get(f"/api/projects/{project['project_id']}/openreel/project").json()
                saved = client.post(handoff["authority"]["snapshotUrl"], json={
                    "schema_version": OPENREEL_SNAPSHOT_SCHEMA,
                    "source_timeline_revision": timeline["revision"],
                    "source_timeline_hash": timeline["timeline_hash"],
                    "project": handoff["project"],
                })
                rejected = client.post(handoff["authority"]["exportIntentUrl"], json={
                    "snapshot_id": saved.json()["snapshot_id"],
                    "approval_confirmation": False,
                })
                client.close()
            self.assertEqual(rejected.status_code, 422)
            self.assertIn("Confirm", rejected.json()["detail"])

    def test_openreel_completion_rejects_a_receipt_for_another_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store = JsonStore(Path(folder))
            project, timeline = self.fixture()
            style = store.create_style("Adapter style", [], {})
            project["style_id"] = style["style_id"]
            root = store.projects_dir / project["project_id"]
            root.mkdir(parents=True)
            store.write_json(root / "manifest.json", {**project, "status": "timeline_ready", "device_id": None})
            TimelineStore(store).initialize(project["project_id"], timeline)
            with patch.object(main_module, "store", store):
                client = TestClient(main_module.app)
                session = {"authorized": True, "owner": True, "device_id": "test-device"}
                signed = TimestampSigner(settings.session_secret).sign(b64encode(json.dumps(session).encode())).decode()
                client.cookies.set("session", signed)
                handoff = client.get(f"/api/projects/{project['project_id']}/openreel/project").json()
                saved = client.post(handoff["authority"]["snapshotUrl"], json={
                    "schema_version": OPENREEL_SNAPSHOT_SCHEMA,
                    "source_timeline_revision": timeline["revision"],
                    "source_timeline_hash": timeline["timeline_hash"],
                    "project": handoff["project"],
                })
                intent = client.post(handoff["authority"]["exportIntentUrl"], json={
                    "snapshot_id": saved.json()["snapshot_id"],
                    "approval_confirmation": True,
                })
                rejected = client.post(intent.json()["completion_url"], json={
                    "schema_version": OPENREEL_RENDER_RECEIPT_SCHEMA,
                    "snapshot_id": "snapshot-wrong",
                })
                client.close()
            self.assertEqual(rejected.status_code, 422)
            self.assertIn("different project snapshot", rejected.json()["detail"])
            self.assertEqual(
                store.project(project["project_id"])["latest_openreel_export_intent"]["status"],
                "awaiting_openreel_render",
            )


if __name__ == "__main__":
    unittest.main()
