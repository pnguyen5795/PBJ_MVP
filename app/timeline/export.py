from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Tuple
import json
import re
import shutil
import subprocess
import time

from ..media import inspect_video
from ..storage import JsonStore, new_id, sha256 as file_sha256, utc_now
from .contracts import TIMELINE_FPS, canonical_json, main_video_duration_frames
from .preview import preview_state_at_frame
from .storage import TimelineStore
from .validation import validate_timeline
from .lifecycle import ACTIVE_JOB_STATES


class TimelineCompileError(RuntimeError):
    pass


class TimelineFFmpegCompiler:
    """Compile a validated timeline from original project assets only."""

    def __init__(self, store: JsonStore):
        self.store = store

    def compile_command(self, project: Dict[str, Any], timeline: Dict[str, Any], output: Path) -> List[str]:
        validate_timeline(timeline, for_export=True)
        assets = {item["asset_id"]: item for item in timeline["assets"]}
        command = ["ffmpeg", "-hide_banner", "-y"]
        filters: List[str] = []
        input_index = 0

        def add_input(asset_id: str) -> int:
            nonlocal input_index
            asset = assets[asset_id]
            source = self.store.resolve_data_path(asset["stored_path"])
            if not source.exists():
                raise TimelineCompileError("Original asset is missing: %s" % asset_id)
            command.extend(["-i", str(source)])
            result = input_index
            input_index += 1
            return result

        main = next(track for track in timeline["tracks"] if track.get("role") == "main" and track.get("kind") == "video")
        main_clips = sorted(main["clips"], key=lambda item: item["timeline_start_frame"])
        labels, durations = [], []
        for index, clip in enumerate(main_clips):
            source_index = add_input(clip["asset_id"])
            label = "main%d" % index
            filters.append(self._video_filter(source_index, clip, timeline["canvas"], label))
            labels.append("[%s]" % label)
            durations.append(clip["duration_frames"] / TIMELINE_FPS)
        current = labels[0]
        current_duration = durations[0]
        transitions = {(item.get("from_clip_id"), item.get("to_clip_id")): item for item in timeline.get("transitions", [])}
        for index in range(1, len(labels)):
            output_label = "base" if index == len(labels) - 1 else "join%d" % index
            transition = transitions.get((main_clips[index - 1]["clip_id"], main_clips[index]["clip_id"]))
            if transition and transition.get("type") == "crossfade":
                seconds = int(transition["duration_frames"]) / TIMELINE_FPS
                offset = max(0, current_duration - seconds)
                filters.append("%s%sxfade=transition=fade:duration=%s:offset=%s[%s]" % (current, labels[index], self._n(seconds), self._n(offset), output_label))
                current_duration += durations[index] - seconds
            else:
                filters.append("%s%sconcat=n=2:v=1:a=0[%s]" % (current, labels[index], output_label))
                current_duration += durations[index]
            current = "[%s]" % output_label
        if len(labels) == 1:
            filters.append("%snull[base]" % current)
        current = "[base]"

        overlays = [clip for track in sorted(timeline["tracks"], key=lambda item: item.get("order", 0))
                    if track.get("kind") == "video" and track.get("role") != "main" and not track.get("muted")
                    for clip in sorted(track.get("clips", []), key=lambda item: item["timeline_start_frame"])]
        for index, clip in enumerate(overlays):
            source_index = add_input(clip["asset_id"])
            overlay_label = "overlay%d" % index
            filters.append(self._overlay_filter(source_index, clip, timeline["canvas"], overlay_label))
            output_label = "vout" if index == len(overlays) - 1 else "layer%d" % index
            start = clip["timeline_start_frame"] / TIMELINE_FPS
            end = (clip["timeline_start_frame"] + clip["duration_frames"]) / TIMELINE_FPS
            transform = clip.get("transform") or {}
            x = self._overlay_center(transform.get("x", .5), "W", "w")
            y = self._overlay_center(transform.get("y", .5), "H", "h")
            filters.append("%s[%s]overlay=x=%s:y=%s:enable='between(t,%s,%s)':eof_action=pass[%s]" % (current, overlay_label, x, y, self._n(start), self._n(end), output_label))
            current = "[%s]" % output_label
        if not overlays:
            filters.append("%snull[vout]" % current)

        audio_labels = []
        for track in timeline["tracks"]:
            if track.get("kind") != "audio" or track.get("muted"):
                continue
            for index, clip in enumerate(track.get("clips", [])):
                if clip.get("muted") or not assets[clip["asset_id"]].get("has_audio"):
                    continue
                source_index = add_input(clip["asset_id"])
                label = "audio%d" % len(audio_labels)
                filters.append(self._audio_filter(source_index, clip, label))
                audio_labels.append("[%s]" % label)
        duration = main_video_duration_frames(timeline) / TIMELINE_FPS
        if audio_labels:
            filters.append("%samix=inputs=%d:duration=longest:normalize=0,atrim=duration=%s[aout]" % ("".join(audio_labels), len(audio_labels), self._n(duration)))
        else:
            filters.append("anullsrc=r=48000:cl=stereo,atrim=duration=%s[aout]" % self._n(duration))
        command.extend([
            "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", self._n(duration), "-movflags", "+faststart", str(output),
        ])
        return command

    def render(self, project: Dict[str, Any], timeline: Dict[str, Any], output: Path) -> Dict[str, Any]:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = self.compile_command(project, timeline, output)
        started = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise TimelineCompileError("FFmpeg export failed: %s" % result.stderr[-3000:])
        verification = self.verify(output, timeline)
        return {"command": command, "elapsed_seconds": round(time.perf_counter() - started, 3), "verification": verification}

    def verify(self, output: Path, timeline: Dict[str, Any]) -> Dict[str, Any]:
        metadata = inspect_video(output)
        expected = main_video_duration_frames(timeline) / TIMELINE_FPS
        canvas = timeline["canvas"]
        checks = {
            "file_present": {"required": True, "status": "passed" if output.exists() and output.stat().st_size else "failed"},
            "resolution": {"required": True, "status": "passed" if metadata.get("width") == canvas["width"] and metadata.get("height") == canvas["height"] else "failed"},
            "video_codec": {"required": True, "status": "passed" if metadata.get("video_codec") == "h264" else "failed"},
            "audio_codec": {"required": True, "status": "passed" if metadata.get("audio_codec") == "aac" else "failed"},
            "has_audio": {"required": True, "status": "passed" if metadata.get("has_audio") is True else "failed"},
            "duration": {"required": True, "status": "passed" if abs(float(metadata.get("duration_seconds") or 0) - expected) <= .25 else "failed", "expected_seconds": expected, "actual_seconds": metadata.get("duration_seconds")},
        }
        checks.update(self._structural_checks(output, expected))
        passed = all(item["status"] == "passed" for item in checks.values() if item["required"])
        if not passed:
            raise TimelineCompileError("Export failed required QA: %s" % json.dumps(checks))
        return {"passed": True, "checks": checks, "metadata": metadata}

    @staticmethod
    def _structural_checks(output: Path, expected_seconds: float) -> Dict[str, Any]:
        command = [
            "ffmpeg", "-hide_banner", "-v", "info", "-i", str(output),
            "-vf", "blackdetect=d=0.75:pix_th=0.02,freezedetect=n=-60dB:d=4",
            "-af", "silencedetect=n=-55dB:d=3", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=max(60, int(expected_seconds * 3)))
        except (OSError, subprocess.SubprocessError) as exc:
            return {"structural_scan": {"required": True, "status": "not_evaluated", "error": str(exc)}}
        if result.returncode != 0:
            return {"structural_scan": {"required": True, "status": "not_evaluated", "error": result.stderr[-1000:]}}
        def intervals(prefix: str):
            starts = [float(value) for value in re.findall(prefix + r"_start:([0-9.]+)", result.stderr)]
            ends = [float(value) for value in re.findall(prefix + r"_end:([0-9.]+)", result.stderr)]
            return [(start, ends[index] if index < len(ends) else expected_seconds)
                    for index, start in enumerate(starts)]

        black_intervals = intervals("black")
        freeze_intervals = intervals("freeze")
        black_tail = [item for item in black_intervals if item[1] >= expected_seconds - .15 and item[1] - item[0] >= .75]
        frozen_tail = [item for item in freeze_intervals if item[1] >= expected_seconds - .15 and item[1] - item[0] >= 4]
        silence = len(re.findall(r"silence_start:", result.stderr))
        timestamp_check = TimelineFFmpegCompiler._timestamp_checks(output, expected_seconds)
        return {
            "structural_scan": {"required": True, "status": "passed"},
            "black_tail": {"required": True, "status": "passed" if not black_tail else "failed", "segments": black_tail, "threshold_seconds": .75},
            "frozen_tail": {"required": True, "status": "passed" if not frozen_tail else "failed", "segments": frozen_tail, "threshold_seconds": 4},
            "long_silence": {"required": False, "status": "passed" if silence == 0 else "failed", "segment_count": silence, "threshold_seconds": 3},
            **timestamp_check,
        }

    @staticmethod
    def _timestamp_checks(output: Path, expected_seconds: float) -> Dict[str, Any]:
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time,duration",
                "-of", "json", str(output),
            ], capture_output=True, text=True, timeout=30)
            payload = json.loads(result.stdout) if result.returncode == 0 else {}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return {"timestamp_scan": {"required": True, "status": "not_evaluated", "error": str(exc)}}
        streams = payload.get("streams") or []
        starts = [abs(float(item.get("start_time") or 0)) for item in streams]
        durations = {item.get("codec_type"): float(item.get("duration") or 0) for item in streams}
        video_duration, audio_duration = durations.get("video", 0), durations.get("audio", 0)
        drift = abs(video_duration - audio_duration) if video_duration and audio_duration else float("inf")
        monotonic_origin = bool(streams) and max(starts or [99]) <= .1
        return {
            "timestamp_scan": {"required": True, "status": "passed" if streams else "failed"},
            "timestamp_origin": {"required": True, "status": "passed" if monotonic_origin else "failed", "maximum_start_seconds": max(starts or [0])},
            "av_duration_drift": {"required": True, "status": "passed" if drift <= .25 else "failed", "drift_seconds": drift},
            "stream_duration": {"required": True, "status": "passed" if abs(video_duration - expected_seconds) <= .25 else "failed", "video_seconds": video_duration},
        }

    @staticmethod
    def _video_filter(input_index: int, clip: Dict[str, Any], canvas: Dict[str, Any], label: str) -> str:
        start, end = clip["source_in_us"] / 1_000_000, clip["source_out_us"] / 1_000_000
        rate = float(clip.get("playback_rate", 1))
        transform = clip.get("transform") or {}
        width, height = int(canvas["width"]), int(canvas["height"])
        mode = transform.get("mode", "fill")
        crop = transform.get("crop") or {}
        source_crop = ""
        if crop:
            crop_width = max(.01, min(1.0, float(crop.get("width", 1))))
            crop_height = max(.01, min(1.0, float(crop.get("height", 1))))
            crop_x = max(0, min(1 - crop_width, float(crop.get("x", 0))))
            crop_y = max(0, min(1 - crop_height, float(crop.get("y", 0))))
            source_crop = "crop=floor(iw*%s/2)*2:floor(ih*%s/2)*2:floor(iw*%s/2)*2:floor(ih*%s/2)*2," % (
                TimelineFFmpegCompiler._n(crop_width), TimelineFFmpegCompiler._n(crop_height),
                TimelineFFmpegCompiler._n(crop_x), TimelineFFmpegCompiler._n(crop_y),
            )
        if mode == "fit":
            visual = source_crop + "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:%s" % (width, height, width, height, canvas.get("background", "black"))
        else:
            x, y = float(transform.get("x", .5)), float(transform.get("y", .5))
            visual = source_crop + "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d:(iw-%d)*%s:(ih-%d)*%s" % (width, height, width, height, width, TimelineFFmpegCompiler._n(x), height, TimelineFFmpegCompiler._n(y))
        scale = max(1.0, float(transform.get("scale", 1)))
        if scale > 1:
            sw, sh = int(round(width * scale / 2) * 2), int(round(height * scale / 2) * 2)
            x, y = float(transform.get("x", .5)), float(transform.get("y", .5))
            visual += ",scale=%d:%d,crop=%d:%d:(iw-%d)*%s:(ih-%d)*%s" % (
                sw, sh, width, height, width, TimelineFFmpegCompiler._n(x),
                height, TimelineFFmpegCompiler._n(y),
            )
        return "[%d:v]trim=start=%s:end=%s,setpts=(PTS-STARTPTS)/%s,%s,setsar=1,fps=30,format=yuv420p,settb=AVTB[%s]" % (input_index, TimelineFFmpegCompiler._n(start), TimelineFFmpegCompiler._n(end), TimelineFFmpegCompiler._n(rate), visual, label)

    @staticmethod
    def _overlay_filter(input_index: int, clip: Dict[str, Any], canvas: Dict[str, Any], label: str) -> str:
        start, end = clip["source_in_us"] / 1_000_000, clip["source_out_us"] / 1_000_000
        timeline_start = clip["timeline_start_frame"] / TIMELINE_FPS
        rate = float(clip.get("playback_rate", 1))
        transform = clip.get("transform") or {}
        scale = max(.1, min(1.0, float(transform.get("scale", .35))))
        target_width = max(2, int(round(int(canvas["width"]) * scale / 2) * 2))
        return "[%d:v]trim=start=%s:end=%s,setpts=(PTS-STARTPTS)/%s+%s/TB,scale=%d:-2,format=yuva420p[%s]" % (input_index, TimelineFFmpegCompiler._n(start), TimelineFFmpegCompiler._n(end), TimelineFFmpegCompiler._n(rate), TimelineFFmpegCompiler._n(timeline_start), target_width, label)

    @staticmethod
    def _audio_filter(input_index: int, clip: Dict[str, Any], label: str) -> str:
        start, end = clip["source_in_us"] / 1_000_000, clip["source_out_us"] / 1_000_000
        rate = float(clip.get("playback_rate", 1))
        timeline_start = clip["timeline_start_frame"] / TIMELINE_FPS
        duration = clip["duration_frames"] / TIMELINE_FPS
        filters = ["[%d:a]atrim=start=%s:end=%s" % (input_index, TimelineFFmpegCompiler._n(start), TimelineFFmpegCompiler._n(end)), "asetpts=PTS-STARTPTS", TimelineFFmpegCompiler._atempo(rate), "volume=%s" % TimelineFFmpegCompiler._n(clip.get("volume", 1))]
        fades = clip.get("fades") or {}
        fade_in = int(fades.get("in_frames", 0)) / TIMELINE_FPS
        fade_out = int(fades.get("out_frames", 0)) / TIMELINE_FPS
        if fade_in > 0: filters.append("afade=t=in:st=0:d=%s" % TimelineFFmpegCompiler._n(fade_in))
        if fade_out > 0: filters.append("afade=t=out:st=%s:d=%s" % (TimelineFFmpegCompiler._n(max(0, duration - fade_out)), TimelineFFmpegCompiler._n(fade_out)))
        filters.append("adelay=%d|%d" % (round(timeline_start * 1000), round(timeline_start * 1000)))
        return ",".join(filters) + "[%s]" % label

    @staticmethod
    def _atempo(rate: float) -> str:
        factors = []
        while rate > 2: factors.append(2.0); rate /= 2
        while rate < .5: factors.append(.5); rate /= .5
        factors.append(rate)
        return ",".join("atempo=%s" % TimelineFFmpegCompiler._n(item) for item in factors)

    @staticmethod
    def _overlay_center(value: float, outer: str, inner: str) -> str:
        return "%s*%s-%s/2" % (outer, TimelineFFmpegCompiler._n(max(0, min(1, float(value)))), inner)

    @staticmethod
    def _n(value: Any) -> str:
        return ("%.6f" % float(value)).rstrip("0").rstrip(".")


class TimelineExportService:
    def __init__(self, store: JsonStore, compiler: Any = None):
        self.store = store
        self.timelines = TimelineStore(store)
        self.compiler = compiler or TimelineFFmpegCompiler(store)

    def create(self, project_id: str, timeline_hash: str, *, approve_on_success: bool,
               approval_confirmation: bool, revision_prompt: str = "") -> Dict[str, Any]:
        project = self.store.project(project_id)
        if project.get("status") in ACTIVE_JOB_STATES:
            raise ValueError("Wait for the current project task to finish before exporting")
        timeline = self.timelines.load(project_id)
        if timeline["timeline_hash"] != timeline_hash:
            raise ValueError("The timeline changed; review the latest saved edit before exporting")
        if approve_on_success and not approval_confirmation:
            raise ValueError("Confirm that a successful export becomes approved learning evidence")
        validate_timeline(timeline, for_export=True)
        export_id = new_id("export")
        root = self.store.project_dir(project_id) / "exports" / export_id
        snapshot = root / "timeline.json"
        self.store.write_json(snapshot, timeline)
        record = {
            "schema_version": "1.0", "export_id": export_id, "project_id": project_id,
            "status": "queued", "created_at": utc_now(), "timeline_hash": timeline_hash,
            "timeline_path": str(snapshot.relative_to(self.store.data_dir)),
            "approve_on_success": bool(approve_on_success), "approval_confirmation": bool(approval_confirmation),
            "revision_prompt": revision_prompt.strip() or None,
        }
        self.store.write_json(root / "export.json", record)
        self.store.update_project(project_id, status="export_queued", editor_read_only=True, active_export_id=export_id, active_task="Preparing final export", active_started_at=utc_now())
        return record

    def record(self, project_id: str, export_id: str) -> Dict[str, Any]:
        return self.store.read_json(self.store.project_dir(project_id) / "exports" / export_id / "export.json")

    def records(self, project_id: str, *, completed_only: bool = False) -> list[Dict[str, Any]]:
        """Return durable render versions oldest-first without trusting the latest pointer."""
        root = self.store.project_dir(project_id) / "exports"
        records = []
        for path in root.glob("*/export.json") if root.exists() else []:
            try:
                record = self.store.read_json(path)
            except (OSError, ValueError):
                continue
            if completed_only and record.get("status") != "complete":
                continue
            records.append(record)
        records.sort(key=lambda item: (item.get("created_at") or "", item.get("export_id") or ""))
        return records

    def run(self, project_id: str, export_id: str) -> Dict[str, Any]:
        from .learning import approve_timeline_export
        root = self.store.project_dir(project_id) / "exports" / export_id
        record = self.record(project_id, export_id)
        project = self.store.update_project(project_id, status="exporting", active_task="Rendering from your original files")
        record.update(status="exporting", started_at=utc_now())
        self.store.write_json(root / "export.json", record)
        try:
            timeline = self.store.read_json(self.store.resolve_data_path(record["timeline_path"]))
            output = root / "output.mp4"
            render = self.compiler.render(project, timeline, output)
            command = render.pop("command")
            receipt = {
                "schema_version": "1.0", "export_id": export_id, "project_id": project_id,
                "created_at": utc_now(), "timeline_hash": timeline["timeline_hash"],
                "timeline_path": record["timeline_path"], "recipe_version": project.get("recipe_version"),
                "assets": [{"asset_id": item["asset_id"], "sha256": item.get("sha256"), "stored_path": item.get("stored_path")} for item in timeline["assets"]],
                "compiled_command_hash": sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
                "output": {"path": str(output.relative_to(self.store.data_dir)), "sha256": file_sha256(output), "size_bytes": output.stat().st_size},
                "verification": render["verification"], "render_elapsed_seconds": render["elapsed_seconds"],
                "original_assets_only": True, "proxy_assets_used": False,
                "transform_contract_version": "normalized-focal-v1",
            }
            event_log = self.timelines.events(project_id)
            program_frames = main_video_duration_frames(timeline)
            preview_states = [preview_state_at_frame(timeline, frame) for frame in sorted({0, max(0, program_frames // 2), max(0, program_frames - 1)})]
            receipt["command_log_head_hash"] = event_log[-1]["event_hash"] if event_log else None
            receipt["preview_contract_version"] = "preview-state-v1"
            receipt["preview_decision_hash"] = sha256(canonical_json(preview_states).encode()).hexdigest()
            receipt_path = root / "render_receipt.json"
            qa_path = root / "qa_report.json"
            self.store.write_json(receipt_path, receipt)
            self.store.write_json(qa_path, render["verification"])
            record.update(
                status="complete", completed_at=utc_now(), output_path=receipt["output"]["path"],
                output_sha256=receipt["output"]["sha256"], render_receipt_path=str(receipt_path.relative_to(self.store.data_dir)),
                qa_report_path=str(qa_path.relative_to(self.store.data_dir)),
            )
            self.store.write_json(root / "export.json", record)
            approval = None
            if record.get("approve_on_success") and render["verification"].get("passed"):
                approval = approve_timeline_export(self.store, project_id, record, timeline, receipt)
                record["approval"] = approval
                self.store.write_json(root / "export.json", record)
            self.store.update_project(
                project_id, status="approved" if approval else "timeline_ready",
                editor_read_only=False, active_export_id=None, active_task=None,
                latest_export=record, has_unexported_changes=False if approval else True,
            )
            return record
        except Exception as exc:
            record.update(status="failed", failed_at=utc_now(), error=str(exc))
            self.store.write_json(root / "export.json", record)
            self.store.update_project(project_id, status="export_failed", editor_read_only=False, active_export_id=None, active_task=None, last_error=str(exc))
            raise
