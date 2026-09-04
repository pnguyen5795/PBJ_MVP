from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any, Dict
import json

from ..storage import JsonStore, utc_now
from .contracts import canonical_json
from .contracts import refresh_hash
from .validation import validate_timeline


class TimelineStore:
    _locks: Dict[str, Lock] = {}
    _locks_guard = Lock()

    def __init__(self, store: JsonStore):
        self.store = store

    def root(self, project_id: str) -> Path:
        return self.store.project_dir(project_id) / "timeline"

    def _lock(self, project_id: str) -> Lock:
        with self._locks_guard:
            return self._locks.setdefault(project_id, Lock())

    def exists(self, project_id: str) -> bool:
        return (self.root(project_id) / "current.json").exists()

    def load(self, project_id: str) -> Dict[str, Any]:
        timeline = self.store.read_json(self.root(project_id) / "current.json")
        validate_timeline(timeline)
        return timeline

    def initialize(self, project_id: str, timeline: Dict[str, Any], *, origin: str = "ai_initial") -> Dict[str, Any]:
        with self._lock(project_id):
            root = self.root(project_id)
            root.mkdir(parents=True, exist_ok=True)
            if (root / "current.json").exists():
                return self.load(project_id)
            validate_timeline(timeline)
            self.store.write_json(root / "current.json", timeline)
            self.store.write_json(root / "snapshots" / "initial-ai.json", timeline)
            self._append_event(project_id, {"type": "timeline.initialized", "origin": origin, "timeline_hash": timeline["timeline_hash"], "revision": timeline["revision"]})
            return deepcopy(timeline)

    def replace_with_ai_revision(self, project_id: str, timeline: Dict[str, Any], feedback: str) -> Dict[str, Any]:
        """Replace the working cut with a validated AI revision while preserving the original baseline."""
        with self._lock(project_id):
            current = self.load(project_id)
            validate_timeline(timeline)
            timeline = deepcopy(timeline)
            timeline["revision"] = int(current.get("revision", 0)) + 1
            refresh_hash(timeline)
            validate_timeline(timeline)
            root = self.root(project_id)
            self.store.write_json(root / "current.json", timeline)
            self.store.write_json(root / "snapshots" / ("ai-revision-%d.json" % timeline["revision"]), timeline)
            self._append_event(project_id, {
                "type": "timeline.ai_revision", "origin": "revision_feedback",
                "feedback": feedback, "before_hash": current["timeline_hash"],
                "timeline_hash": timeline["timeline_hash"], "revision": timeline["revision"],
            })
            return timeline

    def events(self, project_id: str):
        path = self.root(project_id) / "events.ndjson"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _append_event(self, project_id: str, event: Dict[str, Any]) -> None:
        path = self.root(project_id) / "events.ndjson"
        previous = "0" * 64
        if path.exists():
            lines = [line for line in path.read_text().splitlines() if line.strip()]
            if lines:
                previous = json.loads(lines[-1])["event_hash"]
        record = {"schema_version": "1.0", "recorded_at": utc_now(), "previous_event_hash": previous, **deepcopy(event)}
        record["event_hash"] = sha256((previous + canonical_json(record)).encode("utf-8")).hexdigest()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
