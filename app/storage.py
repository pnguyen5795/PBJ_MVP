from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List
import copy
import hashlib
import json
import re
import secrets
import shutil


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
ID_PATTERN = re.compile(r"^[a-z]+-[0-9]{8}-[a-f0-9]{6}$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    return cleaned or "video"


def new_id(prefix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d")
    return "%s-%s-%s" % (prefix, stamp, secrets.token_hex(3))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class JsonStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.assets_dir = data_dir / "assets"
        self.reference_assets_dir = self.assets_dir / "references"
        self.recipes_dir = data_dir / "recipes"
        # Keep the existing style-oriented application API while recipes remain
        # invisible internal infrastructure.
        self.styles_dir = self.recipes_dir
        self.projects_dir = data_dir / "projects"
        self.upload_sessions_dir = data_dir / "upload_sessions"
        self.cache_dir = data_dir / "cache"
        self.archive_dir = data_dir / "archive"
        self.deleted_styles_dir = self.archive_dir / "recipes"
        self.approved_examples_dir = data_dir / "approved_examples"
        self.user_preferences_dir = data_dir / "user_preferences"
        self.learning_suggestions_dir = data_dir / "learning_suggestions"
        for path in (
            self.reference_assets_dir,
            self.recipes_dir,
            self.projects_dir,
            self.upload_sessions_dir,
            self.cache_dir,
            self.deleted_styles_dir,
            self.approved_examples_dir,
            self.user_preferences_dir,
            self.learning_suggestions_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def write_json(path: Path, value: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(path)

    @staticmethod
    def read_json(path: Path) -> Dict[str, Any]:
        return json.loads(path.read_text())

    def list_records(self, parent: Path, filename: str) -> List[Dict[str, Any]]:
        records = []
        for path in sorted(parent.glob("*/" + filename), reverse=True):
            try:
                records.append(self.read_json(path))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def list_styles(self) -> List[Dict[str, Any]]:
        return self.list_records(self.styles_dir, "profile.json")

    def list_projects(self) -> List[Dict[str, Any]]:
        return self.list_records(self.projects_dir, "manifest.json")

    def list_approved_examples(self) -> List[Dict[str, Any]]:
        records = []
        for path in sorted(self.approved_examples_dir.glob("*.json"), reverse=True):
            try:
                records.append(self.read_json(path))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def backfill_permission_scopes(self) -> Dict[str, int]:
        """Attach project device ownership to older learning records in place."""
        project_devices = {
            item.get("project_id"): item.get("device_id")
            for item in self.list_projects() if item.get("project_id")
        }
        counts = {"signals": 0, "examples": 0, "evaluations": 0}
        for style_folder in self.styles_dir.glob("style-*"):
            for path in (style_folder / "learning" / "signals").glob("signal-*.json"):
                try:
                    record = self.read_json(path)
                except (OSError, json.JSONDecodeError):
                    continue
                project_id = record.get("project_id")
                if "device_id" not in record and project_id in project_devices:
                    record["device_id"] = project_devices[project_id]
                    self.write_json(path, record)
                    counts["signals"] += 1
            for path in (style_folder / "evaluations").glob("evaluation-*.json"):
                try:
                    record = self.read_json(path)
                except (OSError, json.JSONDecodeError):
                    continue
                project_id = record.get("project_id")
                if "device_id" not in record and project_id in project_devices:
                    record["device_id"] = project_devices[project_id]
                    self.write_json(path, record)
                    counts["evaluations"] += 1
        for path in self.approved_examples_dir.glob("example-*.json"):
            try:
                record = self.read_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            project_id = record.get("project_id")
            changed = False
            if "device_id" not in record and project_id in project_devices:
                record["device_id"] = project_devices[project_id]
                changed = True
            if "permission_scope" not in record:
                record["permission_scope"] = "device_private"
                changed = True
            if "founder_feedback" in record:
                record.setdefault("approval_feedback", record["founder_feedback"])
                record.pop("founder_feedback", None)
                changed = True
            if changed:
                self.write_json(path, record)
                counts["examples"] += 1
        return counts

    def save_learning_signal(self, style_id: str, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Persist every useful reference, revision, and approval lesson with scope."""
        source_key = signal.get("source_key")
        if source_key:
            existing = next((item for item in self.list_learning_signals(style_id) if item.get("source_key") == source_key), None)
            if existing:
                return existing
        record = {"schema_version": "1.0", "signal_id": new_id("signal"), "recorded_at": utc_now(), **copy.deepcopy(signal)}
        self.write_json(self.style_dir(style_id) / "learning" / "signals" / (record["signal_id"] + ".json"), record)
        self.rebuild_learning_state(style_id)
        return record

    def upsert_learning_signal(self, style_id: str, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Replace one scoped source-key outcome while preserving its stable ID.

        Timeline re-exports from one project are one supporting project, not
        duplicate evidence. The latest successful approval supersedes the
        earlier positive outcome while the append-only timeline events remain.
        """
        source_key = signal.get("source_key")
        existing = next((item for item in self.list_learning_signals(style_id) if item.get("source_key") == source_key), None) if source_key else None
        if not existing:
            return self.save_learning_signal(style_id, signal)
        record = {**existing, **copy.deepcopy(signal), "updated_at": utc_now()}
        self.write_json(self.style_dir(style_id) / "learning" / "signals" / (record["signal_id"] + ".json"), record)
        self.rebuild_learning_state(style_id)
        return record

    def list_learning_signals(self, style_id: str) -> List[Dict[str, Any]]:
        root = self.style_dir(style_id) / "learning" / "signals"
        records = []
        for path in sorted(root.glob("signal-*.json"), reverse=True):
            try:
                records.append(self.read_json(path))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def backfill_learning_signals(self, style_id: str) -> Dict[str, Any]:
        """Create learning events for useful history recorded before the loop existed."""
        from .learning import summarize_run_evidence

        style = self.style(style_id)
        if self.style_analyses(style_id):
            self.save_learning_signal(style_id, {
                "source_key": "reference-history:%s" % style_id,
                "type": "reference_analysis", "scope": "style_evidence",
                "reference_file_ids": [item.get("file_id") for item in style.get("reference_files", [])],
                "recipe_version": style.get("recipe_version"), "status": "candidate",
                "instruction": "Historical reference evidence used to build this recipe.",
            })
        for project in self.list_projects():
            if project.get("style_id") != style_id:
                continue
            self.save_learning_signal(style_id, {
                "source_key": "raw-history:%s" % project["project_id"],
                "type": "raw_footage_upload", "scope": "project_only", "project_id": project["project_id"],
                "device_id": project.get("device_id"),
                "file_count": len(project.get("raw_files", [])), "status": "context",
                "instruction": "Historical project footage inventory.",
            })
            for run in project.get("runs", []):
                def artifact(key: str):
                    relative = run.get(key)
                    if not relative:
                        return {}
                    path = self.resolve_data_path(relative)
                    return self.read_json(path) if path.exists() else {}
                self.save_learning_signal(style_id, {
                    "source_key": "run-history:%s:%s" % (project["project_id"], run["run_id"]),
                    "type": "rough_cut_run", "scope": "project_outcome",
                    "project_id": project["project_id"], "run_id": run["run_id"],
                    "device_id": project.get("device_id"),
                    "revision_number": run.get("revision_number"),
                    "recipe_version": project.get("recipe_version"), "status": "context",
                    "run_evidence": summarize_run_evidence(
                        run, artifact("plan_diff_path"), artifact("decisions_path"), artifact("render_receipt_path")
                    ),
                    "instruction": "Historical completed rough-cut evidence; use for comparison and evaluation, not direct recipe promotion.",
                })
                if not run.get("feedback"):
                    continue
                self.save_learning_signal(style_id, {
                    "source_key": "revision-history:%s:%s" % (project["project_id"], run["run_id"]),
                    "type": "cut_revision", "scope": "project_only", "project_id": project["project_id"],
                    "device_id": project.get("device_id"),
                    "revision_number": run.get("revision_number"), "instruction": run.get("feedback"), "status": "context",
                    "suggested_scope": "unclassified_historical_feedback",
                })
            approval = project.get("final_approval")
            if approval and approval.get("approved"):
                feedback = approval.get("feedback") or {}
                approved_run = next((item for item in project.get("runs", []) if item.get("run_id") == approval.get("run_id")), {})
                def approved_artifact(key: str):
                    relative = approved_run.get(key)
                    if not relative:
                        return {}
                    path = self.resolve_data_path(relative)
                    return self.read_json(path) if path.exists() else {}
                self.save_learning_signal(style_id, {
                    "source_key": "approval-history:%s:%s" % (project["project_id"], approval.get("run_id")),
                    "type": "approved_cut", "scope": "style_candidate", "project_id": project["project_id"],
                    "device_id": project.get("device_id"),
                    "revision_number": next((run.get("revision_number") for run in project.get("runs", []) if run.get("run_id") == approval.get("run_id")), None),
                    "scores": feedback.get("scores", {}), "comments": feedback.get("comments", ""),
                    "clip_feedback": feedback.get("clip_feedback", []), "status": "candidate",
                    "run_evidence": summarize_run_evidence(
                        approved_run, approved_artifact("plan_diff_path"),
                        approved_artifact("decisions_path"), approved_artifact("render_receipt_path")
                    ),
                    "instruction": "Historical approved result; generalize only with repeated compatible evidence.",
                })
                self.link_project_learning_outcome(style_id, project["project_id"], {
                    "approved": True, "approved_run_id": approval.get("run_id"), "scores": feedback.get("scores", {}),
                })
        return self.rebuild_learning_state(style_id)

    def rebuild_learning_state(self, style_id: str) -> Dict[str, Any]:
        from .learning import consolidate_signals
        state = consolidate_signals(self.list_learning_signals(style_id))
        state["style_id"] = style_id
        state["updated_at"] = utc_now()
        self.write_json(self.style_dir(style_id) / "learning" / "current.json", state)
        return state

    def learning_state(self, style_id: str) -> Dict[str, Any]:
        path = self.style_dir(style_id) / "learning" / "current.json"
        return self.read_json(path) if path.exists() else self.rebuild_learning_state(style_id)

    def link_project_learning_outcome(self, style_id: str, project_id: str, outcome: Dict[str, Any]) -> None:
        root = self.style_dir(style_id) / "learning" / "signals"
        for path in root.glob("signal-*.json"):
            signal = self.read_json(path)
            if signal.get("project_id") != project_id:
                continue
            signal["outcome"] = copy.deepcopy(outcome)
            signal["outcome_recorded_at"] = utc_now()
            self.write_json(path, signal)
        self.rebuild_learning_state(style_id)

    def style(self, style_id: str) -> Dict[str, Any]:
        return self.read_json(self.style_dir(style_id) / "profile.json")

    def project(self, project_id: str) -> Dict[str, Any]:
        return self.read_json(self.project_dir(project_id) / "manifest.json")

    def style_dir(self, style_id: str) -> Path:
        if not ID_PATTERN.fullmatch(style_id) or not style_id.startswith("style-"):
            raise FileNotFoundError(style_id)
        return self.styles_dir / style_id

    def project_dir(self, project_id: str) -> Path:
        if not ID_PATTERN.fullmatch(project_id) or not project_id.startswith("project-"):
            raise FileNotFoundError(project_id)
        return self.projects_dir / project_id

    def upload_session_dir(self, session_id: str) -> Path:
        if not ID_PATTERN.fullmatch(session_id) or not session_id.startswith("upload-"):
            raise FileNotFoundError(session_id)
        return self.upload_sessions_dir / session_id

    def create_upload_session(self, name: str, style_id: str, provider: str,
                              prompt: str = "", target_seconds: int = 60,
                              intent: Dict[str, Any] | None = None,
                              recipe_match: Dict[str, Any] | None = None,
                              device_id: str | None = None) -> Dict[str, Any]:
        session_id = new_id("upload")
        folder = self.upload_session_dir(session_id)
        folder.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": "2.0",
            "session_id": session_id,
            "name": name.strip(),
            "style_id": style_id,
            "provider": provider,
            "prompt": prompt.strip(),
            "target_duration_seconds": target_seconds,
            "intent_interpretation": intent,
            "recipe_match": recipe_match,
            "device_id": device_id,
            "created_at": utc_now(),
            "files": [],
        }
        self.write_json(folder / "manifest.json", manifest)
        return manifest

    def upload_session(self, session_id: str) -> Dict[str, Any]:
        return self.read_json(self.upload_session_dir(session_id) / "manifest.json")

    def update_upload_session(self, session_id: str, **changes: Any) -> Dict[str, Any]:
        manifest = self.upload_session(session_id)
        manifest.update(changes)
        self.write_json(self.upload_session_dir(session_id) / "manifest.json", manifest)
        return manifest

    def resolve_data_path(self, relative_path: str) -> Path:
        candidate = (self.data_dir / relative_path).resolve()
        data_root = self.data_dir.resolve()
        if data_root != candidate and data_root not in candidate.parents:
            raise ValueError("Stored path is outside the data directory")
        return candidate

    def analysis_cache_path(self, provider: str, purpose: str, source_sha256: str,
                            identity: Dict[str, str]) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", source_sha256 or ""):
            raise ValueError("Invalid analysis-cache checksum")
        identity_hash = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        return self.cache_dir / "video_analysis" / safe_name(provider) / safe_name(purpose) / (
            "%s-%s.json" % (source_sha256, identity_hash)
        )

    def cached_analysis(self, provider: str, purpose: str, source_sha256: str,
                        identity: Dict[str, str], file_id: str) -> Dict[str, Any] | None:
        path = self.analysis_cache_path(provider, purpose, source_sha256, identity)
        if not path.exists():
            return None
        try:
            cached = self.read_json(path)
        except (OSError, json.JSONDecodeError):
            return None
        if cached.get("provider") != provider or cached.get("model") != identity.get("model"):
            return None
        if cached.get("prompt_version") != identity.get("prompt_version"):
            return None
        if cached.get("cache_identity") != identity:
            return None
        result = copy.deepcopy(cached)
        source_usage = result.get("usage") or {}
        result["file_id"] = file_id
        result["usage"] = {}
        result.pop("remote_asset", None)
        result["cache"] = {
            "hit": True,
            "purpose": purpose,
            "source_sha256": source_sha256,
            "cached_at": cached.get("cache_recorded_at"),
            "source_usage_recorded": bool(source_usage),
        }
        return result

    def save_cached_analysis(self, provider: str, purpose: str, source_sha256: str,
                             identity: Dict[str, str], result: Dict[str, Any]) -> Path:
        record = copy.deepcopy(result)
        record.pop("remote_asset", None)
        record.pop("cache", None)
        record["model"] = identity["model"]
        record["prompt_version"] = identity["prompt_version"]
        record["cache_identity"] = copy.deepcopy(identity)
        record["cache_recorded_at"] = utc_now()
        record["cache_purpose"] = purpose
        path = self.analysis_cache_path(provider, purpose, source_sha256, identity)
        self.write_json(path, record)
        return path

    def update_style(self, style_id: str, **changes: Any) -> Dict[str, Any]:
        profile = self.style(style_id)
        profile.update(changes)
        profile["updated_at"] = utc_now()
        self.write_json(self.style_dir(style_id) / "profile.json", profile)
        return profile

    def save_recipe_draft(self, style_id: str, recipe: Dict[str, Any], version: str,
                          base_version: str = None) -> Dict[str, Any]:
        if not VERSION_PATTERN.fullmatch(version):
            raise ValueError("Invalid recipe version")
        now = utc_now()
        draft = copy.deepcopy(recipe)
        draft.update({
            "schema_version": "1.0",
            "recipe_id": style_id,
            "recipe_version": version,
            "status": "draft",
            "base_version": base_version,
            "created_at": now,
        })
        self.write_json(self.style_dir(style_id) / "drafts" / "current.json", draft)
        return draft

    def approve_recipe_version(self, style_id: str) -> Dict[str, Any]:
        profile = self.style(style_id)
        recipe = profile.get("recipe")
        version = profile.get("recipe_version")
        if not recipe or not version or not VERSION_PATTERN.fullmatch(version):
            raise ValueError("Create and review a recipe before approving it")
        frozen = copy.deepcopy(recipe)
        frozen["status"] = "validated"
        frozen["approved_at"] = utc_now()
        destination = self.style_dir(style_id) / "versions" / (version + ".json")
        if destination.exists():
            raise ValueError("This recipe version is already approved and immutable")
        self.write_json(destination, frozen)
        history = profile.get("recipe_history", []) + [{
            "recipe_version": version,
            "status": "validated",
            "approved_at": frozen["approved_at"],
            "path": str(destination.relative_to(self.data_dir)),
        }]
        self.write_json(self.style_dir(style_id) / "drafts" / "current.json", frozen)
        return self.update_style(
            style_id,
            recipe=frozen,
            recipe_status="validated",
            recipe_history=history,
            style_analysis=frozen,
            status="approved",
            approval={"approved": True, "approved_at": frozen["approved_at"], "recipe_version": version},
        )

    def recipe_version(self, style_id: str, version: str) -> Dict[str, Any]:
        if not VERSION_PATTERN.fullmatch(version):
            raise FileNotFoundError(version)
        return self.read_json(self.style_dir(style_id) / "versions" / (version + ".json"))

    def recipe_for_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        snapshot_path = project.get("recipe_snapshot_path")
        if snapshot_path:
            return self.read_json(self.resolve_data_path(snapshot_path))
        style = self.style(project["style_id"])
        return style.get("recipe") or style.get("style_analysis") or {}

    def delete_style(self, style_id: str) -> Path:
        """Move a style to a dated local archive so accidental deletion is recoverable."""
        source = self.style_dir(style_id)
        if not source.exists():
            raise FileNotFoundError(style_id)
        target = self.deleted_styles_dir / (style_id + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.move(str(source), str(target))
        return target

    def update_project(self, project_id: str, **changes: Any) -> Dict[str, Any]:
        manifest = self.project(project_id)
        manifest.update(changes)
        manifest["updated_at"] = utc_now()
        self.write_json(self.project_dir(project_id) / "manifest.json", manifest)
        return manifest

    def approve_project_run(self, project_id: str, run_id: str, feedback: Dict[str, Any]) -> Dict[str, Any]:
        project = self.project(project_id)
        run = next((item for item in project.get("runs", []) if item.get("run_id") == run_id), None)
        if not run:
            raise FileNotFoundError(run_id)
        style = self.style(project["style_id"])
        plan = self.read_json(self.resolve_data_path(run["plan_path"]))
        def run_artifact(key: str):
            relative = run.get(key)
            if not relative:
                return None
            path = self.resolve_data_path(relative)
            return self.read_json(path) if path.exists() else None
        record = {
            "schema_version": "3.0",
            "example_id": new_id("example"),
            "approved_at": utc_now(),
            "project_id": project_id,
            "project_name": project.get("name"),
            "device_id": project.get("device_id"),
            "permission_scope": "device_private",
            "run_id": run_id,
            "revision_number": run.get("revision_number"),
            "provider": project.get("provider"),
            "project_prompt": project.get("prompt"),
            "target_duration_seconds": project.get("target_duration_seconds"),
            "style_id": style.get("style_id"),
            "style_label": style.get("label"),
            "recipe_version": project.get("recipe_version"),
            "recipe": self.recipe_for_project(project),
            "content_map": project.get("content_map"),
            "initial_plan": self.read_json(self.resolve_data_path(project["runs"][0]["plan_path"])) if project.get("runs") else None,
            "approved_plan": plan,
            "approved_source_time_decisions": run_artifact("decisions_path"),
            "approved_plan_diff": run_artifact("plan_diff_path"),
            "approved_render_receipt": run_artifact("render_receipt_path"),
            "revision_history": [{"revision_number": item.get("revision_number"), "feedback": item.get("feedback"), "plan_path": item.get("plan_path")} for item in project.get("runs", [])],
            "approval_feedback": feedback,
        }
        from .learning import summarize_run_evidence
        approved_run_evidence = summarize_run_evidence(
            run,
            record["approved_plan_diff"] or {},
            record["approved_source_time_decisions"] or {},
            record["approved_render_receipt"] or {},
        )
        from .editorial_intelligence import approval_outcomes
        outcomes = approval_outcomes(record["initial_plan"] or {}, plan, len(project.get("runs", [])))
        record["outcome_metrics"] = outcomes
        evaluation = {
            "schema_version": "1.0",
            "evaluation_id": new_id("evaluation"),
            "recorded_at": record["approved_at"],
            "recipe_id": style.get("style_id"),
            "recipe_version": project.get("recipe_version"),
            "project_id": project_id,
            "device_id": project.get("device_id"),
            "approved_example_id": record["example_id"],
            "revision_count": len(project.get("runs", [])),
            "first_cut_approved": len(project.get("runs", [])) == 1,
            "outcome_metrics": outcomes,
            "scores": feedback.get("scores", {}),
            "issues": feedback.get("issues", []),
            "clip_feedback": feedback.get("clip_feedback", []),
            "comments": feedback.get("comments") or None,
            "run_evidence": approved_run_evidence,
            "intent_interpretation": project.get("intent_interpretation"),
            "recipe_match": project.get("recipe_match"),
            "retrieved_approved_examples": project.get("retrieved_approved_examples", []),
            "learning_status": "candidate_signal_saved",
            "applied_to_recipe": False,
        }
        self.write_json(
            self.style_dir(style["style_id"]) / "evaluations" / (evaluation["evaluation_id"] + ".json"),
            evaluation,
        )
        self.save_learning_signal(style["style_id"], {
            "source_key": "approval:%s:%s" % (project_id, run_id),
            "type": "approved_cut",
            "scope": "style_candidate",
            "project_id": project_id,
            "device_id": project.get("device_id"),
            "example_id": record["example_id"],
            "revision_number": run.get("revision_number"),
            "scores": feedback.get("scores", {}),
            "comments": feedback.get("comments", ""),
            "clip_feedback": feedback.get("clip_feedback", []),
            "run_evidence": approved_run_evidence,
            "outcome_metrics": outcomes,
            "instruction": "Use this approved result as evidence when evaluating similar projects; do not treat project-specific requests as universal rules.",
            "status": "candidate",
        })
        self.link_project_learning_outcome(style["style_id"], project_id, {
            "approved": True, "approved_run_id": run_id,
            "approved_revision_number": run.get("revision_number"),
            "scores": feedback.get("scores", {}),
        })
        record["recipe_evaluation_id"] = evaluation["evaluation_id"]
        self.write_json(self.approved_examples_dir / (record["example_id"] + ".json"), record)
        approval = {"approved": True, "approved_at": record["approved_at"], "run_id": run_id, "example_id": record["example_id"], "feedback": feedback}
        self.update_project(project_id, status="approved", final_approval=approval)
        return record

    def save_style_analysis(self, style_id: str, provider: str, file_id: str, result: Dict[str, Any]) -> Path:
        path = self.style_dir(style_id) / "analyses" / provider / (file_id + ".json")
        self.write_json(path, result)
        self.record_remote_asset(self.style_dir(style_id), provider, file_id, result.get("remote_asset"))
        return path

    def style_analyses(self, style_id: str) -> List[Dict[str, Any]]:
        results = []
        for path in sorted((self.style_dir(style_id) / "analyses").glob("*/*.json")):
            try:
                results.append(self.read_json(path))
            except (OSError, json.JSONDecodeError):
                continue
        return results

    def save_project_analysis(self, project_id: str, provider: str, file_id: str, result: Dict[str, Any]) -> Path:
        path = self.project_dir(project_id) / "analyses" / provider / (file_id + ".json")
        self.write_json(path, result)
        self.record_remote_asset(self.project_dir(project_id), provider, file_id, result.get("remote_asset"))
        return path

    def project_analyses(self, project_id: str, provider: str = None) -> List[Dict[str, Any]]:
        root = self.project_dir(project_id) / "analyses"
        pattern = (provider + "/*.json") if provider else "*/*.json"
        results = []
        for path in sorted(root.glob(pattern)):
            try:
                results.append(self.read_json(path))
            except (OSError, json.JSONDecodeError):
                continue
        return results

    def record_remote_asset(self, owner_dir: Path, provider: str, file_id: str, asset: Any) -> None:
        if not asset:
            return
        path = owner_dir / "remote_assets.json"
        record = self.read_json(path) if path.exists() else {"assets": []}
        if not any(item.get("provider") == provider and item.get("id") == asset.get("id") for item in record["assets"]):
            record["assets"].append({"provider": provider, "file_id": file_id, **asset, "recorded_at": utc_now()})
            self.write_json(path, record)

    def remote_assets(self) -> List[Dict[str, Any]]:
        assets = []
        for owner_type, parent in (("style", self.styles_dir), ("project", self.projects_dir)):
            for path in sorted(parent.glob("*/remote_assets.json")):
                try:
                    record = self.read_json(path)
                except (OSError, json.JSONDecodeError):
                    continue
                for item in record.get("assets", []):
                    assets.append({**item, "owner_type": owner_type, "owner_id": path.parent.name})
        return sorted(assets, key=lambda item: item.get("recorded_at", ""), reverse=True)

    def mark_remote_asset_deleted(self, owner_type: str, owner_id: str, provider: str, asset_id: str) -> Dict[str, Any]:
        owner_dir = self.style_dir(owner_id) if owner_type == "style" else self.project_dir(owner_id)
        path = owner_dir / "remote_assets.json"
        record = self.read_json(path)
        match = next((item for item in record.get("assets", []) if item.get("provider") == provider and item.get("id") == asset_id), None)
        if not match:
            raise FileNotFoundError(asset_id)
        match["status"] = "deleted"
        match["retained"] = False
        match["deleted_at"] = utc_now()
        self.write_json(path, record)
        return match

    def create_style(self, label: str, reference_paths: Iterable[Path], metadata: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        style_id = new_id("style")
        folder = self.styles_dir / style_id
        folder.mkdir(parents=True)
        files = []
        for index, source in enumerate(reference_paths, start=1):
            checksum = sha256(source)
            suffix = source.suffix.lower() if source.suffix else ".video"
            target = self.reference_assets_dir / (checksum + suffix)
            if not target.exists():
                shutil.copy2(str(source), str(target))
            files.append({
                "file_id": "reference-%03d" % index,
                "original_name": source.name,
                "stored_path": str(target.relative_to(self.data_dir)),
                "sha256": checksum,
                "metadata": metadata.get(str(source), {}),
            })
        profile = {
            "schema_version": "2.0",
            "style_id": style_id,
            "label": label.strip() or style_id,
            "status": "references_uploaded",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "reference_files": files,
            "recipe": None,
            "recipe_version": "0.0.0",
            "recipe_status": "draft",
            "recipe_ownership": "platform",
            "recipe_visibility": "internal",
            "recipe_history": [],
            "actionable_traits": [],
            "observed_but_unsupported_traits": [],
            "style_analysis": None,
            "analysis_runs": {},
            "last_error": None,
            "approval": {"approved": False, "approved_at": None},
        }
        self.write_json(folder / "profile.json", profile)
        self.write_json(folder / "remote_assets.json", {"assets": []})
        return profile

    def create_project(self, name: str, style_id: str, provider: str, prompt: str,
                       target_seconds: int, raw_paths: Iterable[Path],
                       metadata: Dict[str, Dict[str, Any]],
                       intent: Dict[str, Any] | None = None,
                       recipe_match: Dict[str, Any] | None = None,
                       device_id: str | None = None) -> Dict[str, Any]:
        project_id = new_id("project")
        folder = self.projects_dir / project_id
        raw_dir = folder / "raw"
        raw_dir.mkdir(parents=True)
        files = []
        for index, source in enumerate(raw_paths, start=1):
            name_on_disk = "%03d-%s" % (index, safe_name(source.name))
            target = raw_dir / name_on_disk
            shutil.copy2(str(source), str(target))
            files.append({
                "file_id": "raw-%03d" % index,
                "original_name": source.name,
                "stored_path": str(target.relative_to(self.data_dir)),
                "sha256": sha256(target),
                "metadata": metadata.get(str(source), {}),
                "analysis_status": "pending",
            })
        style = self.style(style_id)
        recipe = style.get("recipe") or style.get("style_analysis") or {}
        recipe_version = style.get("recipe_version") or "0.0.0"
        snapshot_path = folder / "recipe_snapshot.json"
        self.write_json(snapshot_path, copy.deepcopy(recipe))
        manifest = {
            "schema_version": "3.0",
            "project_id": project_id,
            "name": name.strip() or project_id,
            "style_id": style_id,
            "recipe_version": recipe_version,
            "recipe_snapshot_path": str(snapshot_path.relative_to(self.data_dir)),
            "provider": provider,
            "prompt": prompt.strip(),
            "target_duration_seconds": target_seconds,
            "intent_interpretation": intent,
            "recipe_match": recipe_match,
            "device_id": device_id,
            "retrieved_approved_examples": [],
            "status": "footage_uploaded",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "raw_files": files,
            "runs": [],
            "content_map": None,
            "last_error": None,
        }
        self.write_json(folder / "manifest.json", manifest)
        self.write_json(folder / "remote_assets.json", {"assets": []})
        return manifest

    def delete_project(self, project_id: str) -> None:
        """Delete one local project and its media. Remote provider assets are separate."""
        folder = self.project_dir(project_id)
        if not folder.exists():
            raise FileNotFoundError(project_id)
        shutil.rmtree(folder)
