from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from app.ffmpeg_runtime import ManagedProcessResult
from app.media import inspect_video


class MediaInspectionTests(unittest.TestCase):
    def test_rotation_and_vfr_metadata_are_detected(self):
        payload = '{"format":{"duration":"2"},"streams":[{"codec_type":"video","codec_name":"hevc","width":1920,"height":1080,"avg_frame_rate":"24000/1001","r_frame_rate":"30/1","side_data_list":[{"rotation":-90}]},{"codec_type":"audio","codec_name":"aac","sample_rate":"44100","channels":2}]}'
        with patch("app.media.shutil.which", return_value="ffprobe"), patch(
            "app.media.run_media_process",
            return_value=ManagedProcessResult(
                returncode=0, stdout=payload, stderr="",
            ),
        ):
            metadata = inspect_video(Path("iphone.mov"))
        self.assertEqual(metadata["rotation"], -90)
        self.assertTrue(metadata["variable_frame_rate"])
        self.assertEqual(metadata["audio_sample_rate"], 44100)

    def test_ffprobe_failure_returns_a_stable_privacy_safe_category(self):
        private_path = Path("/private/uploads/secret-family-video.mov")
        failures = (
            subprocess.CalledProcessError(
                1, ["ffprobe", str(private_path)],
                stderr="parser failed on secret-family-video.mov",
            ),
            OSError("could not execute ffprobe for secret-family-video.mov"),
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "secret-family-video.mov"),
        )

        for failure in failures:
            with (
                self.subTest(error_type=type(failure).__name__),
                patch("app.media.shutil.which", return_value="/usr/bin/ffprobe"),
                patch("app.media.run_media_process", side_effect=failure),
            ):
                result = inspect_video(private_path)

            self.assertEqual(result, {"inspection_error": "media_inspection_failed"})
            self.assertNotIn("secret-family-video.mov", str(result))


if __name__ == "__main__":
    unittest.main()
