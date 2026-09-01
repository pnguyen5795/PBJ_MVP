from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict
import asyncio
import json

from ..agents import OpenAIAgentRuntime
from ..editorial_intelligence import retrieve_approved_examples
from ..learning import consolidate_signals, permission_scoped_signals, relevant_signals
from ..storage import JsonStore, new_id, utc_now
from .operations import SUPPORTED_OPERATION_TYPES
from .reducer import apply_transaction
from .storage import TimelineStore
from .diff import timeline_diff


PROPOSAL_PROMPT_VERSION = "timeline-proposal-v2"
PROPOSAL_REPAIR_PROMPT_VERSION = "timeline-proposal-repair-v1"
PROPOSAL_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "operations"],
    "properties": {
        "summary": {"type": "string"},
        "operations": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "payload_json", "reason"],
            "properties": {
                "type": {"type": "string", "enum": sorted(SUPPORTED_OPERATION_TYPES)},
                "payload_json": {"type": "string"},
                "reason": {"type": "string"},
            },
        }},
    },
}


class OpenAITimelineProposalEngine:
    def __init__(self, runtime: OpenAIAgentRuntime | None = None):
        self.runtime = runtime or OpenAIAgentRuntime()

    async def propose(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if not self.runtime.configured():
            raise RuntimeError("OPENAI_API_KEY is not configured")
        return await asyncio.to_thread(self._propose_sync, context)

    def _propose_sync(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = """Create one reversible typed transaction that revises the current PB&J timeline.
Use only the supplied assets. Never alter a clip whose asset has analyzed=false. Never invent media.
Do not include shell commands or rendering instructions. Use exact integer microseconds and frames.
The user's newest instruction is project-specific unless the governed learning context explicitly says otherwise.
Return payload_json as a valid JSON object for the selected operation type.

CONTEXT:
%s""" % json.dumps(context, ensure_ascii=False)
        result, metadata = self.runtime.run_structured(
            "editing", "timeline_proposal", PROPOSAL_SCHEMA, prompt,
        )
        result.update(metadata)
        return result

    async def repair(self, context: Dict[str, Any], failed_result: Dict[str, Any],
                     validation_error: str) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._repair_sync, context, failed_result, validation_error,
        )

    def _repair_sync(self, context: Dict[str, Any], failed_result: Dict[str, Any],
                     validation_error: str) -> Dict[str, Any]:
        prompt = """Repair this proposed PB&J timeline transaction after deterministic
validation rejected it. Preserve the user's revision intent and every valid
operation. Make the smallest necessary correction. Use only the current timeline,
supplied analyzed assets, and supported operation types. Never reanalyze or render
media. Return one complete replacement proposal for another validation pass.

VALIDATION ERROR:
%s

FAILED PROPOSAL:
%s

PROJECT CONTEXT:
%s""" % (
            validation_error,
            json.dumps(failed_result, ensure_ascii=False),
            json.dumps(context, ensure_ascii=False),
        )
        result, metadata = self.runtime.run_structured(
            "repair", "repaired_timeline_proposal", PROPOSAL_SCHEMA, prompt,
        )
        result.update(metadata)
        result["repair_prompt_version"] = PROPOSAL_REPAIR_PROMPT_VERSION
        result["input_validation_error"] = validation_error
        return result


class TimelineProposalService:
    def __init__(self, store: JsonStore, engine: Any = None):
        self.store = store
        self.timelines = TimelineStore(store)
        self.engine = engine or OpenAITimelineProposalEngine()

    def path(self, project_id: str, proposal_id: str) -> Path:
        if not proposal_id.startswith("proposal-"):
            raise FileNotFoundError(proposal_id)
        return self.timelines.root(project_id) / "proposals" / (proposal_id + ".json")

    def load(self, project_id: str, proposal_id: str) -> Dict[str, Any]:
        return self.store.read_json(self.path(project_id, proposal_id))

    async def create(self, project_id: str, instruction: str) -> Dict[str, Any]:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("Describe what you want changed")
        project = self.store.project(project_id)
        timeline = self.timelines.load(project_id)
        signals = permission_scoped_signals(
            self.store.list_learning_signals(project["style_id"]), project_id, project.get("device_id"),
        )
        examples = retrieve_approved_examples(
            self.store.list_approved_examples(), project.get("intent_interpretation") or {},
            project["style_id"], project.get("target_duration_seconds", 60), device_id=project.get("device_id"),
        )
        analyses = self.store.project_analyses(project_id, project.get("provider"))
        history = project.get("timeline_revision_history", [])
        applied_prompts = [item.get("instruction") for item in history
                           if item.get("status") == "applied" and item.get("instruction")]
        if not history:
            applied_prompts = project.get("timeline_revision_prompts", [])
        context = {
            "current_timeline": timeline,
            "project_prompt": project.get("prompt"),
            "revision_instruction": instruction,
            "previous_applied_revision_prompts": applied_prompts,
            "recipe": self.store.recipe_for_project(project),
            "learning_state": consolidate_signals(signals),
            "relevant_learning_signals": relevant_signals(signals, instruction, project_id),
            "approved_examples": examples,
            "footage_analysis": analyses,
            "unanalyzed_asset_ids": [item["asset_id"] for item in timeline["assets"] if not item.get("analyzed")],
            "supported_operations": sorted(SUPPORTED_OPERATION_TYPES),
        }
        result = await self.engine.propose(context)
        repair_attempts = []
        for attempt in range(3):
            try:
                operations = []
                for index, item in enumerate(result.get("operations") or []):
                    payload = json.loads(item.get("payload_json") or "{}")
                    operations.append({
                        "operation_id": "ai-op-%03d" % (index + 1), "type": item["type"],
                        "payload": payload, "reason": item.get("reason") or instruction,
                    })
                transaction = {
                    "transaction_id": new_id("transaction"), "base_revision": timeline["revision"],
                    "base_timeline_hash": timeline["timeline_hash"], "origin": "ai_proposal",
                    "reason": instruction, "operations": operations,
                    "recipe_version": project.get("recipe_version"),
                    "evidence_provenance": {
                        "analysis_file_ids": [item.get("file_id") for item in analyses],
                        "learning_signal_ids": [item.get("signal_id") for item in context["relevant_learning_signals"]],
                        "approved_example_ids": [item.get("example_id") for item in examples],
                    },
                }
                self._protect_unanalyzed_assets(timeline, operations)
                proposed, _ = apply_transaction(timeline, transaction)
                break
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                if attempt >= 2 or not hasattr(self.engine, "repair"):
                    raise
                result = await self.engine.repair(context, result, str(exc))
                repair_attempts.append({
                    "attempt": attempt + 1, "validation_error": str(exc),
                    "agent_role_version": result.get("agent_role_version"),
                    "model": result.get("model"), "reasoning_effort": result.get("reasoning_effort"),
                    "response_id": result.get("response_id"),
                    "prompt_version": result.get("repair_prompt_version"),
                })
        proposal_id = new_id("proposal")
        record = {
            "schema_version": "1.0", "proposal_id": proposal_id, "project_id": project_id,
            "status": "pending", "created_at": utc_now(), "summary": result.get("summary") or instruction,
            "instruction": instruction, "base_timeline_hash": timeline["timeline_hash"],
            "proposed_timeline_hash": proposed["timeline_hash"], "transaction": transaction,
            "diff": timeline_diff(timeline, proposed),
            "prompt_version": PROPOSAL_PROMPT_VERSION, "decision_model": result.get("model"),
            "agent": {key: result.get(key) for key in (
                "agent_key", "agent_name", "agent_role_version", "model", "reasoning_effort"
            )},
            "repair_attempts": repair_attempts,
            "response_id": result.get("response_id"), "usage": result.get("usage", {}),
        }
        self.store.write_json(self.path(project_id, proposal_id), record)
        self.store.save_learning_signal(project["style_id"], {
            "source_key": "timeline-proposal:%s:%s" % (project_id, proposal_id),
            "type": "timeline_revision", "scope": "project_only", "project_id": project_id,
            "device_id": project.get("device_id"), "instruction": instruction,
            "proposal_id": proposal_id, "status": "pending",
        })
        return record

    def apply(self, project_id: str, proposal_id: str) -> Dict[str, Any]:
        record = self.load(project_id, proposal_id)
        if record.get("status") != "pending":
            raise ValueError("This proposal is no longer pending")
        result = self.timelines.transact(project_id, record["transaction"])
        record.update(status="applied", applied_at=utc_now(), applied_timeline_hash=result["timeline"]["timeline_hash"])
        self.store.write_json(self.path(project_id, proposal_id), record)
        self._record_history(project_id, record, "applied")
        self._save_outcome_signal(project_id, record, "applied")
        return {"timeline": result["timeline"], "proposal": record}

    def reject(self, project_id: str, proposal_id: str) -> Dict[str, Any]:
        record = self.load(project_id, proposal_id)
        if record.get("status") != "pending":
            raise ValueError("This proposal is no longer pending")
        record.update(status="rejected", rejected_at=utc_now())
        self.store.write_json(self.path(project_id, proposal_id), record)
        self._record_history(project_id, record, "rejected")
        self._save_outcome_signal(project_id, record, "rejected")
        return {"proposal": record}

    def _record_history(self, project_id: str, record: Dict[str, Any], status: str) -> None:
        """Keep attempted feedback separate from instructions the user accepted.

        Rejected proposals remain evidence, but are never silently fed back as
        positive instructions for the next AI revision.
        """
        project = self.store.project(project_id)
        history = list(project.get("timeline_revision_history", []))
        history.append({
            "proposal_id": record["proposal_id"], "instruction": record.get("instruction"),
            "status": status, "transaction_id": (record.get("transaction") or {}).get("transaction_id"),
            "recorded_at": record.get("applied_at") or record.get("rejected_at") or utc_now(),
        })
        changes: Dict[str, Any] = {"timeline_revision_history": history}
        if status == "applied":
            prompts = list(project.get("timeline_revision_prompts", []))
            if record.get("instruction") and record["instruction"] not in prompts:
                prompts.append(record["instruction"])
            changes["timeline_revision_prompts"] = prompts
        self.store.update_project(project_id, **changes)

    def _save_outcome_signal(self, project_id: str, record: Dict[str, Any], status: str) -> None:
        project = self.store.project(project_id)
        self.store.save_learning_signal(project["style_id"], {
            "source_key": "timeline-proposal-outcome:%s:%s" % (project_id, record["proposal_id"]),
            "type": "timeline_proposal_%s" % status, "scope": "project_only",
            "project_id": project_id, "device_id": project.get("device_id"),
            "proposal_id": record["proposal_id"], "instruction": record.get("instruction"),
            "timeline_hash": record.get("applied_timeline_hash"), "status": "context",
        })

    @staticmethod
    def _protect_unanalyzed_assets(timeline: Dict[str, Any], operations) -> None:
        asset_map = {item["asset_id"]: item for item in timeline["assets"]}
        clip_map = {clip["clip_id"]: clip for track in timeline["tracks"] for clip in track["clips"]}
        for operation in operations:
            payload = operation.get("payload") or {}
            clip = clip_map.get(payload.get("clip_id")) or payload.get("clip")
            if clip and not asset_map.get(clip.get("asset_id"), {}).get("analyzed"):
                raise ValueError("AI proposals cannot alter unanalyzed footage")
