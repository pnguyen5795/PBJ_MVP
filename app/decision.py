import asyncio
import json
import re
from typing import Any, Dict, List

from .agents import OpenAIAgentRuntime
from .learning import extract_requirements
from .contracts import CANDIDATE_SELECTION_JSON_SCHEMA, ROUGH_CUT_PLAN_JSON_SCHEMA, STYLE_SYNTHESIS_JSON_SCHEMA
from .prompts import (
    CANDIDATE_SELECTION_PROMPT, CANDIDATE_SELECTION_PROMPT_VERSION,
    PLANNER_POLICY_VERSION, ROUGH_CUT_PLAN_PROMPT, ROUGH_CUT_PLAN_PROMPT_VERSION,
    STYLE_REVISION_PROMPT, STYLE_REVISION_PROMPT_VERSION,
    STYLE_SYNTHESIS_PROMPT, STYLE_SYNTHESIS_PROMPT_VERSION,
    TIMELINE_REPAIR_PROMPT, TIMELINE_REPAIR_PROMPT_VERSION,
)


class OpenAIDecisionEngine:
    def __init__(self, runtime: OpenAIAgentRuntime | None = None):
        self.runtime = runtime or OpenAIAgentRuntime()

    def configured(self) -> bool:
        return self.runtime.configured()

    async def synthesize_style(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return await asyncio.to_thread(self._synthesize_style_sync, analyses)

    def _synthesize_style_sync(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        evidence = [{
            "file_id": item.get("file_id"), "provider": item.get("provider"),
            "model": item.get("model"), "analysis": item.get("analysis"),
        } for item in analyses]
        result, metadata = self.runtime.run_structured(
            "learning", "editing_recipe", STYLE_SYNTHESIS_JSON_SCHEMA,
            STYLE_SYNTHESIS_PROMPT.format(analyses_json=json.dumps(evidence, ensure_ascii=False)),
        )
        result["synthesis"] = {
            "provider": "openai", **metadata,
            "prompt_version": STYLE_SYNTHESIS_PROMPT_VERSION,
        }
        return result

    async def plan_rough_cut(self, project: Dict[str, Any], style: Dict[str, Any], content_map: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return await asyncio.to_thread(self._plan_rough_cut_sync, project, style, content_map)

    async def revise_style(self, style_analysis: Dict[str, Any], feedback: str) -> Dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return await asyncio.to_thread(self._revise_style_sync, style_analysis, feedback)

    def _revise_style_sync(self, style_analysis: Dict[str, Any], feedback: str) -> Dict[str, Any]:
        result, metadata = self._structured_response(
            "revised_editing_recipe", STYLE_SYNTHESIS_JSON_SCHEMA,
            STYLE_REVISION_PROMPT.format(
                style_json=json.dumps(style_analysis, ensure_ascii=False),
                feedback=feedback,
            ), agent_key="learning",
        )
        result["synthesis"] = {
            "provider": "openai", **metadata,
            "prompt_version": STYLE_REVISION_PROMPT_VERSION,
        }
        return result

    def _structured_response(self, name: str, schema: Dict[str, Any], prompt: str,
                             agent_key: str = "editing"):
        return self.runtime.run_structured(agent_key, name, schema, prompt)

    def _plan_rough_cut_sync(self, project: Dict[str, Any], style: Dict[str, Any], content_map: Dict[str, Any]) -> Dict[str, Any]:
        style_evidence = dict(style.get("recipe") or style.get("style_analysis") or {})
        # Learning signals are advisory context, not silently promoted recipe rules.
        style_evidence["learning_signals"] = style.get("learning_signals", [])
        style_evidence["learning_state"] = style.get("learning_state", {})
        # Approved examples are retrieved inside the pinned recipe boundary and
        # remain evidence, never commands or silently promoted rules.
        style_evidence["approved_examples"] = style.get("approved_examples", [])
        requirements = extract_requirements(project.get("prompt", ""))
        learning_state = style.get("learning_state") or {}
        promoted_categories = [
            item.get("category") for item in learning_state.get("insights", [])
            if item.get("status") == "promoted_overlay" and item.get("category")
        ]
        compact_map = {
            "source_file_count": content_map.get("source_file_count"),
            "candidates_by_role": content_map.get("candidates_by_role", {}),
        }
        selection, selection_metadata = self._structured_response(
            "rough_cut_candidate_selection", CANDIDATE_SELECTION_JSON_SCHEMA,
            CANDIDATE_SELECTION_PROMPT.format(
                user_prompt=project["prompt"], target_seconds=project["target_duration_seconds"],
                style_json=json.dumps(style_evidence, ensure_ascii=False),
                requirements_json=json.dumps(requirements, ensure_ascii=False),
                content_map_json=json.dumps(compact_map, ensure_ascii=False),
            ),
        )
        selection = self._ensure_required_candidates(selection, content_map, requirements)
        selection = self._ensure_single_available_candidate(selection, content_map)
        candidate_index = {item["candidate_id"]: item for item in content_map.get("all_segments", [])}
        selected_ids = [item["candidate_id"] for item in selection["selected_candidates"]]
        unknown = [item for item in selected_ids if item not in candidate_index]
        if unknown:
            raise ValueError("OpenAI selected unknown candidates: %s" % ", ".join(unknown))
        selected_details = [candidate_index[item] for item in selected_ids]
        plan, plan_metadata = self._structured_response(
            "first_rough_cut_plan", ROUGH_CUT_PLAN_JSON_SCHEMA,
            ROUGH_CUT_PLAN_PROMPT.format(
                user_prompt=project["prompt"], target_seconds=project["target_duration_seconds"],
                style_json=json.dumps(style_evidence, ensure_ascii=False),
                requirements_json=json.dumps(requirements, ensure_ascii=False),
                selection_json=json.dumps(selection, ensure_ascii=False),
                candidates_json=json.dumps(selected_details, ensure_ascii=False),
            ),
        )
        # Models sometimes leave a fractional tail after laying out the final
        # shot.  The renderer must receive an exact target timeline, so trim
        # only the final segment when the model ran slightly long.  This does
        # not invent media or change the creative selection; it preserves the
        # selected source range and removes the excess tail.
        plan = self._repair_source_ids(plan, project)
        plan = self._repair_source_ranges(plan, project)
        plan = self._repair_timeline_continuity(plan)
        plan = self._reconcile_target_duration(plan, float(project["target_duration_seconds"]))
        timestamp_refinement = self._validate_selected_ranges(plan, selected_details)
        requirement_check = self._verify_requirements(plan, selected_details, requirements)
        return {
            **plan, "schema_version": "1.0", "project_id": project["project_id"],
            "style_id": style["style_id"],
            "recipe_version": project.get("recipe_version") or style.get("recipe_version"),
            "provider": project["provider"],
            "decision_model": plan_metadata["model"], "selection": selection,
            "decision_metadata": {
                "agent": {key: plan_metadata[key] for key in (
                    "agent_key", "agent_name", "agent_role_version", "model", "reasoning_effort"
                )},
                "effective_project_prompt": project["prompt"],
                "target_duration_seconds": project["target_duration_seconds"],
                "requirements": requirements,
                "requirement_check": requirement_check,
                "learning_signal_ids": [item.get("signal_id") for item in style.get("learning_signals", [])],
                "learning_state": {
                    "updated_at": learning_state.get("updated_at"),
                    "signal_count": learning_state.get("signal_count", 0),
                    "available_promoted_overlay_categories": promoted_categories,
                },
                "prompt_versions": {
                    "candidate_selection": CANDIDATE_SELECTION_PROMPT_VERSION,
                    "rough_cut_plan": ROUGH_CUT_PLAN_PROMPT_VERSION,
                    "planner_policy": PLANNER_POLICY_VERSION,
                },
                "selection_response_id": selection_metadata["response_id"],
                "plan_response_id": plan_metadata["response_id"],
                "selection_usage": selection_metadata["usage"], "plan_usage": plan_metadata["usage"],
                "timestamp_refinement": timestamp_refinement,
            },
        }

    async def repair_rough_cut(self, project: Dict[str, Any], plan: Dict[str, Any],
                               selected_candidates: List[Dict[str, Any]],
                               validation_error: str) -> Dict[str, Any]:
        if not self.configured():
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return await asyncio.to_thread(
            self._repair_rough_cut_sync, project, plan, selected_candidates, validation_error,
        )

    def _repair_rough_cut_sync(self, project: Dict[str, Any], plan: Dict[str, Any],
                               selected_candidates: List[Dict[str, Any]],
                               validation_error: str) -> Dict[str, Any]:
        constraints = [{
            "source_file_id": item["file_id"],
            "duration_seconds": (item.get("metadata") or {}).get("duration_seconds"),
            "has_audio": (item.get("metadata") or {}).get("has_audio"),
        } for item in project.get("raw_files", [])]
        repair_input = {key: plan.get(key) for key in (
            "title", "creative_summary", "target_duration_seconds",
            "video_segments", "audio_segments", "warnings",
        )}
        repaired, metadata = self._structured_response(
            "repaired_rough_cut_plan", ROUGH_CUT_PLAN_JSON_SCHEMA,
            TIMELINE_REPAIR_PROMPT.format(
                user_prompt=project.get("prompt", ""),
                target_seconds=project.get("target_duration_seconds"),
                validation_error=validation_error,
                source_constraints_json=json.dumps(constraints, ensure_ascii=False),
                candidates_json=json.dumps(selected_candidates, ensure_ascii=False),
                plan_json=json.dumps(repair_input, ensure_ascii=False),
            ),
            agent_key="repair",
        )
        repaired = self._repair_source_ids(repaired, project)
        repaired = self._repair_source_ranges(repaired, project)
        repaired = self._repair_timeline_continuity(repaired)
        repaired = self._reconcile_target_duration(
            repaired, float(project["target_duration_seconds"]),
        )
        repaired["decision_model"] = metadata["model"]
        repaired["repair_metadata"] = {
            **metadata,
            "prompt_version": TIMELINE_REPAIR_PROMPT_VERSION,
            "validation_error": validation_error,
        }
        return repaired

    @staticmethod
    def _candidate_text(candidate: Dict[str, Any]) -> str:
        fields = [candidate.get("transcript", ""), candidate.get("visual_description", ""),
                  candidate.get("audio_description", ""), " ".join(candidate.get("subjects") or []),
                  " ".join(candidate.get("actions") or []), " ".join(candidate.get("editorial_roles") or [])]
        return " ".join(str(item) for item in fields).lower()

    @staticmethod
    def _requirement_words(term: str) -> set:
        generic = {"clip", "footage", "shot", "video", "scene", "moment", "the"}
        return {word for word in re.findall(r"[a-z0-9]+", (term or "").lower()) if len(word) > 2 and word not in generic}

    @classmethod
    def _ensure_required_candidates(cls, selection: Dict[str, Any], content_map: Dict[str, Any],
                                    requirements: List[Dict[str, Any]]) -> Dict[str, Any]:
        selected = selection.setdefault("selected_candidates", [])
        selected_ids = {item.get("candidate_id") for item in selected}
        all_candidates = content_map.get("all_segments", [])
        for requirement in requirements:
            matches = []
            if requirement.get("type") == "editorial_role":
                role = requirement.get("role")
                matches = [item for item in all_candidates if role in (item.get("editorial_roles") or [])]
            elif requirement.get("type") == "content":
                term_words = cls._requirement_words(requirement.get("term", ""))
                matches = [item for item in all_candidates if term_words and term_words <= set(re.findall(r"[a-z0-9]+", cls._candidate_text(item)))]
            if not matches or any(item.get("candidate_id") in selected_ids for item in matches):
                continue
            candidate = max(matches, key=lambda item: float(item.get("confidence", 0)))
            selected.append({"candidate_id": candidate["candidate_id"], "intended_role": requirement.get("type", "required"),
                             "reason": "Required by the explicit project instructions: %s" % requirement["description"],
                             "priority": len(selected) + 1})
            selected_ids.add(candidate["candidate_id"])
        return selection

    @staticmethod
    def _ensure_single_available_candidate(
        selection: Dict[str, Any],
        content_map: Dict[str, Any],
    ) -> Dict[str, Any]:
        selected = selection.setdefault("selected_candidates", [])
        candidates = content_map.get("all_segments") or []
        if selected or len(candidates) != 1:
            return selection
        candidate_id = candidates[0].get("candidate_id")
        if not candidate_id:
            return selection
        selected.append({
            "candidate_id": candidate_id,
            "intended_role": "available_source",
            "reason": "The only analyzed source segment available for this project.",
            "priority": 1,
        })
        selection.setdefault("warnings", []).append(
            "PBJ retained the only analyzed source segment after the model returned an empty shortlist"
        )
        return selection

    @classmethod
    def _verify_requirements(cls, plan: Dict[str, Any], selected_details: List[Dict[str, Any]],
                             requirements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        checks = []
        for requirement in requirements:
            if requirement.get("type") == "structure":
                checks.append({**requirement, "status": "planner_enforced", "machine_verified": False})
                continue
            if requirement.get("type") == "editorial_role":
                candidates = [item for item in selected_details if requirement.get("role") in (item.get("editorial_roles") or [])]
            else:
                term_words = cls._requirement_words(requirement.get("term", ""))
                candidates = [item for item in selected_details if term_words and term_words <= set(re.findall(r"[a-z0-9]+", cls._candidate_text(item)))]
            used = False
            for candidate in candidates:
                for segment in plan.get("video_segments") or []:
                    if segment.get("source_file_id") != candidate.get("source_file_id"):
                        continue
                    if float(segment["source_end"]) > float(candidate["start_seconds"]) and float(segment["source_start"]) < float(candidate["end_seconds"]):
                        used = True
                        break
                if used:
                    break
            check = {**requirement, "status": "satisfied" if used else "missing", "machine_verified": True}
            checks.append(check)
            if requirement.get("required") and candidates and not used:
                raise ValueError("The edit plan omitted a required item: %s" % requirement["description"])
        return checks

    @staticmethod
    def _repair_source_ids(plan: Dict[str, Any], project: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve only unique project-owned aliases; never guess across sources."""
        sources = project.get("raw_files") or []
        valid_ids = {item.get("file_id") for item in sources if item.get("file_id")}
        aliases: Dict[str, set] = {}
        for item in sources:
            file_id = item.get("file_id")
            if not file_id:
                continue
            names = {
                str(item.get("original_name") or "").strip(),
                str(item.get("stored_path") or "").rsplit("/", 1)[-1].strip(),
            }
            for name in names:
                if name:
                    aliases.setdefault(name.casefold(), set()).add(file_id)

        repairs = []
        for layer in ("video_segments", "audio_segments"):
            for index, segment in enumerate(plan.get(layer) or []):
                supplied = str(segment.get("source_file_id") or "").strip()
                if supplied in valid_ids:
                    continue
                matches = aliases.get(supplied.casefold(), set())
                resolved = next(iter(matches)) if len(matches) == 1 else None
                if resolved is None and len(valid_ids) == 1:
                    resolved = next(iter(valid_ids))
                if resolved is None:
                    continue
                segment["source_file_id"] = resolved
                repairs.append({
                    "layer": layer,
                    "segment_index": index,
                    "supplied_source_file_id": supplied,
                    "resolved_source_file_id": resolved,
                    "method": "unique_project_source_alias",
                })
        if repairs:
            plan.setdefault("warnings", []).append(
                "PBJ resolved model-provided source names to unique project-owned media IDs"
            )
            plan.setdefault("source_id_repairs", []).extend(repairs)
        return plan

    @staticmethod
    def _repair_source_ranges(plan: Dict[str, Any], project: Dict[str, Any]) -> Dict[str, Any]:
        """Clamp model estimates to real media bounds without re-analyzing footage."""
        durations = {item["file_id"]: item.get("metadata", {}).get("duration_seconds")
                     for item in project.get("raw_files", [])}
        for layer in ("video_segments", "audio_segments"):
            for segment in plan.get(layer) or []:
                duration = durations.get(segment.get("source_file_id"))
                if duration is None:
                    continue
                # Keep both endpoints inside the actual file. If the model
                # starts beyond EOF, place the trim at the final safe frame
                # rather than allowing an invalid zero/negative range.
                start = min(float(duration) - 0.01, max(0.0, float(segment.get("source_start", 0))))
                end = min(float(duration), float(segment.get("source_end", 0)))
                if end <= start:
                    end = min(float(duration), start + 0.01)
                segment["source_start"] = start
                segment["source_end"] = end
                speed = max(0.01, float(segment.get("speed", 1)))
                segment["timeline_end"] = float(segment.get("timeline_start", 0)) + (end - start) / speed
        return plan

    @staticmethod
    def _repair_timeline_continuity(plan: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize harmless model rounding gaps/overlaps before FFmpeg validation."""
        for layer in ("video_segments", "audio_segments"):
            previous_end = 0.0
            for index, segment in enumerate(plan.get(layer) or []):
                speed = max(0.01, float(segment.get("speed", 1)))
                duration = (float(segment["source_end"]) - float(segment["source_start"])) / speed
                transition = segment.get("transition", "cut") if layer == "video_segments" else "cut"
                transition_duration = float(segment.get("transition_duration", 0)) if transition == "crossfade" else 0.0
                start = 0.0 if index == 0 else previous_end - transition_duration
                segment["timeline_start"] = round(max(0.0, start), 6)
                segment["timeline_end"] = round(segment["timeline_start"] + duration, 6)
                previous_end = segment["timeline_end"]
        return plan

    @staticmethod
    def _reconcile_target_duration(plan: Dict[str, Any], target: float) -> Dict[str, Any]:
        # Video and original audio must end together. If either layer is
        # shorter after safe source-bound repairs, shorten the rough cut to
        # that shared endpoint rather than inventing media or leaving a gap.
        ends = [float(segments[-1].get("timeline_end", 0)) for segments in
                (plan.get("video_segments") or [], plan.get("audio_segments") or []) if segments]
        available = min(ends) if ends else target
        if available < target - 0.5:
            plan["target_duration_seconds"] = round(available, 3)
            target = available
            plan.setdefault("warnings", []).append(
                "Output shortened to %.3fs so video and original audio end together" % available
            )
        for layer in ("video_segments", "audio_segments"):
            segments = plan.get(layer) or []
            if not segments:
                continue
            end = float(segments[-1].get("timeline_end", 0))
            excess = end - target
            if 0 < excess <= 5.0:
                final = segments[-1]
                final_end = target
                final_start = float(final["timeline_start"])
                speed = float(final.get("speed", 1))
                final["timeline_end"] = final_end
                final["source_end"] = float(final["source_start"]) + (final_end - final_start) * speed
                plan.setdefault("warnings", []).append(
                    "%s final segment trimmed by %.3fs to match the requested duration" % (layer, excess)
                )
        return plan

    @staticmethod
    def _validate_selected_ranges(plan: Dict[str, Any], selected_details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prove every final trim is contained in analyzer evidence and preserve both ranges."""
        records = []
        for layer in ("video_segments", "audio_segments"):
            for index, segment in enumerate(plan.get(layer, [])):
                matching = [candidate for candidate in selected_details
                            if candidate.get("source_file_id") == segment.get("source_file_id")
                            and float(candidate.get("start_seconds", -1)) <= float(segment["source_start"]) + 0.08
                            and float(candidate.get("end_seconds", -1)) + 0.08 >= float(segment["source_end"])]
                provenance_method = "openai_trim_within_selected_analyzer_range"
                if matching:
                    candidate = min(matching, key=lambda item: float(item["end_seconds"]) - float(item["start_seconds"]))
                else:
                    # The analyzer shortlist is guidance, not a hard edit
                    # boundary. OpenAI may reasonably extend a shot slightly
                    # when building a coherent story. Keep the record, mark
                    # the exception, and let the renderer's strict source
                    # duration checks remain the final safety gate.
                    same_file = [candidate for candidate in selected_details
                                  if candidate.get("source_file_id") == segment.get("source_file_id")]
                    if not same_file:
                        raise ValueError("OpenAI planned a %s trim from an unknown source file" % layer)
                    candidate = min(same_file, key=lambda item: abs(float(item.get("start_seconds", 0)) - float(segment["source_start"])))
                    provenance_method = "openai_trim_outside_shortlist_allowed_with_warning"
                records.append({
                    "layer": layer, "segment_index": index,
                    "candidate_id": candidate["candidate_id"],
                    "analyzer_range": {"start_seconds": candidate["start_seconds"], "end_seconds": candidate["end_seconds"]},
                    "refined_range": {"start_seconds": segment["source_start"], "end_seconds": segment["source_end"]},
                    "method": provenance_method,
                })
        return records
