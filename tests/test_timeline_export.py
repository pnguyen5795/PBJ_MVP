from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from io import BytesIO
import json
import signal
import shutil
import subprocess
import sys
import time

import app.ffmpeg_runtime as ffmpeg_runtime
import app.timeline.export as timeline_export
from app.media import inspect_video
from app.storage import JsonStore, sha256
from app.timeline.contracts import asset_from_raw, empty_timeline, refresh_hash, samples_from_frames
from app.timeline.export import TimelineCompileError, TimelineExportService, TimelineFFmpegCompiler
from app.timeline.storage import TimelineStore


def setUpModule():
    ffmpeg_runtime.start_media_process_runtime()


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
    def test_hosted_mode_always_bounds_ffmpeg_concurrency(self):
        with patch.dict("os.environ", {"PBJ_HOSTED_MODE": "true", "PBJ_LOW_MEMORY_MODE": "false"}):
            from app.ffmpeg_runtime import low_memory_mode
            self.assertTrue(low_memory_mode())

    def test_render_platform_marker_always_bounds_ffmpeg_concurrency(self):
        with patch.dict("os.environ", {
            "RENDER": "true",
            "PBJ_HOSTED_MODE": "false",
            "PBJ_LOW_MEMORY_MODE": "false",
        }):
            from app.ffmpeg_runtime import low_memory_mode
            self.assertTrue(low_memory_mode())

    def test_hosted_low_memory_command_bounds_ffmpeg_workers(self):
        with TemporaryDirectory() as folder, patch.dict("os.environ", {"PBJ_LOW_MEMORY_MODE": "true"}):
            store = JsonStore(Path(folder) / "data")
            project_id = "project-20260902-memory"
            source = store.projects_dir / project_id / "raw" / "source.mp4"
            source.parent.mkdir(parents=True); source.write_bytes(b"fixture")
            raw = {"file_id": "raw-001", "stored_path": str(source.relative_to(store.data_dir)),
                   "sha256": "a" * 64, "metadata": {"duration_seconds": 1, "has_audio": True}}
            timeline = populated_timeline(project_id, raw)
            command = TimelineFFmpegCompiler(store).compile_command(
                {"project_id": project_id, "raw_files": [raw]}, timeline, source.parent / "output.mp4",
            )
            self.assertIn("-filter_complex_threads", command)
            self.assertIn("threads=1:lookahead_threads=1:sync-lookahead=0", command)
            self.assertEqual(command[command.index("-threads") + 1], "1")
            self.assertEqual(command[command.index("-preset") + 1], "medium")
            self.assertNotIn("-tune", command)
            self.assertEqual(command.count("-probesize"), 2)
            self.assertEqual(command.count("-analyzeduration"), 2)
            self.assertIn("-nostats", command)
            self.assertEqual(command[command.index("-loglevel") + 1], "error")

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


class FFmpegProcessReliabilityTests(TestCase):
    def test_render_timeout_is_generous_duration_based_and_configurable(self):
        env_name = timeline_export.RENDER_TIMEOUT_FLOOR_ENV
        with patch.dict("os.environ", {env_name: "600"}):
            self.assertEqual(timeline_export.render_timeout_seconds(60), 600)
            self.assertEqual(timeline_export.render_timeout_seconds(90), 810)
            self.assertEqual(timeline_export.render_timeout_seconds(180), 1620)
        for invalid in ("not-a-number", "0", "-10", "59"):
            with self.subTest(invalid=invalid), patch.dict("os.environ", {env_name: invalid}):
                self.assertEqual(timeline_export.render_timeout_seconds(60), 600)
        with patch.dict("os.environ", {env_name: "900"}):
            self.assertEqual(timeline_export.render_timeout_seconds(60), 900)

    def test_compiler_passes_program_duration_to_process_timeout(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            raw = {
                "file_id": "raw-001", "stored_path": "unused.mov", "sha256": "a" * 64,
                "metadata": {"duration_seconds": 1, "has_audio": True},
            }
            timeline = populated_timeline("project-timeout", raw)
            compiler = TimelineFFmpegCompiler(store)
            output = Path(folder) / "output.mp4"
            with (
                patch.object(compiler, "compile_command", return_value=["ffmpeg"]) as compile_command,
                patch.object(compiler, "verify", return_value={"passed": True}),
                patch.object(timeline_export, "render_timeout_seconds", return_value=123) as timeout,
                patch.object(timeline_export, "_run_render_process", return_value=(0, "")) as run_process,
            ):
                compiler.render({"project_id": "project-timeout"}, timeline, output)

            compile_command.assert_called_once()
            timeout.assert_called_once_with(1.0)
            run_process.assert_called_once_with(["ffmpeg"], 123)

    def test_runner_isolates_process_and_retains_only_bounded_stderr_tail(self):
        command = [
            sys.executable, "-c",
            "import sys; sys.stderr.buffer.write(b'x' * 200000 + b'END-MARKER'); raise SystemExit(7)",
        ]
        original_popen = subprocess.Popen
        with patch.object(ffmpeg_runtime.subprocess, "Popen", wraps=original_popen) as popen:
            returncode, stderr = timeline_export._run_render_process(command, timeout_seconds=5)

        self.assertEqual(returncode, 7)
        self.assertLessEqual(len(stderr.encode()), timeline_export.RENDER_STDERR_TAIL_BYTES)
        self.assertTrue(stderr.endswith("END-MARKER"))
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertIs(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(popen.call_args.kwargs["stderr"], subprocess.PIPE)
        self.assertEqual(timeline_export.active_render_process_count(), 0)

    def test_structural_qa_fails_closed_if_managed_output_is_truncated(self):
        result = ffmpeg_runtime.ManagedProcessResult(
            returncode=0,
            stdout="",
            stderr="black_start:0 black_end:1",
            stderr_truncated=True,
        )
        with (
            patch.object(timeline_export, "run_media_process", return_value=result) as runner,
            patch.object(TimelineFFmpegCompiler, "_timestamp_checks") as timestamp_checks,
        ):
            checks = TimelineFFmpegCompiler._structural_checks(Path("output.mp4"), 60)

        self.assertEqual(checks["structural_scan"]["status"], "not_evaluated")
        self.assertEqual(checks["structural_scan"]["error"], "structural_scan_output_limit")
        self.assertFalse(runner.call_args.kwargs["stderr_tail"])
        timestamp_checks.assert_not_called()

    def test_stderr_reader_finish_is_time_bounded_if_pipe_stays_open(self):
        class BlockingStream:
            def __init__(self):
                self.closed = Event()

            def read(self, _size):
                self.closed.wait(30)
                return b""

            def close(self):
                self.closed.set()

        stream = BlockingStream()
        reader = ffmpeg_runtime._BoundedPipeCapture(stream, 1024, keep_tail=True)
        reader.start()
        started = time.monotonic()
        captured, truncated = reader.finish()

        self.assertEqual(captured, b"")
        self.assertFalse(truncated)
        self.assertLess(time.monotonic() - started, 2.5)
        self.assertTrue(stream.closed.is_set())
        self.assertFalse(reader.thread.is_alive())

    def test_timeout_escalates_term_to_kill_and_reaps_process(self):
        class StubbornProcess:
            pid = 424242
            returncode = None

            def __init__(self):
                self.stderr = BytesIO(b"diagnostic tail")
                self.wait_timeouts = []

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.wait_timeouts.append(timeout)
                if len(self.wait_timeouts) < 3:
                    raise subprocess.TimeoutExpired(["ffmpeg"], timeout)
                self.returncode = -signal.SIGKILL
                return self.returncode

        process = StubbornProcess()
        with (
            patch.object(ffmpeg_runtime.subprocess, "Popen", return_value=process),
            patch.object(ffmpeg_runtime.os, "killpg") as killpg,
        ):
            with self.assertRaisesRegex(TimelineCompileError, "timed out after 2 seconds"):
                timeline_export._run_render_process(
                    ["ffmpeg"], timeout_seconds=2, terminate_grace_seconds=.25,
                )

        self.assertEqual(process.wait_timeouts, [2, .25, None])
        self.assertEqual(
            killpg.call_args_list,
            [
                ((process.pid, signal.SIGTERM),),
                ((process.pid, signal.SIGKILL),),
            ],
        )
        self.assertEqual(timeline_export.active_render_process_count(), 0)

    def test_active_process_can_be_cancelled_and_is_untracked(self):
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                timeline_export._run_render_process, command, 60, .25,
            )
            deadline = time.monotonic() + 2
            while not timeline_export.active_render_process_count() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(timeline_export.active_render_process_count(), 1)
            self.assertEqual(timeline_export.terminate_active_render_processes(.25), 1)
            returncode, _stderr = future.result(timeout=3)

        self.assertNotEqual(returncode, 0)
        self.assertEqual(timeline_export.active_render_process_count(), 0)

    def test_shutdown_terminates_active_child_and_blocks_follow_on_spawn(self):
        ffmpeg_runtime.start_media_process_runtime()
        try:
            command = [sys.executable, "-c", "import time; time.sleep(60)"]
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    ffmpeg_runtime.run_media_process,
                    command,
                    timeout_seconds=60,
                    terminate_grace_seconds=.25,
                )
                deadline = time.monotonic() + 2
                while not ffmpeg_runtime.active_media_process_count() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(ffmpeg_runtime.active_media_process_count(), 1)
                self.assertEqual(ffmpeg_runtime.shutdown_media_process_runtime(.25), 1)
                with patch.object(ffmpeg_runtime.subprocess, "Popen") as popen:
                    with self.assertRaises(ffmpeg_runtime.ManagedProcessUnavailable):
                        ffmpeg_runtime.run_media_process(
                            ["ffmpeg"], timeout_seconds=1,
                        )
                popen.assert_not_called()
                self.assertNotEqual(future.result(timeout=3).returncode, 0)
        finally:
            ffmpeg_runtime.start_media_process_runtime()

    def test_structural_qa_process_is_visible_to_shutdown_and_reaped(self):
        def run_long_qa(_command, **_kwargs):
            return ffmpeg_runtime.run_media_process(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                timeout_seconds=60,
                terminate_grace_seconds=.25,
                stderr_tail=False,
            )

        with (
            patch.object(timeline_export, "run_media_process", side_effect=run_long_qa),
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(
                TimelineFFmpegCompiler._structural_checks, Path("output.mp4"), 60,
            )
            deadline = time.monotonic() + 2
            while not timeline_export.active_render_process_count() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(timeline_export.active_render_process_count(), 1)
            self.assertEqual(timeline_export.terminate_active_render_processes(.25), 1)
            checks = future.result(timeout=3)

        self.assertEqual(checks["structural_scan"]["status"], "not_evaluated")
        self.assertEqual(timeline_export.active_render_process_count(), 0)


class FakeCompiler:
    def render(self, project, timeline, output):
        output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(b"verified-export")
        return {"command": ["ffmpeg", "-i", "original.mov", str(output)], "elapsed_seconds": .1,
                "verification": {"passed": True, "checks": {"fixture": {"required": True, "status": "passed"}}}}


class FailingCompiler:
    def render(self, project, timeline, output):
        raise RuntimeError("fixture export failure")


class PartialFailingCompiler:
    def render(self, project, timeline, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"partial")
        raise RuntimeError("fixture export failure")


class TimedOutCompiler:
    def render(self, project, timeline, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"partial")
        timeline_export._run_render_process(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            timeout_seconds=.05,
            terminate_grace_seconds=.05,
        )


class ConcurrencyTrackingCompiler(FakeCompiler):
    def __init__(self):
        self.lock = Lock()
        self.active = 0
        self.max_active = 0

    def render(self, project, timeline, output):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return super().render(project, timeline, output)
        finally:
            with self.lock:
                self.active -= 1


class TimelineApprovalLearningTests(TestCase):
    @staticmethod
    def exportable_project(store, suffix):
        style_id = "style-20260827-%s" % suffix
        style_root = store.styles_dir / style_id
        style_root.mkdir(parents=True)
        store.write_json(style_root / "profile.json", {
            "style_id": style_id, "recipe_version": "1.0.0", "recipe": {"rules": []},
        })
        project_id = "project-20260827-%s" % suffix
        root = store.projects_dir / project_id
        root.mkdir(parents=True)
        raw = {
            "file_id": "raw-001", "original_name": "source.mov",
            "stored_path": "projects/%s/raw/source.mov" % project_id,
            "sha256": suffix[0] * 64, "analysis_status": "complete",
            "metadata": {"duration_seconds": 2, "has_audio": True},
        }
        store.write_json(root / "recipe_snapshot.json", {"rules": []})
        store.write_json(root / "manifest.json", {
            "project_id": project_id, "style_id": style_id, "recipe_version": "1.0.0",
            "recipe_snapshot_path": "projects/%s/recipe_snapshot.json" % project_id,
            "raw_files": [raw], "status": "timeline_ready",
        })
        timeline = populated_timeline(project_id, raw)
        TimelineStore(store).initialize(project_id, timeline)
        return project_id, timeline

    def test_process_render_slot_serializes_different_projects(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            compiler = ConcurrencyTrackingCompiler()
            first_id, first_timeline = self.exportable_project(store, "aa11aa")
            second_id, second_timeline = self.exportable_project(store, "bb22bb")
            first_service = TimelineExportService(store, compiler=compiler)
            second_service = TimelineExportService(store, compiler=compiler)
            first = first_service.create(first_id, first_timeline["timeline_hash"], approve_on_success=False, approval_confirmation=False)
            second = second_service.create(second_id, second_timeline["timeline_hash"], approve_on_success=False, approval_confirmation=False)

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda item: item[0].run(item[1], item[2]),
                    ((first_service, first_id, first["export_id"]),
                     (second_service, second_id, second["export_id"])),
                ))

            self.assertEqual(compiler.max_active, 1)
            self.assertTrue(all(record["status"] == "complete" for record in results))
            waits = [record.get("queue_wait_seconds", 0) for record in results]
            self.assertGreaterEqual(max(waits), 0.04)

    def test_competing_export_requests_create_only_one_queued_export(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id, timeline = self.exportable_project(store, "dd44dd")
            service = TimelineExportService(store, compiler=FakeCompiler())

            def create(_index):
                try:
                    return service.create(
                        project_id, timeline["timeline_hash"],
                        approve_on_success=False, approval_confirmation=False,
                    )
                except ValueError:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(create, range(2)))

            self.assertEqual(sum(result is not None for result in results), 1)
            roots = list((store.project_dir(project_id) / "exports").glob("*/export.json"))
            self.assertEqual(len(roots), 1)
            self.assertEqual(store.project(project_id)["status"], "export_queued")

    def test_failed_export_admission_removes_its_orphan_snapshot(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id, timeline = self.exportable_project(store, "ee55ee")
            service = TimelineExportService(store, compiler=FakeCompiler())
            original_transition = store.transition_project

            def competing_job(*args, **kwargs):
                store.update_project(project_id, status="timeline_queued")
                return original_transition(*args, **kwargs)

            with patch.object(store, "transition_project", side_effect=competing_job):
                with self.assertRaises(ValueError):
                    service.create(
                        project_id, timeline["timeline_hash"],
                        approve_on_success=False, approval_confirmation=False,
                    )

            exports = store.project_dir(project_id) / "exports"
            self.assertFalse(exports.exists() and any(exports.iterdir()))

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

    def test_failed_export_releases_project_and_never_approves(self):
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
            self.assertIsNone(project.get("active_export_id"))
            self.assertFalse(project.get("final_approval", {}).get("approved", False))
            failed = service.record(project_id, export["export_id"])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["failure_code"], "render_or_qa_failed")
            self.assertNotIn("fixture export failure", str(failed))

    def test_failed_render_removes_partial_output(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id, timeline = self.exportable_project(store, "cc33cc")
            service = TimelineExportService(store, compiler=PartialFailingCompiler())
            export = service.create(
                project_id, timeline["timeline_hash"],
                approve_on_success=False, approval_confirmation=False,
            )

            with self.assertRaises(RuntimeError):
                service.run(project_id, export["export_id"])

            output = store.project_dir(project_id) / "exports" / export["export_id"] / "output.mp4"
            self.assertFalse(output.exists())

    def test_timed_out_render_cleans_up_releases_slot_and_allows_next_render(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id, timeline = self.exportable_project(store, "cc44cc")
            failed_service = TimelineExportService(store, compiler=TimedOutCompiler())
            failed_export = failed_service.create(
                project_id, timeline["timeline_hash"],
                approve_on_success=False, approval_confirmation=False,
            )

            with self.assertRaises(TimelineCompileError):
                failed_service.run(project_id, failed_export["export_id"])

            failed_output = (
                store.project_dir(project_id) / "exports" /
                failed_export["export_id"] / "output.mp4"
            )
            failed_project = store.project(project_id)
            self.assertFalse(failed_output.exists())
            self.assertEqual(failed_project["status"], "export_failed")
            self.assertIsNone(failed_project["active_export_id"])
            self.assertEqual(timeline_export.active_render_process_count(), 0)

            next_service = TimelineExportService(store, compiler=FakeCompiler())
            next_export = next_service.create(
                project_id, timeline["timeline_hash"],
                approve_on_success=False, approval_confirmation=False,
            )
            completed = next_service.run(project_id, next_export["export_id"])
            self.assertEqual(completed["status"], "complete")

    def test_corrupt_export_record_does_not_leave_project_stuck(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id, timeline = self.exportable_project(store, "fa11ed")
            service = TimelineExportService(store, compiler=FakeCompiler())
            export = service.create(
                project_id, timeline["timeline_hash"],
                approve_on_success=False, approval_confirmation=False,
            )
            record_path = (
                store.project_dir(project_id) / "exports" / export["export_id"] / "export.json"
            )
            record_path.write_text("not-json")

            with self.assertRaises(json.JSONDecodeError):
                service.run(project_id, export["export_id"])

            project = store.project(project_id)
            self.assertEqual(project["status"], "export_failed")
            self.assertIsNone(project["active_export_id"])

    def test_pre_render_record_write_failure_recovers_project_and_record(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            project_id, timeline = self.exportable_project(store, "fa22ed")
            service = TimelineExportService(store, compiler=FakeCompiler())
            export = service.create(
                project_id, timeline["timeline_hash"],
                approve_on_success=False, approval_confirmation=False,
            )
            record_path = (
                store.project_dir(project_id) / "exports" / export["export_id"] / "export.json"
            )
            original_write = store.write_json
            failed_once = False

            def fail_first_exporting_write(path, payload):
                nonlocal failed_once
                if path == record_path and payload.get("status") == "exporting" and not failed_once:
                    failed_once = True
                    raise OSError("simulated pre-render record failure")
                return original_write(path, payload)

            with patch.object(store, "write_json", side_effect=fail_first_exporting_write):
                with self.assertRaises(OSError):
                    service.run(project_id, export["export_id"])

            project = store.project(project_id)
            self.assertEqual(project["status"], "export_failed")
            self.assertIsNone(project["active_export_id"])
            self.assertEqual(service.record(project_id, export["export_id"])["status"], "failed")


if __name__ == "__main__":
    import unittest
    unittest.main()
