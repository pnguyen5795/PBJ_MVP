from pathlib import Path
from typing import Any, Dict
import json
import shutil
import subprocess


def ffmpeg_status() -> Dict[str, Any]:
    return {
        "ffmpeg": shutil.which("ffmpeg"),
        "ffprobe": shutil.which("ffprobe"),
        "ready": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
    }


def inspect_video(path: Path) -> Dict[str, Any]:
    if not shutil.which("ffprobe"):
        return {"inspection_error": "ffprobe is not installed"}
    command = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path)
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
        payload = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"inspection_error": str(exc)}
    video = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), {})
    audio = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), {})
    fmt = payload.get("format", {})
    rotation = (video.get("tags") or {}).get("rotate")
    if rotation is None:
        rotation = next((item.get("rotation") for item in video.get("side_data_list", []) if item.get("rotation") is not None), 0)
    average_rate = video.get("avg_frame_rate")
    real_rate = video.get("r_frame_rate")
    return {
        "duration_seconds": _number(fmt.get("duration")),
        "size_bytes": _integer(fmt.get("size")),
        "format_name": fmt.get("format_name"),
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "frame_rate": average_rate,
        "real_frame_rate": real_rate,
        "variable_frame_rate": bool(average_rate and real_rate and average_rate != real_rate),
        "rotation": _integer(rotation) or 0,
        "color_transfer": video.get("color_transfer"),
        "color_primaries": video.get("color_primaries"),
        "color_space": video.get("color_space"),
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": _integer(audio.get("sample_rate")),
        "audio_channels": audio.get("channels"),
        "has_audio": bool(audio),
    }


def _number(value: Any):
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _integer(value: Any):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
