from typing import Any, Dict, Iterable, List
import asyncio

from .decision import OpenAIDecisionEngine
from .learning import consolidate_signals, permission_scoped_signals, relevant_signals
from .editorial_intelligence import retrieve_approved_examples
from .costing import analysis_cost_summary
from .providers import PROVIDERS
from .provenance import source_time_decisions
from .storage import JsonStore, new_id, utc_now
from .timeline.migration import timeline_from_edit_plan
from .timeline.proxies import ProxyPipeline
from .timeline.storage import TimelineStore


def failure_fields(exc: Exception) -> Dict[str, Any]:
    technical = str(exc)
    lowered = technical.lower()
    if "insufficient_quota" in lowered or "exceeded your current quota" in lowered:
        message = "OpenAI has no API quota available. Add billing or credits in the OpenAI API account, then retry; completed video analysis will be reused."
    elif "response_format_invalid" in lowered:
        message = "The video analyzer rejected the requested response format. The technical details were saved for debugging."
    elif "nodename nor servname" in lowered or "connecterror" in lowered:
        message = "The provider could not be reached. Check the internet connection and retry."
    else:
        message = technical if len(technical) <= 500 else technical[:497] + "..."
    return {
        "last_error": message,
        "last_error_details": {"type": type(exc).__name__, "message": technical, "recorded_at": utc_now()},
    }


def analysis_cache_identity(analyzer: Any, permission_scope: str) -> Dict[str, str] | None:
    identity = analyzer.cache_identity() if hasattr(analyzer, "cache_identity") else None
    if not isinstance(identity, dict) or not identity.get("model") or not identity.get("prompt_version"):
        return None
    return {
        "model": str(identity["model"]),
        "prompt_version": str(identity["prompt_version"]),
        "permission_scope": permission_scope,
    }


async def analyze_with_retry(analyzer: Any, source: Any, file_id: str, purpose: str,
                             retry_delays: Iterable[float]) -> Dict[str, Any]:
    """Retry a provider call while keeping completed files safely cached."""
    delays = list(retry_delays)
    attempts = len(delays) + 1
    for attempt in range(attempts):
        try:
            result = await analyzer.analyze(source, file_id, purpose)
            result["attempt_count"] = attempt + 1
            return result
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if isinstance(status_code, int) and 400 <= status_code < 500 and status_code != 429:
                raise
            if attempt == attempts - 1:
                raise
            if delays[attempt] > 0:
                await asyncio.sleep(delays[attempt])


class StyleWorkflow:
    def __init__(self, store: JsonStore, analyzers: Dict[str, Any] = None, decision_engine: Any = None,
                 retry_delays: Iterable[float] = (1, 3)):
        self.store = store
        self.analyzers = analyzers or {name: cls() for name, cls in PROVIDERS.items()}
        self.decision_engine = decision_engine or OpenAIDecisionEngine()
        self.retry_delays = tuple(retry_delays)

    async def analyze(self, style_id: str, providers: Iterable[str], refresh: bool = False) -> Dict[str, Any]:
        profile = self.store.update_style(style_id, status="analyzing_references", last_error=None)
        chosen = list(dict.fromkeys(providers))
        if not chosen or any(name not in self.analyzers for name in chosen):
            raise ValueError("Choose at least one valid analyzer")
        try:
            existing = {(item.get("provider"), item.get("file_id")): item for item in self.store.style_analyses(style_id)}
            for provider_name in chosen:
                analyzer = self.analyzers[provider_name]
                if hasattr(analyzer, "readiness") and not analyzer.readiness().configured:
                    raise RuntimeError("%s is not configured" % provider_name.title())
                for reference in profile["reference_files"]:
                    key = (provider_name, reference["file_id"])
                    if key in existing and not refresh:
                        continue
                    reference["analysis_status"] = "analyzing"
                    reference.pop("analysis_error", None)
                    self.store.update_style(style_id, reference_files=profile["reference_files"])
                    source = self.store.resolve_data_path(reference["stored_path"])
                    permission_scope = (
                        "device:%s" % (profile.get("device_id") or "legacy-local")
                        if profile.get("project_private") else "shared-recipe-evidence"
                    )
                    identity = analysis_cache_identity(analyzer, permission_scope)
                    result = None
                    if identity and not refresh:
                        result = self.store.cached_analysis(
                            provider_name, "style_reference", reference["sha256"], identity, reference["file_id"],
                        )
                    try:
                        if result is None:
                            result = await analyze_with_retry(
                                analyzer, source, reference["file_id"], "style_reference", self.retry_delays,
                            )
                    except Exception as exc:
                        reference["analysis_status"] = "failed"
                        reference["analysis_error"] = failure_fields(exc)["last_error"]
                        self.store.update_style(style_id, reference_files=profile["reference_files"])
                        raise
                    result["duration_seconds"] = reference.get("metadata", {}).get("duration_seconds")
                    result["source_sha256"] = reference["sha256"]
                    result["completed_at"] = utc_now()
                    self.store.record_remote_asset(
                        self.store.style_dir(style_id), provider_name,
                        reference["file_id"], result.get("remote_asset"),
                    )
                    self._validate_analysis(result)
                    self.store.save_style_analysis(style_id, provider_name, reference["file_id"], result)
                    if identity and not (result.get("cache") or {}).get("hit"):
                        self.store.save_cached_analysis(
                            provider_name, "style_reference", reference["sha256"], identity, result,
                        )
                    reference["analysis_status"] = "complete"
                    reference.pop("analysis_error", None)
                    self.store.update_style(style_id, reference_files=profile["reference_files"])
            analyses = self.store.style_analyses(style_id)
            synthesis = await self.decision_engine.synthesize_style(analyses)
            self._normalize_recipe_evidence(synthesis, profile, analyses)
            self._normalize_recipe_counts(synthesis, profile)
            self._validate_recipe(synthesis, profile, analyses)
            version = self._draft_version(profile)
            base_version = profile.get("recipe_version") if profile.get("recipe_status") == "validated" else None
            recipe = self.store.save_recipe_draft(style_id, synthesis, version, base_version)
            self.store.save_learning_signal(style_id, {
                "source_key": "reference:%s:%s" % (style_id, version),
                "type": "reference_analysis",
                "scope": "style_evidence",
                "reference_file_ids": [item.get("file_id") for item in profile.get("reference_files", [])],
                "provider_models": sorted({item.get("model") for item in analyses if item.get("model")}),
                "recipe_version": version,
                "status": "candidate",
                "instruction": "Use recurring evidence from these references to distinguish core style rules from one-off choices.",
            })
            supported = [rule for rule in recipe["rules"] if rule["renderer_support"] in ("supported", "partial")]
            unsupported = [rule for rule in recipe["rules"] if rule["renderer_support"] == "unsupported"]
            return self.store.update_style(
                style_id, status="ready_for_review", style_analysis=recipe, recipe=recipe,
                recipe_version=version, recipe_status="testing",
                actionable_traits=supported,
                observed_but_unsupported_traits=unsupported + recipe.get("unsupported_observations", []),
                analysis_runs={name: len([a for a in analyses if a.get("provider") == name]) for name in self.analyzers},
                cost_summary=analysis_cost_summary(analyses),
                approval={"approved": False, "approved_at": None, "recipe_version": None},
            )
        except Exception as exc:
            analyses_now = self.store.style_analyses(style_id)
            if analyses_now and all(item.get("analysis", {}).get("segments") is not None for item in analyses_now):
                self.store.update_style(style_id, status="analysis_complete_synthesis_failed", **failure_fields(exc))
            else:
                self.store.update_style(style_id, status="analysis_failed", **failure_fields(exc))
            raise

    def approve(self, style_id: str) -> Dict[str, Any]:
        profile = self.store.style(style_id)
        if not profile.get("recipe"):
            raise ValueError("Analyze and review this editing recipe before approving it")
        approved = self.store.approve_recipe_version(style_id)
        self.store.save_learning_signal(style_id, {
            "source_key": "recipe-approval:%s:%s" % (style_id, approved.get("recipe_version")),
            "type": "recipe_version_approved", "scope": "recipe_governance",
            "recipe_version": approved.get("recipe_version"), "status": "confirmed",
            "instruction": "This evidence-backed recipe version was reviewed and approved; the event records governance and is not independent style evidence.",
        })
        return self.store.style(style_id)

    async def revise(self, style_id: str, feedback: str) -> Dict[str, Any]:
        profile = self.store.update_style(style_id, status="revising_style", last_error=None)
        if not profile.get("recipe"):
            raise ValueError("Analyze this recipe before revising it")
        if not feedback.strip():
            raise ValueError("Describe what should change in the editing recipe")
        try:
            revised = await self.decision_engine.revise_style(profile["recipe"], feedback.strip())
            self._normalize_recipe_evidence(revised, profile, self.store.style_analyses(style_id))
            self._normalize_recipe_counts(revised, profile)
            self._validate_recipe(revised, profile, self.store.style_analyses(style_id))
            version = self._increment_minor(profile.get("recipe_version") or "0.0.0")
            recipe = self.store.save_recipe_draft(style_id, revised, version, profile.get("recipe_version"))
            self.store.save_learning_signal(style_id, {
                "source_key": "recipe-correction:%s:%s" % (style_id, version),
                "type": "recipe_correction", "scope": "recipe_governance",
                "recipe_version": version, "previous_recipe_version": profile.get("recipe_version"),
                "status": "candidate", "instruction": feedback.strip(),
            })
            history = profile.get("revision_history", []) + [{
                "revision_number": len(profile.get("revision_history", [])) + 1,
                "feedback": feedback.strip(), "revised_at": utc_now(),
                "previous_recipe_version": profile.get("recipe_version"),
                "previous_recipe": profile["recipe"],
            }]
            supported = [rule for rule in recipe["rules"] if rule["renderer_support"] in ("supported", "partial")]
            unsupported = [rule for rule in recipe["rules"] if rule["renderer_support"] == "unsupported"]
            return self.store.update_style(
                style_id, status="ready_for_review", style_analysis=recipe, recipe=recipe,
                recipe_version=version, recipe_status="testing",
                actionable_traits=supported,
                observed_but_unsupported_traits=unsupported + recipe.get("unsupported_observations", []),
                revision_history=history,
                approval={"approved": False, "approved_at": None, "recipe_version": None},
            )
        except Exception as exc:
            self.store.update_style(style_id, status="revision_failed", **failure_fields(exc))
            raise

    @staticmethod
    def _increment_minor(version: str) -> str:
        try:
            major, minor, _patch = (int(item) for item in version.split("."))
        except (AttributeError, TypeError, ValueError):
            return "1.0.0"
        if major == 0:
            return "1.0.0"
        return "%d.%d.0" % (major, minor + 1)

    @classmethod
    def _draft_version(cls, profile: Dict[str, Any]) -> str:
        current = profile.get("recipe_version") or "0.0.0"
        if not profile.get("recipe") or current == "0.0.0":
            return "1.0.0"
        if profile.get("recipe_status") == "validated":
            return cls._increment_minor(current)
        return current

    @staticmethod
    def _normalize_recipe_counts(recipe: Dict[str, Any], profile: Dict[str, Any]) -> None:
        """Derive recurrence counts from cited evidence instead of trusting model arithmetic."""
        reference_ids = {item["file_id"] for item in profile.get("reference_files", [])}
        for rule in recipe.get("rules") or []:
            cited = {item.get("reference_file_id") for item in rule.get("evidence") or []}
            rule["total_reference_count"] = len(reference_ids)
            rule["supporting_reference_count"] = len(cited & reference_ids)

    @staticmethod
    def _normalize_recipe_evidence(recipe: Dict[str, Any], profile: Dict[str, Any], analyses: List[Dict[str, Any]]) -> None:
        """Keep model-cited evidence tied to the named segment, tolerating editorial boundary drift."""
        reference_by_alias = {}
        for reference in profile.get("reference_files", []):
            reference_by_alias[reference.get("file_id")] = reference.get("file_id")
            reference_by_alias[reference.get("original_name")] = reference.get("file_id")
        segments = {}
        for analysis in analyses:
            for segment in analysis.get("analysis", {}).get("segments", []):
                segments.setdefault((analysis.get("file_id"), segment.get("segment_id")), []).append(segment)
        for rule in recipe.get("rules") or []:
            for evidence in rule.get("evidence") or []:
                evidence["reference_file_id"] = reference_by_alias.get(evidence.get("reference_file_id"), evidence.get("reference_file_id"))
                matches = segments.get((evidence.get("reference_file_id"), evidence.get("segment_id")))
                if not matches:
                    continue
                segment = matches[0]
                start = max(float(segment["start_seconds"]), float(evidence.get("start_seconds", segment["start_seconds"])))
                end = min(float(segment["end_seconds"]), float(evidence.get("end_seconds", segment["end_seconds"])))
                if end <= start:
                    start, end = float(segment["start_seconds"]), float(segment["end_seconds"])
                evidence["start_seconds"] = round(start, 3)
                evidence["end_seconds"] = round(end, 3)

    @staticmethod
    def _validate_recipe(recipe: Dict[str, Any], profile: Dict[str, Any], analyses: List[Dict[str, Any]]) -> None:
        rules = recipe.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ValueError("Recipe synthesis returned no evidence-backed rules")
        reference_ids = {item["file_id"] for item in profile.get("reference_files", [])}
        total_references = len(reference_ids)
        segment_index = {}
        for analysis in analyses:
            file_id = analysis.get("file_id")
            for segment in analysis.get("analysis", {}).get("segments", []):
                segment_index.setdefault((file_id, segment.get("segment_id")), []).append(segment)
        seen_rule_ids = set()
        for rule in rules:
            rule_id = rule.get("rule_id")
            if not rule_id or rule_id in seen_rule_ids:
                raise ValueError("Recipe rules must have unique rule IDs")
            seen_rule_ids.add(rule_id)
            if rule.get("total_reference_count") != total_references:
                raise ValueError("Recipe rule reference totals do not match the uploaded references")
            evidence = rule.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("Every recipe rule must cite timestamped reference evidence")
            supporting_ids = set()
            for item in evidence:
                file_id = item.get("reference_file_id")
                key = (file_id, item.get("segment_id"))
                start, end = item.get("start_seconds"), item.get("end_seconds")
                if file_id not in reference_ids or key not in segment_index:
                    raise ValueError("Recipe evidence references an unknown source segment")
                if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start < 0 or end <= start:
                    raise ValueError("Recipe evidence contains an invalid timestamp range")
                if not any(float(segment["start_seconds"]) - 0.1 <= start and float(segment["end_seconds"]) + 0.1 >= end for segment in segment_index[key]):
                    raise ValueError("Recipe evidence falls outside its analyzer segment")
                supporting_ids.add(file_id)
            if rule.get("supporting_reference_count") != len(supporting_ids):
                raise ValueError("Recipe supporting-reference count does not match its evidence")
            confidence = rule.get("confidence")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError("Recipe rule confidence must be between 0 and 1")

    @staticmethod
    def _validate_analysis(result: Dict[str, Any]) -> None:
        analysis = result.get("analysis")
        if not isinstance(analysis, dict) or not isinstance(analysis.get("segments"), list):
            raise ValueError("Analyzer returned an invalid analysis")
        duration = result.get("duration_seconds")
        previous = 0.0
        for segment in analysis["segments"]:
            start, end = segment.get("start_seconds"), segment.get("end_seconds")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start < 0 or end <= start:
                raise ValueError("Analyzer returned an invalid segment time range")
            if duration is not None and end > duration + 1.5:
                raise ValueError("Analyzer returned a segment outside the source duration")
            if start < previous:
                raise ValueError("Analyzer segments are not chronological")
            confidence = segment.get("confidence")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError("Analyzer returned confidence outside 0–1")
            previous = start


class ProjectAnalysisWorkflow:
    ROLES = ["hook", "setup", "main_point", "proof", "demonstration", "reaction", "b_roll", "transition", "ending", "other"]

    def __init__(self, store: JsonStore, analyzers: Dict[str, Any] = None,
                 retry_delays: Iterable[float] = (1, 3)):
        self.store = store
        self.analyzers = analyzers or {name: cls() for name, cls in PROVIDERS.items()}
        self.retry_delays = tuple(retry_delays)

    async def analyze(self, project_id: str, refresh: bool = False) -> Dict[str, Any]:
        project = self.store.update_project(project_id, status="analyzing_footage", last_error=None)
        provider_name = project["provider"]
        try:
            analyzer = self.analyzers[provider_name]
            if hasattr(analyzer, "readiness") and not analyzer.readiness().configured:
                raise RuntimeError("%s is not configured" % provider_name.title())
            existing = {item.get("file_id"): item for item in self.store.project_analyses(project_id, provider_name)}
            pending = []
            for raw_file in project["raw_files"]:
                result = existing.get(raw_file["file_id"])
                if result is None or refresh:
                    raw_file["analysis_status"] = "analyzing"
                    raw_file.pop("analysis_error", None)
                    pending.append(raw_file)
                else:
                    raw_file["analysis_status"] = "complete"
                    raw_file.pop("analysis_error", None)
            self.store.update_project(project_id, raw_files=project["raw_files"])

            # Keep a small concurrency limit: it shortens long multi-clip jobs while
            # avoiding a burst that can trigger provider throttling or local pressure.
            semaphore = asyncio.Semaphore(2)
            cache_locks = {}

            async def analyze_file(raw_file: Dict[str, Any]) -> None:
                async with semaphore:
                    checksum = raw_file["sha256"]
                    lock = cache_locks.setdefault(checksum, asyncio.Lock())
                    async with lock:
                        source = self.store.resolve_data_path(raw_file["stored_path"])
                        identity = analysis_cache_identity(
                            analyzer, "device:%s" % (project.get("device_id") or "legacy-local"),
                        )
                        result = None
                        if identity and not refresh:
                            result = self.store.cached_analysis(
                                provider_name, "raw_footage", checksum, identity, raw_file["file_id"],
                            )
                        if result is None:
                            result = await analyze_with_retry(
                                analyzer, source, raw_file["file_id"], "raw_footage", self.retry_delays,
                            )
                        result["duration_seconds"] = raw_file.get("metadata", {}).get("duration_seconds")
                        result["source_sha256"] = checksum
                        result["completed_at"] = utc_now()
                        self.store.record_remote_asset(
                            self.store.project_dir(project_id), provider_name,
                            raw_file["file_id"], result.get("remote_asset"),
                        )
                        StyleWorkflow._validate_analysis(result)
                        self.store.save_project_analysis(project_id, provider_name, raw_file["file_id"], result)
                        if identity and not (result.get("cache") or {}).get("hit"):
                            self.store.save_cached_analysis(
                                provider_name, "raw_footage", checksum, identity, result,
                            )

            outcomes = await asyncio.gather(*(analyze_file(item) for item in pending), return_exceptions=True)
            failures = [(item, outcome) for item, outcome in zip(pending, outcomes) if isinstance(outcome, Exception)]
            if failures:
                for raw_file, exc in failures:
                    raw_file["analysis_status"] = "failed"
                    raw_file["analysis_error"] = failure_fields(exc)["last_error"]
                self.store.update_project(project_id, raw_files=project["raw_files"])
                raise failures[0][1]
            for raw_file in pending:
                raw_file["analysis_status"] = "complete"
                raw_file.pop("analysis_error", None)
            self.store.update_project(project_id, raw_files=project["raw_files"])
            analyses = self.store.project_analyses(project_id, provider_name)
            content_map = self.build_content_map(project_id, provider_name, analyses, project.get("raw_files", []))
            self.store.write_json(self.store.project_dir(project_id) / "content_map.json", content_map)
            self.store.write_json(self.store.project_dir(project_id) / "content_maps" / (provider_name + ".json"), content_map)
            return self.store.update_project(project_id, status="footage_analyzed", raw_files=project["raw_files"], content_map=content_map, analysis_cost_summary=analysis_cost_summary(analyses))
        except Exception as exc:
            self.store.update_project(project_id, status="analysis_failed", **failure_fields(exc))
            raise

    @classmethod
    def build_content_map(cls, project_id: str, provider: str, analyses: List[Dict[str, Any]], raw_files: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        by_role = {role: [] for role in cls.ROLES}
        all_segments = []
        metadata = {item["file_id"]: item.get("metadata", {}) for item in (raw_files or [])}
        for file_analysis in analyses:
            file_id = file_analysis["file_id"]
            for segment in file_analysis["analysis"]["segments"]:
                candidate = {**segment, "source_file_id": file_id, "source_metadata": metadata.get(file_id, {}), "candidate_id": "%s:%s" % (file_id, segment["segment_id"])}
                all_segments.append(candidate)
                roles = segment.get("editorial_roles") or ["other"]
                matched = False
                for role in roles:
                    normalized = role.lower().strip().replace(" ", "_").replace("-", "_")
                    if normalized in by_role:
                        by_role[normalized].append(candidate)
                        matched = True
                if not matched:
                    by_role["other"].append(candidate)
        for candidates in by_role.values():
            candidates.sort(key=lambda item: (-item.get("confidence", 0), item["source_file_id"], item["start_seconds"]))
        return {
            "schema_version": "1.0", "project_id": project_id, "provider": provider,
            "created_at": utc_now(), "source_file_count": len(analyses),
            "segment_count": len(all_segments), "candidates_by_role": by_role,
            "all_segments": all_segments,
        }


class TimelinePreparationWorkflow:
    """Create the AI's editable first cut without rendering a combined video."""

    def __init__(self, store: JsonStore, decision_engine: Any = None, proxy_pipeline: Any = None):
        self.store = store
        self.decision_engine = decision_engine or OpenAIDecisionEngine()
        self.proxy_pipeline = proxy_pipeline or ProxyPipeline(store)
        self.timelines = TimelineStore(store)

    async def create(self, project_id: str, feedback: str = "") -> Dict[str, Any]:
        project = self.store.update_project(
            project_id, status="planning_timeline", last_error=None,
            active_task="Planning your editable first cut",
        )
        try:
            pinned_recipe = self.store.recipe_for_project(project)
            if not pinned_recipe:
                raise ValueError("The project has no approved recipe snapshot")
            content_map = project.get("content_map")
            if not content_map:
                raise ValueError("Analyze the raw footage before planning the timeline")
            all_signals = self.store.list_learning_signals(project["style_id"])
            allowed_signals = permission_scoped_signals(all_signals, project_id, project.get("device_id"))
            retrieved_examples = retrieve_approved_examples(
                self.store.list_approved_examples(), project.get("intent_interpretation") or {},
                project["style_id"], project.get("target_duration_seconds", 60),
                device_id=project.get("device_id"),
            )
            style_profile = self.store.style(project["style_id"])
            style = {
                **style_profile, "recipe": pinned_recipe, "style_analysis": pinned_recipe,
                "recipe_version": project.get("recipe_version"),
                "learning_state": consolidate_signals(allowed_signals),
                "learning_signals": relevant_signals(allowed_signals, project.get("prompt", ""), project_id),
                "approved_examples": retrieved_examples,
            }
            planning_project = dict(project)
            if feedback.strip():
                planning_project["prompt"] = "%s\n\nRevision feedback from the user:\n%s" % (project["prompt"], feedback.strip())
            plan = await self.decision_engine.plan_rough_cut(planning_project, style, content_map)
            plan.setdefault("decision_metadata", {})["retrieved_approved_example_ids"] = [item["example_id"] for item in retrieved_examples]
            plan = OpenAIDecisionEngine._repair_source_ids(plan, project)
            plan = OpenAIDecisionEngine._repair_source_ranges(plan, project)
            plan = OpenAIDecisionEngine._repair_timeline_continuity(plan)
            plan = OpenAIDecisionEngine._reconcile_target_duration(plan, float(project["target_duration_seconds"]))
            project = self.store.update_project(project_id, retrieved_approved_examples=[{
                key: item.get(key) for key in ("example_id", "recipe_version", "score", "matched_terms", "duration_delta_seconds")
            } for item in retrieved_examples])
            timeline = await self._validated_timeline_with_repair(project, plan, content_map)
            root = self.timelines.root(project_id)
            self.store.write_json(root / "initial_edit_plan.json", plan)
            self.store.write_json(root / "source_time_decisions.json", {
                "schema_version": "1.0", "decisions": source_time_decisions(plan),
            })
            if self.timelines.exists(project_id):
                if not feedback.strip():
                    raise ValueError("The first timeline already exists; provide revision feedback to replace it")
                timeline = self.timelines.replace_with_ai_revision(project_id, timeline, feedback.strip())
            else:
                timeline = self.timelines.initialize(project_id, timeline)
            self.store.update_project(
                project_id, status="preparing_proxies", active_task="Preparing fast previews for each source clip",
            )
            proxy_report = await asyncio.to_thread(self.proxy_pipeline.ensure_project, project)
            initial_path = self.timelines.root(project_id) / "snapshots" / "initial-ai.json"
            self.store.save_learning_signal(project["style_id"], {
                "source_key": "timeline-initial:%s:%s" % (project_id, timeline["timeline_hash"][:12]),
                "type": "timeline_initial", "scope": "project_outcome", "project_id": project_id,
                "device_id": project.get("device_id"), "recipe_version": project.get("recipe_version"),
                "timeline_hash": timeline["timeline_hash"], "status": "context",
                "instruction": "AI-created editable first timeline; compare with the latest successful approved export.",
            })
            return self.store.update_project(
                project_id, status="timeline_ready", active_task=None, active_revision=None,
                timeline_hash=timeline["timeline_hash"], timeline_revision=timeline["revision"],
                initial_timeline_path=str(initial_path.relative_to(self.store.data_dir)),
                proxy_report=proxy_report, pending_revision_feedback=None,
            )
        except Exception as exc:
            self.store.update_project(
                project_id, status="timeline_failed", active_revision=None, active_task=None, **failure_fields(exc),
            )
            raise

    async def _validated_timeline_with_repair(self, project: Dict[str, Any], plan: Dict[str, Any],
                                              content_map: Dict[str, Any]):
        """Validate first, then give the repair agent at most two bounded attempts."""
        persisted_plan = plan
        try:
            return timeline_from_edit_plan(project, plan)
        except (ValueError, KeyError) as first_error:
            if not hasattr(self.decision_engine, "repair_rough_cut"):
                raise
            original_metadata = dict(plan.get("decision_metadata") or {})
            original_selection = dict(plan.get("selection") or {})
            candidate_index = {
                item.get("candidate_id"): item for item in content_map.get("all_segments", [])
                if item.get("candidate_id")
            }
            selected = [
                candidate_index[item.get("candidate_id")]
                for item in original_selection.get("selected_candidates", [])
                if item.get("candidate_id") in candidate_index
            ]
            errors = [str(first_error)]
            for attempt in range(1, 3):
                repaired = await self.decision_engine.repair_rough_cut(
                    project, plan, selected, errors[-1],
                )
                repair_metadata = dict(repaired.pop("repair_metadata", {}) or {})
                plan = {
                    **repaired,
                    "schema_version": "1.0",
                    "project_id": project["project_id"],
                    "style_id": project["style_id"],
                    "recipe_version": project.get("recipe_version"),
                    "provider": project["provider"],
                    "selection": original_selection,
                    "decision_metadata": {
                        **original_metadata,
                        "repair_attempts": [
                            *(original_metadata.get("repair_attempts") or []),
                            {
                                "attempt": attempt,
                                "input_validation_error": errors[-1],
                                **repair_metadata,
                            },
                        ],
                    },
                }
                original_metadata = dict(plan["decision_metadata"])
                try:
                    timeline = timeline_from_edit_plan(project, plan)
                    # Mutate the caller-owned plan so persisted provenance is the
                    # exact plan that produced the accepted initial timeline.
                    persisted_plan.clear()
                    persisted_plan.update({**repaired,
                        "schema_version": "1.0", "project_id": project["project_id"],
                        "style_id": project["style_id"], "recipe_version": project.get("recipe_version"),
                        "provider": project["provider"], "selection": original_selection,
                        "decision_metadata": original_metadata,
                    })
                    return timeline
                except (ValueError, KeyError) as repair_error:
                    errors.append(str(repair_error))
            raise ValueError(
                "PB&J could not produce a valid initial timeline after two bounded repair attempts: %s"
                % errors[-1]
            )
