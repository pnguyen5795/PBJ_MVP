from __future__ import annotations

from array import array
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable
import json
import shutil
import subprocess

from ..media import inspect_video
from ..storage import JsonStore, utc_now


PROXY_PROFILE_VERSION = "iphone-preview-v1"


class ProxyError(RuntimeError):
    pass


class ProxyPipeline:
    """Create per-source browser media; never combines the project timeline."""

    def __init__(self, store: JsonStore):
        self.store = store

    def asset_root(self, project_id: str, asset_id: str) -> Path:
        return self.store.project_dir(project_id) / "proxies" / asset_id

    def ensure_project(self, project: Dict[str, Any], *, asset_ids: Iterable[str] | None = None) -> Dict[str, Any]:
        selected = set(asset_ids or [item["file_id"] for item in project.get("raw_files", [])])
        results = []
        for raw in project.get("raw_files", []):
            if raw["file_id"] in selected:
                results.append(self.ensure_asset(project["project_id"], raw))
        return {"profile_version": PROXY_PROFILE_VERSION, "assets": results,
                "cache_hits": sum(bool(item.get("cache_hit")) for item in results)}

    def ensure_asset(self, project_id: str, asset: Dict[str, Any], *,
                     include_waveform: bool = False, include_thumbnails: bool = False) -> Dict[str, Any]:
        source = self.store.resolve_data_path(asset["stored_path"])
        if not source.exists():
            raise ProxyError("Original source is missing: %s" % asset["file_id"])
        checksum = asset.get("sha256") or self._checksum(source)
        root = self.asset_root(project_id, asset["file_id"])
        manifest_path = root / "manifest.json"
        existing = self.store.read_json(manifest_path) if manifest_path.exists() else None
        if existing and (existing.get("source_sha256") != checksum or existing.get("profile_version") != PROXY_PROFILE_VERSION):
            existing = None
        root.mkdir(parents=True, exist_ok=True)
        thumbs = root / "thumbnails"
        metadata = asset.get("metadata") or inspect_video(source)
        preview = root / "preview.mp4"
        did_work = False
        if not preview.exists():
            self._make_preview(source, preview, metadata)
            did_work = True
        preview_metadata = inspect_video(preview)
        if include_thumbnails and not any(thumbs.glob("*.jpg")):
            thumbs.mkdir(parents=True, exist_ok=True)
            self._make_thumbnails(preview, thumbs)
            did_work = True
        waveform_path = root / "waveform.json"
        if include_waveform and not waveform_path.exists():
            self._make_waveform(source, waveform_path, bool(metadata.get("has_audio")))
            did_work = True
        duration_us = int(round(float(metadata.get("duration_seconds") or 0) * 1_000_000))
        mapping = {
            "schema_version": "1.0", "profile_version": PROXY_PROFILE_VERSION,
            "source_timebase": "microseconds", "proxy_timebase": "frames@30fps",
            "source_duration_us": duration_us,
            "anchors": [{"proxy_frame": 0, "source_us": 0},
                        {"proxy_frame": int(round(duration_us / 1_000_000 * 30)), "source_us": duration_us}],
            "vfr_normalized": bool(metadata.get("variable_frame_rate")),
        }
        mapping_path = root / "timestamp-map.json"
        if not mapping_path.exists():
            self.store.write_json(mapping_path, mapping)
        relative = lambda path: str(path.relative_to(self.store.data_dir))
        thumb_paths = sorted(relative(path) for path in thumbs.glob("*.jpg"))
        manifest = {
            "schema_version": "1.0", "asset_id": asset["file_id"], "source_sha256": checksum,
            "profile_version": PROXY_PROFILE_VERSION,
            "created_at": (existing or {}).get("created_at") or utc_now(), "cache_hit": not did_work,
            "preview_path": relative(preview), "thumbnail_paths": thumb_paths,
            "waveform_path": relative(waveform_path) if waveform_path.exists() else None,
            "timestamp_map_path": relative(mapping_path),
            "preview_metadata": preview_metadata,
            "waveform_points": len(self.store.read_json(waveform_path).get("peaks", [])) if waveform_path.exists() else 0,
            "required_paths": [relative(preview), relative(mapping_path)],
            "provider_analysis_cost": 0, "combined_timeline_render": False,
        }
        self.store.write_json(manifest_path, manifest)
        return manifest

    def ensure_audio_asset(self, project_id: str, asset: Dict[str, Any], *, include_waveform: bool = False) -> Dict[str, Any]:
        source = self.store.resolve_data_path(asset["stored_path"])
        checksum = asset.get("sha256") or self._checksum(source)
        root = self.asset_root(project_id, asset["file_id"])
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "manifest.json"
        existing = self.store.read_json(manifest_path) if manifest_path.exists() else None
        if existing and (existing.get("source_sha256") != checksum or existing.get("profile_version") != PROXY_PROFILE_VERSION):
            existing = None
        preview = root / "preview.m4a"
        did_work = False
        if not preview.exists():
            result = subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                "-vn", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", str(preview),
            ], capture_output=True, text=True)
            if result.returncode != 0:
                raise ProxyError("Could not create audio preview: %s" % result.stderr[-1000:])
            did_work = True
        waveform_path = root / "waveform.json"
        if include_waveform and not waveform_path.exists():
            self._make_waveform(source, waveform_path, True)
            did_work = True
        relative = lambda path: str(path.relative_to(self.store.data_dir))
        manifest = {
            "schema_version": "1.0", "asset_id": asset["file_id"], "source_sha256": checksum,
            "profile_version": PROXY_PROFILE_VERSION,
            "created_at": (existing or {}).get("created_at") or utc_now(), "cache_hit": not did_work,
            "preview_path": relative(preview), "waveform_path": relative(waveform_path) if waveform_path.exists() else None,
            "thumbnail_paths": [], "timestamp_map_path": None,
            "waveform_points": len(self.store.read_json(waveform_path).get("peaks", [])) if waveform_path.exists() else 0,
            "required_paths": [relative(preview)],
            "provider_analysis_cost": 0, "combined_timeline_render": False,
        }
        self.store.write_json(manifest_path, manifest)
        return manifest

    @staticmethod
    def _make_preview(source: Path, target: Path, metadata: Dict[str, Any]) -> None:
        if not shutil.which("ffmpeg"):
            raise ProxyError("FFmpeg is required to prepare preview media")
        hdr = str(metadata.get("color_transfer") or "").lower() in {"smpte2084", "arib-std-b67"}
        scale = "scale=w='if(gt(iw,ih),min(1280,iw),min(720,iw))':h=-2"
        video_filter = scale
        if hdr:
            video_filter = "zscale=t=linear:npl=100,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv," + scale
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?", "-vf", video_filter, "-r", "30", "-fps_mode", "cfr",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(target),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 and hdr:
            command[command.index(video_filter)] = scale
            result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise ProxyError("Could not create preview for %s: %s" % (source.name, result.stderr[-1200:]))

    @staticmethod
    def _make_thumbnails(preview: Path, folder: Path) -> None:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(preview),
            "-vf", "fps=1/5,scale=160:-2,format=yuvj420p", "-q:v", "4", "-strict", "unofficial", str(folder / "%05d.jpg"),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise ProxyError("Could not create thumbnail strip: %s" % result.stderr[-1000:])

    @staticmethod
    def _make_waveform(source: Path, target: Path, has_audio: bool) -> Dict[str, Any]:
        peaks = []
        if has_audio:
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "2000", "-f", "s16le", "-"]
            result = subprocess.run(command, capture_output=True)
            if result.returncode != 0:
                raise ProxyError("Could not create waveform: %s" % result.stderr.decode(errors="replace")[-1000:])
            samples = array("h")
            samples.frombytes(result.stdout)
            bucket = max(1, len(samples) // 1200)
            for offset in range(0, len(samples), bucket):
                window = samples[offset:offset + bucket]
                peaks.append(round(max((abs(value) for value in window), default=0) / 32768, 4))
        payload = {"schema_version": "1.0", "sample_rate": 2000, "peaks": peaks, "has_audio": has_audio}
        target.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
        return payload

    @staticmethod
    def _checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
