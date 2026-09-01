"""Governed Learning Agent assessments.

The assessment is advisory evidence. It cannot mutate or promote recipes.
"""

from __future__ import annotations

from typing import Any, Dict
import json

from .agents import OpenAIAgentRuntime
from .learning import CATEGORIES, consolidate_signals, permission_scoped_signals
from .storage import JsonStore, utc_now


LEARNING_ASSESSMENT_PROMPT_VERSION = "learning-assessment-v1"
LEARNING_ASSESSMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "evidence_classifications", "recipe_candidates", "user_preference_candidates"],
    "properties": {
        "summary": {"type": "string"},
        "evidence_classifications": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["evidence_id", "category", "scope", "polarity", "observation", "rationale", "confidence"],
            "properties": {
                "evidence_id": {"type": "string"},
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "scope": {"type": "string", "enum": ["project_only", "user_preference_candidate", "recipe_candidate", "platform_candidate"]},
                "polarity": {"type": "string", "enum": ["positive", "negative", "mixed", "context"]},
                "observation": {"type": "string"}, "rationale": {"type": "string"},
                "confidence": {"type": "number"},
            },
        }},
        "recipe_candidates": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "suggestion", "supporting_evidence_ids", "contradictory_evidence_ids", "confidence", "recommended_status"],
            "properties": {
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "suggestion": {"type": "string"},
                "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "contradictory_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
                "recommended_status": {"type": "string", "enum": ["project_only", "emerging", "candidate"]},
            },
        }},
        "user_preference_candidates": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["category", "preference", "supporting_evidence_ids", "confidence"],
            "properties": {
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "preference": {"type": "string"},
                "supporting_evidence_ids": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "number"},
            },
        }},
    },
}


class LearningAssessmentService:
    def __init__(self, store: JsonStore, runtime: OpenAIAgentRuntime | None = None):
        self.store = store
        self.runtime = runtime or OpenAIAgentRuntime()

    def assess_approval(self, project: Dict[str, Any], export: Dict[str, Any],
                        metrics: Dict[str, Any], proposals: list[Dict[str, Any]]) -> Dict[str, Any]:
        path = (self.store.project_dir(project["project_id"]) / "timeline" / "learning" /
                ("export-%s-assessment.json" % export["export_id"]))
        base = {
            "schema_version": "1.0", "recorded_at": utc_now(),
            "project_id": project["project_id"], "export_id": export["export_id"],
            "recipe_id": project["style_id"], "recipe_version": project.get("recipe_version"),
            "prompt_version": LEARNING_ASSESSMENT_PROMPT_VERSION,
            "governance": {
                "advisory_only": True, "applied_to_recipe": False,
                "promotion_requires_cross_project_thresholds": True,
                "permission_scope": "device_private",
            },
        }
        if not self.runtime.configured():
            record = {**base, "status": "skipped", "reason": "OPENAI_API_KEY is not configured"}
            self.store.write_json(path, record)
            return {**record, "path": str(path.relative_to(self.store.data_dir))}

        signals = permission_scoped_signals(
            self.store.list_learning_signals(project["style_id"]),
            project["project_id"], project.get("device_id"),
        )
        evidence = {
            "project_prompt": project.get("prompt"),
            "recipe_version": project.get("recipe_version"),
            "recipe": self.store.recipe_for_project(project),
            "outcome_metrics": metrics,
            "revision_proposals": [{
                "evidence_id": item.get("proposal_id"),
                "instruction": item.get("instruction"), "status": item.get("status"),
                "diff": item.get("diff"),
            } for item in proposals],
            "deterministic_learning_state": consolidate_signals(signals),
            "positive_evidence_boundary": "The successfully exported and explicitly approved outcome is positive project evidence; intermediate actions remain context.",
        }
        prompt = """Classify what this approved project may teach PB&J. Cite only the supplied
evidence IDs. Separate project-specific corrections, possible user preferences,
recipe candidates, and platform candidates. A revision request is not proof that
the requested change was good unless it survived into the approved outcome. A
rejected proposal is negative/context evidence. Do not recommend promotion from
one project. Preserve contradictions and uncertainty.

APPROVAL EVIDENCE:
%s""" % json.dumps(evidence, ensure_ascii=False)
        try:
            result, metadata = self.runtime.run_structured(
                "learning", "approval_learning_assessment", LEARNING_ASSESSMENT_SCHEMA, prompt,
            )
            record = {**base, "status": "complete", "assessment": result, "agent": metadata}
        except Exception as exc:
            # Export approval and deterministic evidence remain valid even when
            # the advisory model assessment is temporarily unavailable.
            record = {**base, "status": "failed", "error": str(exc)}
        self.store.write_json(path, record)
        return {**record, "path": str(path.relative_to(self.store.data_dir))}
