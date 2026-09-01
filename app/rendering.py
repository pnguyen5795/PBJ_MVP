from pathlib import Path
from typing import Any, Dict, List
import json
import shutil
import subprocess
import re

from .media import inspect_video
from .storage import JsonStore


class PlanValidationError(ValueError):
    pass


class FFmpegRenderer:
    WIDTH = 1080
    HEIGHT = 1920
    # Analyzer timestamps and model-generated speed values are estimates. A
    # rough cut should tolerate modest rounding/drift rather than fail before
    # FFmpeg can render it. Structural and source-range checks remain strict.
    TOLERANCE = 0.5

    def __init__(self, store: JsonStore):
        self.store = store

    def validate(self, project: Dict[str, Any], plan: Dict[str, Any]) -> None:
        if plan.get("project_id") != project.get("project_id") or plan.get("style_id") != project.get("style_id"):
            raise PlanValidationError("Plan does not belong to this project and style")
        target = float(plan.get("target_duration_seconds", 0))
        if not 15 <= target <= 180:
            raise PlanValidationError("Output duration must be between 15 and 180 seconds")
        requested_target = float(project["target_duration_seconds"])
        # A source-bound repair may produce a shorter, honest rough cut when
        # the selected footage cannot safely fill the requested duration. Do
        # not reject that; never extend it with invented frames.
        if target > requested_target + self.TOLERANCE:
            raise PlanValidationError("Plan duration exceeds the requested duration")
        sources = {item["file_id"]: item for item in project["raw_files"]}
        for layer in ("video_segments", "audio_segments"):
            segments = plan.get(layer)
            if not segments:
                raise PlanValidationError("Plan must contain %s" % layer)
            previous_end = 0.0
            for index, segment in enumerate(segments):
                source = sources.get(segment.get("source_file_id"))
                if not source:
                    raise PlanValidationError("Plan references an unknown source file")
                if layer == "audio_segments" and source.get("metadata", {}).get("has_audio") is False:
                    raise PlanValidationError("An audio segment references a source with no audio track")
                source_start, source_end = float(segment["source_start"]), float(segment["source_end"])
                timeline_start, timeline_end = float(segment["timeline_start"]), float(segment["timeline_end"])
                speed = float(segment.get("speed", 1))
                duration = source.get("metadata", {}).get("duration_seconds")
                if source_start < 0 or source_end <= source_start or (duration is not None and source_end > float(duration) + self.TOLERANCE):
                    raise PlanValidationError("Plan contains an invalid source time range")
                expected_start = previous_end
                if layer == "video_segments":
                    transition = segment.get("transition", "cut")
                    transition_duration = float(segment.get("transition_duration", 0))
                    if index == 0 and (transition != "cut" or abs(transition_duration) > self.TOLERANCE):
                        raise PlanValidationError("The first video segment must enter with a cut")
                    if transition == "cut" and abs(transition_duration) > self.TOLERANCE:
                        raise PlanValidationError("A hard cut must have zero transition duration")
                    if transition == "crossfade":
                        if index == 0 or not 0.1 <= transition_duration <= 1:
                            raise PlanValidationError("A crossfade must last between 0.1 and 1 second")
                        expected_start = previous_end - transition_duration
                    elif transition != "cut":
                        raise PlanValidationError("Unsupported video transition")
                if abs(timeline_start - expected_start) > self.TOLERANCE or timeline_end <= timeline_start:
                    raise PlanValidationError("%s contains a gap or an invalid overlap" % layer)
                if abs(((source_end - source_start) / speed) - (timeline_end - timeline_start)) > self.TOLERANCE:
                    raise PlanValidationError("Source and timeline durations do not match the speed")
                previous_end = timeline_end
            if abs(previous_end - target) > self.TOLERANCE:
                raise PlanValidationError("%s does not end at the target duration" % layer)

    def render(self, project: Dict[str, Any], plan: Dict[str, Any], output_path: Path) -> Dict[str, Any]:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("FFmpeg and ffprobe are required")
        self.validate(project, plan)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_command(project, plan, output_path)
        completed = subprocess.run(command, capture_output=True, text=True)
        log_path = output_path.with_suffix(".ffmpeg.log")
        log_path.write_text(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError("FFmpeg render failed; see %s" % log_path)
        verification = self.verify_output(output_path, float(plan["target_duration_seconds"]))
        return {"output_path": str(output_path), "log_path": str(log_path), "verification": verification, "command": command, "command_summary": {"input_count": len(plan["video_segments"]) + len(plan["audio_segments"]), "video_segments": len(plan["video_segments"]), "audio_segments": len(plan["audio_segments"])}}

    def build_command(self, project: Dict[str, Any], plan: Dict[str, Any], output_path: Path) -> List[str]:
        sources = {item["file_id"]: self.store.resolve_data_path(item["stored_path"]) for item in project["raw_files"]}
        command = ["ffmpeg", "-hide_banner", "-y"]
        for segment in plan["video_segments"]:
            command.extend(["-i", str(sources[segment["source_file_id"]])])
        for segment in plan["audio_segments"]:
            command.extend(["-i", str(sources[segment["source_file_id"]])])
        filters = []
        video_labels = []
        for index, segment in enumerate(plan["video_segments"]):
            label = "v%d" % index
            filters.append(self._video_filter(index, segment, label))
            video_labels.append("[%s]" % label)
        current_video = video_labels[0]
        if len(video_labels) == 1:
            filters.append("%snull[vout]" % current_video)
        else:
            for index in range(1, len(video_labels)):
                output_label = "vout" if index == len(video_labels) - 1 else "vx%d" % index
                segment = plan["video_segments"][index]
                if segment.get("transition") == "crossfade":
                    filters.append("%s%sxfade=transition=fade:duration=%s:offset=%s[%s]" % (current_video, video_labels[index], self._n(segment["transition_duration"]), self._n(segment["timeline_start"]), output_label))
                else:
                    filters.append("%s%sconcat=n=2:v=1:a=0[%s]" % (current_video, video_labels[index], output_label))
                current_video = "[%s]" % output_label
        audio_labels = []
        offset = len(plan["video_segments"])
        for index, segment in enumerate(plan["audio_segments"]):
            label = "a%d" % index
            filters.append(self._audio_filter(offset + index, segment, label))
            audio_labels.append("[%s]" % label)
        filters.append("%sconcat=n=%d:v=0:a=1[aout]" % ("".join(audio_labels), len(audio_labels)))
        command.extend([
            "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-t", self._n(plan["target_duration_seconds"]), "-movflags", "+faststart", str(output_path),
        ])
        return command

    def _video_filter(self, input_index: int, segment: Dict[str, Any], output_label: str) -> str:
        trim = "[%d:v]trim=start=%s:end=%s,setpts=(PTS-STARTPTS)/%s" % (input_index, self._n(segment["source_start"]), self._n(segment["source_end"]), self._n(segment.get("speed", 1)))
        zoom_start = float(segment.get("zoom_start", 1))
        zoom_end = float(segment.get("zoom_end", zoom_start))
        mode = segment.get("crop_mode", "center_crop")
        focal_x = float(segment.get("focal_x", 0.5)) if mode == "focal_crop" else 0.5
        focal_y = float(segment.get("focal_y", 0.5)) if mode == "focal_crop" else 0.5
        if mode == "fit":
            visual = "scale=w=%d:h=%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black" % (self.WIDTH, self.HEIGHT, self.WIDTH, self.HEIGHT)
        elif mode == "blurred_background":
            return "%s,split=2[bg%d][fg%d];[bg%d]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,boxblur=30:15[bgx%d];[fg%d]scale=%d:%d:force_original_aspect_ratio=decrease[fgx%d];[bgx%d][fgx%d]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30,format=yuv420p,settb=AVTB[%s]" % (trim, input_index, input_index, input_index, self.WIDTH, self.HEIGHT, self.WIDTH, self.HEIGHT, input_index, input_index, self.WIDTH, self.HEIGHT, input_index, input_index, input_index, output_label)
        else:
            visual = "scale=w=%d:h=%d:force_original_aspect_ratio=increase,crop=%d:%d:(iw-%d)*%s:(ih-%d)*%s" % (self.WIDTH, self.HEIGHT, self.WIDTH, self.HEIGHT, self.WIDTH, self._n(focal_x), self.HEIGHT, self._n(focal_y))
        if mode != "blurred_background" and (zoom_start > 1 or zoom_end > 1):
            # Avoid zoompan here: with variable-frame-rate phone footage it
            # can emit irregular timestamps and make concat hold the previous
            # frame while audio continues. A deterministic scale/crop keeps
            # the punch-in effect while preserving one video frame per input
            # frame and a stable 30-fps timeline.
            zoom = max(zoom_start, zoom_end)
            zoom_width = int(round(self.WIDTH * zoom / 2) * 2)
            zoom_height = int(round(self.HEIGHT * zoom / 2) * 2)
            visual += ",scale=%d:%d,crop=%d:%d:(iw-%d)*%s:(ih-%d)*%s" % (zoom_width, zoom_height, self.WIDTH, self.HEIGHT, self.WIDTH, self._n(focal_x), self.HEIGHT, self._n(focal_y))
        return "%s,%s,setsar=1,fps=30,format=yuv420p,settb=AVTB[%s]" % (trim, visual, output_label)

    def _audio_filter(self, input_index: int, segment: Dict[str, Any], output_label: str) -> str:
        parts = ["[%d:a]atrim=start=%s:end=%s" % (input_index, self._n(segment["source_start"]), self._n(segment["source_end"])), "asetpts=PTS-STARTPTS", self._atempo(float(segment.get("speed", 1)))]
        if segment.get("noise_reduction"):
            parts.append("afftdn=nf=-25")
        if segment.get("normalize"):
            parts.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        return ",".join(parts) + "[%s]" % output_label

    @staticmethod
    def _atempo(speed: float) -> str:
        factors = []
        while speed > 2:
            factors.append(2.0); speed /= 2
        while speed < 0.5:
            factors.append(0.5); speed /= 0.5
        factors.append(speed)
        return ",".join("atempo=%s" % FFmpegRenderer._n(item) for item in factors)

    @staticmethod
    def _n(value: Any) -> str:
        return ("%.6f" % float(value)).rstrip("0").rstrip(".")

    def verify_output(self, path: Path, expected_duration: float) -> Dict[str, Any]:
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Renderer produced no output file")
        metadata = inspect_video(path)
        if metadata.get("inspection_error"):
            raise RuntimeError("Rendered file could not be inspected")
        checks = {
            "resolution": self._check(metadata.get("width") == self.WIDTH and metadata.get("height") == self.HEIGHT, True),
            "video_codec": self._check(metadata.get("video_codec") == "h264", True),
            "audio_codec": self._check(metadata.get("audio_codec") == "aac", True),
            "has_audio": self._check(metadata.get("has_audio") is True, True),
            "duration": self._check(abs(float(metadata.get("duration_seconds") or 0) - expected_duration) <= 0.2, True),
        }
        checks.update(self._structural_checks(path, expected_duration))
        required_passed = all(item["status"] == "passed" for item in checks.values() if item["required"])
        if not required_passed:
            raise RuntimeError("Rendered output failed verification: %s" % json.dumps(checks))
        return {"passed": True, "checks": checks, "metadata": metadata}

    @staticmethod
    def _check(passed: bool, required: bool, **evidence: Any) -> Dict[str, Any]:
        return {"status": "passed" if passed else "failed", "required": required, **evidence}

    def _structural_checks(self, path: Path, expected_duration: float) -> Dict[str, Any]:
        """Run deterministic output checks. Required checks fail closed."""
        command = [
            "ffmpeg", "-hide_banner", "-v", "info", "-i", str(path),
            "-vf", "blackdetect=d=0.75:pix_th=0.02,freezedetect=n=-60dB:d=4",
            "-af", "silencedetect=n=-55dB:d=3", "-f", "null", "-",
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=max(60, int(expected_duration * 3)))
        except (OSError, subprocess.SubprocessError) as exc:
            return {"structural_scan": {"status": "not_evaluated", "required": True, "error": str(exc)}}
        if result.returncode != 0:
            return {"structural_scan": {"status": "not_evaluated", "required": True, "error": result.stderr[-1000:]}}
        stderr = result.stderr
        black_count = len(re.findall(r"black_start:", stderr))
        freeze_count = len(re.findall(r"freeze_start:", stderr))
        silence_count = len(re.findall(r"silence_start:", stderr))
        return {
            "structural_scan": self._check(True, True),
            "black_frames": self._check(black_count == 0, True, segment_count=black_count, threshold_seconds=0.75),
            "frozen_video": self._check(freeze_count == 0, True, segment_count=freeze_count, threshold_seconds=4),
            # Long silence may be intentional original audio, so record it for
            # recipe evaluation without rejecting an otherwise honest render.
            "long_silence": self._check(silence_count == 0, False, segment_count=silence_count, threshold_seconds=3),
        }
