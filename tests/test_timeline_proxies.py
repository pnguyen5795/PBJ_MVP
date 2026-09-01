from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
import shutil
import subprocess
from types import SimpleNamespace

from app.media import inspect_video
from app.storage import JsonStore, sha256
from app.timeline.proxies import PROXY_PROFILE_VERSION, ProxyPipeline


@skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class TimelineProxyTests(TestCase):
    def test_proxy_pipeline_is_per_source_cached_and_browser_safe(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id = "project-20260827-a1b2c3"
            project_root = store.projects_dir / project_id
            source = project_root / "raw" / "source.mp4"
            source.parent.mkdir(parents=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=purple:s=640x360:r=24:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
            ], check=True)
            raw = {
                "file_id": "raw-001", "original_name": "source.mp4",
                "stored_path": str(source.relative_to(store.data_dir)), "sha256": sha256(source),
                "metadata": inspect_video(source), "analysis_status": "complete",
            }
            project = {"project_id": project_id, "raw_files": [raw]}
            store.write_json(project_root / "manifest.json", project)
            pipeline = ProxyPipeline(store)
            first = pipeline.ensure_project(project)
            second = pipeline.ensure_project(project)
            self.assertEqual(first["assets"][0]["profile_version"], PROXY_PROFILE_VERSION)
            self.assertFalse(first["assets"][0]["combined_timeline_render"])
            self.assertTrue(second["assets"][0]["cache_hit"])
            preview = store.resolve_data_path(first["assets"][0]["preview_path"])
            metadata = inspect_video(preview)
            self.assertEqual(metadata["video_codec"], "h264")
            self.assertEqual(metadata["audio_sample_rate"], 48000)
            self.assertEqual(metadata["frame_rate"], "30/1")

    @skipUnless("libx265" in subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout, "HEVC encoder is required")
    def test_iphone_like_hevc_hdr_and_mixed_audio_become_browser_safe(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data"); project_id = "project-20260827-f1e2d3"
            root = store.projects_dir / project_id; source = root / "raw" / "iphone.mov"; source.parent.mkdir(parents=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=s=160x90:r=30:d=0.5",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.5",
                "-c:v", "libx265", "-x265-params", "log-level=error", "-pix_fmt", "yuv420p10le",
                "-color_trc", "smpte2084", "-color_primaries", "bt2020", "-colorspace", "bt2020nc",
                "-c:a", "aac", "-shortest", str(source),
            ], check=True)
            metadata = inspect_video(source); metadata["color_transfer"] = "smpte2084"
            raw = {"file_id": "raw-001", "original_name": "iphone.mov", "stored_path": str(source.relative_to(store.data_dir)), "sha256": sha256(source), "metadata": metadata, "analysis_status": "complete"}
            store.write_json(root / "manifest.json", {"project_id": project_id, "raw_files": [raw]})
            manifest = ProxyPipeline(store).ensure_asset(project_id, raw)
            preview = inspect_video(store.resolve_data_path(manifest["preview_path"]))
            self.assertEqual(preview["video_codec"], "h264")
            self.assertEqual(preview["audio_sample_rate"], 48000)
            self.assertEqual(preview["frame_rate"], "30/1")

    def test_rotation_and_vfr_metadata_are_detected(self):
        payload = '{"format":{"duration":"2"},"streams":[{"codec_type":"video","codec_name":"hevc","width":1920,"height":1080,"avg_frame_rate":"24000/1001","r_frame_rate":"30/1","side_data_list":[{"rotation":-90}]},{"codec_type":"audio","codec_name":"aac","sample_rate":"44100","channels":2}]}'
        with patch("app.media.shutil.which", return_value="ffprobe"), patch("app.media.subprocess.run", return_value=SimpleNamespace(stdout=payload)):
            metadata = inspect_video(Path("iphone.mov"))
        self.assertEqual(metadata["rotation"], -90)
        self.assertTrue(metadata["variable_frame_rate"])
        self.assertEqual(metadata["audio_sample_rate"], 44100)


if __name__ == "__main__":
    import unittest
    unittest.main()
