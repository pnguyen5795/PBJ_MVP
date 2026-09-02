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
from .diff import timeline_diff
from .reducer import apply_inverse_transaction, apply_transaction
from .validation import validate_timeline


class StaleTimelineError(RuntimeError):
    def __init__(self, current: Dict[str, Any]):
        super().__init__("The timeline changed on another request")
        self.current = current


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
            history = {"schema_version": "1.0", "undo": [], "redo": [], "seen_transaction_ids": []}
            self.store.write_json(root / "history.json", history)
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
            history = self._history(project_id)
            history["undo"] = []
            history["redo"] = []
            self.store.write_json(root / "history.json", history)
            self._append_event(project_id, {
                "type": "timeline.ai_revision", "origin": "revision_feedback",
                "feedback": feedback, "before_hash": current["timeline_hash"],
                "timeline_hash": timeline["timeline_hash"], "revision": timeline["revision"],
            })
            return timeline

    def transact(self, project_id: str, transaction: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock(project_id):
            current = self.load(project_id)
            if transaction.get("base_revision") != current["revision"] or transaction.get("base_timeline_hash") != current["timeline_hash"]:
                raise StaleTimelineError(current)
            history = self._history(project_id)
            if transaction.get("transaction_id") in history.get("seen_transaction_ids", []):
                return {"timeline": current, "diff": {"idempotent": True}, "autosaved": True}
            updated, inverse = apply_transaction(current, transaction)
            diff = timeline_diff(current, updated)
            entry = {"transaction_id": transaction["transaction_id"], "transaction": deepcopy(transaction), "inverse": inverse, "diff": diff, "applied_at": utc_now()}
            history["undo"].append(entry)
            history["redo"] = []
            history.setdefault("seen_transaction_ids", []).append(transaction["transaction_id"])
            self.store.write_json(self.root(project_id) / "current.json", updated)
            self.store.write_json(self.root(project_id) / "history.json", history)
            self._append_event(project_id, {"type": "timeline.transaction", **entry, "revision": updated["revision"], "timeline_hash": updated["timeline_hash"]})
            return {"timeline": updated, "diff": diff, "autosaved": True}

    def undo(self, project_id: str) -> Dict[str, Any]:
        with self._lock(project_id):
            current = self.load(project_id)
            history = self._history(project_id)
            if not history["undo"]:
                return {"timeline": current, "diff": {"noop": True}, "autosaved": True}
            entry = history["undo"].pop()
            updated = apply_inverse_transaction(current, entry["inverse"])
            history["redo"].append(entry)
            diff = timeline_diff(current, updated)
            self.store.write_json(self.root(project_id) / "current.json", updated)
            self.store.write_json(self.root(project_id) / "history.json", history)
            self._append_event(project_id, {"type": "timeline.undo", "transaction_id": entry["transaction_id"], "diff": diff, "revision": updated["revision"], "timeline_hash": updated["timeline_hash"]})
            return {"timeline": updated, "diff": diff, "autosaved": True}

    def redo(self, project_id: str) -> Dict[str, Any]:
        with self._lock(project_id):
            current = self.load(project_id)
            history = self._history(project_id)
            if not history["redo"]:
                return {"timeline": current, "diff": {"noop": True}, "autosaved": True}
            entry = history["redo"].pop()
            replay = deepcopy(entry["transaction"])
            replay["base_revision"] = current["revision"]
            replay["base_timeline_hash"] = current["timeline_hash"]
            updated, inverse = apply_transaction(current, replay)
            entry["inverse"] = inverse
            history["undo"].append(entry)
            diff = timeline_diff(current, updated)
            self.store.write_json(self.root(project_id) / "current.json", updated)
            self.store.write_json(self.root(project_id) / "history.json", history)
            self._append_event(project_id, {"type": "timeline.redo", "transaction_id": entry["transaction_id"], "diff": diff, "revision": updated["revision"], "timeline_hash": updated["timeline_hash"]})
            return {"timeline": updated, "diff": diff, "autosaved": True}

    def snapshot(self, project_id: str, name: str) -> Path:
        timeline = self.load(project_id)
        path = self.root(project_id) / "snapshots" / (name + ".json")
        self.store.write_json(path, timeline)
        return path

    def register_asset(self, project_id: str, asset: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically add imported media to the asset registry without placing it."""
        with self._lock(project_id):
            timeline = self.load(project_id)
            if any(item.get("asset_id") == asset.get("asset_id") for item in timeline["assets"]):
                return timeline
            before_hash = timeline["timeline_hash"]
            timeline["assets"].append(deepcopy(asset))
            timeline["revision"] += 1
            refresh_hash(timeline)
            validate_timeline(timeline)
            self.store.write_json(self.root(project_id) / "current.json", timeline)
            self._append_event(project_id, {
                "type": "timeline.asset_registered", "asset_id": asset.get("asset_id"),
                "before_hash": before_hash, "timeline_hash": timeline["timeline_hash"], "revision": timeline["revision"],
            })
            return timeline

    def mark_asset_analyzed(self, project_id: str, asset_id: str) -> Dict[str, Any]:
        with self._lock(project_id):
            timeline = self.load(project_id)
            asset = next((item for item in timeline["assets"] if item.get("asset_id") == asset_id), None)
            if not asset:
                raise KeyError(asset_id)
            asset["analyzed"] = True
            asset["analysis_status"] = "complete"
            timeline["revision"] += 1
            refresh_hash(timeline)
            validate_timeline(timeline)
            self.store.write_json(self.root(project_id) / "current.json", timeline)
            self._append_event(project_id, {"type": "timeline.asset_analyzed", "asset_id": asset_id, "timeline_hash": timeline["timeline_hash"], "revision": timeline["revision"]})
            return timeline

    def mark_asset_analysis_failed(self, project_id: str, asset_id: str, error: str) -> Dict[str, Any]:
        with self._lock(project_id):
            timeline = self.load(project_id)
            asset = next((item for item in timeline["assets"] if item.get("asset_id") == asset_id), None)
            if not asset:
                raise KeyError(asset_id)
            asset["analyzed"] = False
            asset["analysis_status"] = "failed"
            asset["analysis_error"] = str(error)
            timeline["revision"] += 1
            refresh_hash(timeline)
            validate_timeline(timeline)
            self.store.write_json(self.root(project_id) / "current.json", timeline)
            self._append_event(project_id, {"type": "timeline.asset_analysis_failed", "asset_id": asset_id, "error": str(error), "timeline_hash": timeline["timeline_hash"], "revision": timeline["revision"]})
            return timeline

    def events(self, project_id: str):
        path = self.root(project_id) / "events.ndjson"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _history(self, project_id: str) -> Dict[str, Any]:
        path = self.root(project_id) / "history.json"
        history = self.store.read_json(path) if path.exists() else {"schema_version": "1.0", "undo": [], "redo": []}
        history.setdefault("seen_transaction_ids", [
            item.get("transaction_id") for item in history.get("undo", []) + history.get("redo", [])
            if item.get("transaction_id")
        ])
        return history

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
