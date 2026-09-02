from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
import shutil
import subprocess

from app.media import inspect_video
from app.storage import JsonStore, sha256
from app.timeline.contracts import asset_from_raw, empty_timeline, refresh_hash, samples_from_frames
from app.timeline.export import TimelineExportService, TimelineFFmpegCompiler
from app.timeline.storage import TimelineStore


def populated_timeline(project_id, raw):
    timeline = empty_timeline(project_id, [asset_from_raw(raw)])
    video = timeline["tracks"][0]
    audio = timeline["tracks"][2]
    video["clips"] = [{
        "clip_id": "video-001", "kind": "video", "asset_id": raw["file_id"],
        "source_in_us": 0, "source_out_us": 1_000_000, "timeline_start_frame": 0,
        "duration_frames": 30, "playback_rate": 1.0, "linked_group_id": "link-1",
        "transform": {"mode": "fit", "x": .5, "y": .5, "scale": 1.0},
    }]
    audio["clips"] = [{
        "clip_id": "audio-001", "kind": "audio", "asset_id": raw["file_id"],
        "source_in_us": 0, "source_out_us": 1_000_000, "timeline_start_frame": 0,
        "duration_frames": 30, "timeline_start_sample": 0, "duration_samples": samples_from_frames(30),
        "playback_rate": 1.0, "linked_group_id": "link-1", "volume": 1.0, "muted": False,
        "fades": {"in_frames": 0, "out_frames": 0},
    }]
    refresh_hash(timeline)
    return timeline


@skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class TimelineCompilerTests(TestCase):
    def test_compiler_reads_original_assets_and_produces_verified_output(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id = "project-20260827-aaa111"
            root = store.projects_dir / project_id
            source = root / "raw" / "source.mp4"; source.parent.mkdir(parents=True)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=purple:s=320x240:r=30:d=1", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)], check=True)
            raw = {"file_id": "raw-001", "original_name": "source.mp4", "stored_path": str(source.relative_to(store.data_dir)), "sha256": sha256(source), "analysis_status": "complete", "metadata": inspect_video(source)}
            project = {"project_id": project_id, "raw_files": [raw]}; store.write_json(root / "manifest.json", project)
            timeline = populated_timeline(project_id, raw)
            output = root / "exports" / "test" / "output.mp4"
            result = TimelineFFmpegCompiler(store).render(project, timeline, output)
            self.assertTrue(result["verification"]["passed"])
            self.assertIn(str(source.resolve()), result["command"])
            self.assertNotIn("/proxies/", " ".join(result["command"]))

    def test_compiler_supports_crossfade_overlay_and_mixed_audio(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data"); project_id = "project-20260827-abc999"
            root = store.projects_dir / project_id; source = root / "raw" / "source.mp4"; source.parent.mkdir(parents=True)
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1.2", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)], check=True)
            raw = {"file_id": "raw-001", "original_name": "source.mp4", "stored_path": str(source.relative_to(store.data_dir)), "sha256": sha256(source), "analysis_status": "complete", "metadata": inspect_video(source)}
            project = {"project_id": project_id, "raw_files": [raw]}; store.write_json(root / "manifest.json", project)
            timeline = empty_timeline(project_id, [asset_from_raw(raw)]); main, overlay, audio = timeline["tracks"]
            transform = {"mode": "fit", "x": .5, "y": .5, "scale": 1.0}
            main["clips"] = [
                {"clip_id":"v1","kind":"video","asset_id":"raw-001","source_in_us":0,"source_out_us":600_000,"timeline_start_frame":0,"duration_frames":18,"playback_rate":1.0,"linked_group_id":None,"transform":transform},
                {"clip_id":"v2","kind":"video","asset_id":"raw-001","source_in_us":600_000,"source_out_us":1_200_000,"timeline_start_frame":12,"duration_frames":18,"playback_rate":1.0,"linked_group_id":None,"transform":transform},
            ]
            overlay["clips"] = [{"clip_id":"pip","kind":"video","asset_id":"raw-001","source_in_us":0,"source_out_us":200_000,"timeline_start_frame":6,"duration_frames":6,"playback_rate":1.0,"linked_group_id":None,"transform":{"mode":"fill","x":.8,"y":.2,"scale":.3}}]
            audio["clips"] = [{"clip_id":"a1","kind":"audio","asset_id":"raw-001","source_in_us":0,"source_out_us":1_000_000,"timeline_start_frame":0,"duration_frames":30,"timeline_start_sample":0,"duration_samples":samples_from_frames(30),"playback_rate":1.0,"linked_group_id":None,"volume":.8,"muted":False,"fades":{"in_frames":3,"out_frames":3}}]
            timeline["transitions"] = [{"transition_id":"t1","type":"crossfade","from_clip_id":"v1","to_clip_id":"v2","duration_frames":6}]
            refresh_hash(timeline)
            output = root / "exports" / "complex" / "output.mp4"
            result = TimelineFFmpegCompiler(store).render(project, timeline, output)
            self.assertTrue(result["verification"]["passed"])
            graph = result["command"][result["command"].index("-filter_complex") + 1]
            self.assertIn("xfade", graph); self.assertIn("overlay=", graph); self.assertIn("amix", graph)

    def test_compiler_applies_selected_clip_crop_before_canvas_fit(self):
        clip = {
            "source_in_us": 0, "source_out_us": 1_000_000, "playback_rate": 1,
            "transform": {"mode": "fit", "x": .5, "y": .5, "scale": 1,
                          "crop": {"preset": "1:1", "x": .21875, "y": 0, "width": .5625, "height": 1}},
        }
        graph = TimelineFFmpegCompiler._video_filter(0, clip, {"width": 1080, "height": 1920, "background": "black"}, "v0")
        self.assertIn("crop=floor(iw*0.5625/2)*2:floor(ih*1/2)*2", graph)
        self.assertLess(graph.index("crop="), graph.index("scale=1080:1920"))


class FakeCompiler:
    def render(self, project, timeline, output):
        output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b"verified-export")
        return {"command": ["ffmpeg", "-i", "original.mov", str(output)], "elapsed_seconds": .1,
                "verification": {"passed": True, "checks": {"fixture": {"required": True, "status": "passed"}}}}


class FailingCompiler:
    def render(self, project, timeline, output):
        raise RuntimeError("fixture export failure")


class TimelineApprovalLearningTests(TestCase):
    def test_export_history_is_oldest_first_and_can_filter_completed_versions(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id = "project-20260901-abc123"
            root = store.projects_dir / project_id
            store.write_json(root / "manifest.json", {"project_id": project_id})
            for export_id, status, created_at in (
                ("export-2", "complete", "2026-09-01T00:00:02+00:00"),
                ("export-1", "complete", "2026-09-01T00:00:01+00:00"),
                ("export-3", "failed", "2026-09-01T00:00:03+00:00"),
            ):
                store.write_json(root / "exports" / export_id / "export.json", {
                    "export_id": export_id, "status": status, "created_at": created_at,
                })
            service = TimelineExportService(store, compiler=FakeCompiler())
            self.assertEqual([item["export_id"] for item in service.records(project_id)], ["export-1", "export-2", "export-3"])
            self.assertEqual([item["export_id"] for item in service.records(project_id, completed_only=True)], ["export-1", "export-2"])

    def test_successful_export_approves_once_and_failed_export_cannot(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-bbb222"; style_root = store.styles_dir / style_id; style_root.mkdir(parents=True)
            store.write_json(style_root / "profile.json", {"style_id": style_id, "label": "Test", "recipe_version": "1.0.0", "recipe": {"rules": []}})
            project_id = "project-20260827-ccc333"; root = store.projects_dir / project_id; root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "original_name": "source.mov", "stored_path": "projects/%s/raw/source.mov" % project_id, "sha256": "b" * 64, "analysis_status": "complete", "metadata": {"duration_seconds": 2, "has_audio": True}}
            recipe_path = root / "recipe_snapshot.json"; store.write_json(recipe_path, {"rules": []})
            project = {"project_id": project_id, "name": "Learning", "style_id": style_id, "recipe_version": "1.0.0", "recipe_snapshot_path": str(recipe_path.relative_to(store.data_dir)), "device_id": "device-1", "prompt": "Short cut", "target_duration_seconds": 1, "raw_files": [raw], "status": "timeline_ready", "content_map": {}, "timeline_revision_prompts": []}
            store.write_json(root / "manifest.json", project)
            timeline = populated_timeline(project_id, raw); timelines = TimelineStore(store); timelines.initialize(project_id, timeline)
            store.update_project(project_id, initial_timeline_path=str((timelines.root(project_id) / "snapshots" / "initial-ai.json").relative_to(store.data_dir)))
            service = TimelineExportService(store, compiler=FakeCompiler())
            first = service.create(project_id, timeline["timeline_hash"], approve_on_success=True, approval_confirmation=True)
            completed = service.run(project_id, first["export_id"])
            self.assertEqual(completed["status"], "complete")
            self.assertTrue(store.project(project_id)["final_approval"]["approved"])
            signals = [item for item in store.list_learning_signals(style_id) if item.get("type") == "approved_timeline_export"]
            self.assertEqual(len(signals), 1)
            second = service.create(project_id, timeline["timeline_hash"], approve_on_success=True, approval_confirmation=True)
            service.run(project_id, second["export_id"])
            signals = [item for item in store.list_learning_signals(style_id) if item.get("type") == "approved_timeline_export"]
            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0]["export_id"], second["export_id"])
            self.assertEqual(len([item for item in store.list_approved_examples() if item.get("project_id") == project_id]), 1)

    def test_failed_export_unlocks_editor_and_never_approves(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-ddd444"; style_root = store.styles_dir / style_id; style_root.mkdir(parents=True)
            store.write_json(style_root / "profile.json", {"style_id": style_id, "recipe_version": "1.0.0", "recipe": {"rules": []}})
            project_id = "project-20260827-eee555"; root = store.projects_dir / project_id; root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "original_name": "source.mov", "stored_path": "projects/%s/raw/source.mov" % project_id, "sha256": "c" * 64, "analysis_status": "complete", "metadata": {"duration_seconds": 2, "has_audio": True}}
            store.write_json(root / "recipe_snapshot.json", {"rules": []})
            store.write_json(root / "manifest.json", {"project_id": project_id, "style_id": style_id, "recipe_version": "1.0.0", "recipe_snapshot_path": "projects/%s/recipe_snapshot.json" % project_id, "raw_files": [raw], "status": "timeline_ready"})
            timeline = populated_timeline(project_id, raw); TimelineStore(store).initialize(project_id, timeline)
            service = TimelineExportService(store, compiler=FailingCompiler())
            export = service.create(project_id, timeline["timeline_hash"], approve_on_success=True, approval_confirmation=True)
            with self.assertRaises(RuntimeError):
                service.run(project_id, export["export_id"])
            project = store.project(project_id)
            self.assertEqual(project["status"], "export_failed")
            self.assertFalse(project["editor_read_only"])
            self.assertFalse(project.get("final_approval", {}).get("approved", False))
            self.assertEqual(service.record(project_id, export["export_id"])["status"], "failed")


if __name__ == "__main__":
    import unittest
    unittest.main()
