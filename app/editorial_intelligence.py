"""Auditable, deterministic editorial intelligence around the Recipe Engine.

These helpers never render media and never promote shared recipe rules. They
interpret a brief, rank already-approved internal recipes/examples, classify
feedback conservatively, and measure what survived from first cut to approval.
"""

from typing import Any, Dict, Iterable, List
import re

from .learning import extract_requirements


STOP_WORDS = {
    "about", "after", "again", "also", "and", "before", "from", "have",
    "into", "make", "should", "that", "the", "this", "video", "with", "your",
}


def words(value: str) -> set[str]:
    return {
        item for item in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(item) > 2 and item not in STOP_WORDS
    }


def interpret_brief(prompt: str, target_seconds: int) -> Dict[str, Any]:
    text = (prompt or "").strip()
    lowered = text.lower()
    pacing = "fast" if any(term in lowered for term in ("fast", "quick", "energetic", "punchy")) else (
        "slow" if any(term in lowered for term in ("slow", "calm", "reflective", "cinematic")) else "unspecified"
    )
    structure = []
    for label, terms in {
        "strong_opening": ("hook", "strongest moment", "open with"),
        "chronological": ("chronological", "in order", "start to finish"),
        "reaction_driven": ("reaction", "reactions"),
        "dialogue_led": ("dialogue", "interview", "talking"),
    }.items():
        if any(term in lowered for term in terms):
            structure.append(label)
    return {
        "schema_version": "1.0",
        "source": "project_brief",
        "brief": text,
        "target_duration_seconds": target_seconds,
        "pacing": pacing,
        "structure_preferences": structure,
        "requirements": extract_requirements(text),
        "query_terms": sorted(words(text)),
    }


def _recipe_text(style: Dict[str, Any]) -> str:
    recipe = style.get("recipe") or style.get("style_analysis") or {}
    values: List[str] = [style.get("label", ""), recipe.get("summary", ""), recipe.get("structure_summary", "")]
    for key in ("creative_principles", "compatibility", "avoid"):
        values.extend(str(item) for item in recipe.get(key) or [])
    for rule in recipe.get("rules") or []:
        values.extend(str(rule.get(key) or "") for key in ("category", "instruction", "observation"))
    return " ".join(values)


def match_recipe(intent: Dict[str, Any], styles: Iterable[Dict[str, Any]], override_style_id: str = "") -> Dict[str, Any]:
    approved = [item for item in styles if item.get("approval", {}).get("approved")]
    if not approved:
        raise ValueError("PB&J has no approved internal recipe available")
    query = set(intent.get("query_terms") or [])
    ranked = []
    for style in approved:
        overlap = sorted(query & words(_recipe_text(style)))
        score = len(overlap) * 4
        reasons = []
        if overlap:
            reasons.append("brief terms matched recipe evidence: %s" % ", ".join(overlap[:8]))
        if style.get("system_default"):
            score += 1
            reasons.append("approved general fallback")
        if override_style_id and style.get("style_id") == override_style_id:
            score += 1000
            reasons.append("internal recipe override")
        ranked.append((score, style.get("updated_at", ""), style, reasons))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = ranked[0]
    return {
        "schema_version": "1.0",
        "method": "deterministic_recipe_rank_v1",
        "selected_recipe_id": best[2]["style_id"],
        "selected_recipe_version": best[2].get("recipe_version"),
        "confidence": round(min(.95, .35 + min(best[0], 20) / 40), 2),
        "reasons": best[3] or ["best available approved internal recipe"],
        "override_used": bool(override_style_id),
        "candidates": [{
            "recipe_id": item[2]["style_id"], "recipe_version": item[2].get("recipe_version"),
            "score": item[0], "reasons": item[3],
        } for item in ranked[:5]],
    }


def retrieve_approved_examples(examples: Iterable[Dict[str, Any]], intent: Dict[str, Any],
                               recipe_id: str, target_seconds: int,
                               device_id: str | None = None, limit: int = 3) -> List[Dict[str, Any]]:
    query = set(intent.get("query_terms") or [])
    ranked = []
    for example in examples:
        # Until PB&J has account-level consent and permissions, retrieval stays
        # inside both the pinned recipe and the originating device boundary.
        if example.get("style_id") != recipe_id or example.get("device_id") != device_id:
            continue
        overlap = sorted(query & words(example.get("project_prompt", "")))
        duration_delta = abs(float(example.get("target_duration_seconds") or target_seconds) - target_seconds)
        score = len(overlap) * 3 + max(0, 3 - duration_delta / 30)
        if (example.get("revision_number") or 99) == 1:
            score += 2
        ranked.append((score, example.get("approved_at", ""), example, overlap, duration_delta))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [{
        "example_id": item[2].get("example_id"),
        "recipe_version": item[2].get("recipe_version"),
        "score": round(item[0], 3),
        "matched_terms": item[3],
        "duration_delta_seconds": round(item[4], 3),
        "revision_number": item[2].get("revision_number"),
        "project_prompt": item[2].get("project_prompt"),
        "approved_plan": item[2].get("approved_plan"),
    } for item in ranked[:limit]]


def classify_feedback(feedback: str, focus: Iterable[str] = ()) -> Dict[str, Any]:
    text = " ".join([feedback or "", *[str(item) for item in focus]]).lower()
    corrective_markers = (
        "didn't", "did not", "don't", "do not", "not", "wrong", "fix", "change",
        "different", "remove", "less", "more", "faster", "slower", "shorter", "longer",
        "could improve", "i dislike", "i hate",
    )
    positive_markers = (
        "great", "good", "love", "liked", "perfect", "works", "nailed", "keep this",
        "exactly right", "happy with",
    )
    def contains_marker(markers):
        return any(re.search(r"\b" + re.escape(term) + r"\b", text) for term in markers)

    if contains_marker(corrective_markers):
        feedback_polarity = "corrective"
    elif contains_marker(positive_markers):
        feedback_polarity = "positive"
    else:
        feedback_polarity = "neutral"
    if any(term in text for term in ("copyright", "unsafe", "privacy", "permission", "never generate")):
        suggested, confidence = "platform_guardrail_review", .8
    elif any(term in text for term in ("i always", "i prefer", "for all my", "remember that")):
        suggested, confidence = "user_preference_candidate", .75
    elif any(term in text for term in ("this clip", "this shot", "this project", "this video", "at 0:")):
        suggested, confidence = "project_only", .9
    elif any(term in text for term in ("opening", "ending", "pacing", "structure", "transitions")):
        suggested, confidence = "recipe_candidate", .55
    else:
        suggested, confidence = "project_only", .6
    return {
        "schema_version": "1.0", "method": "conservative_feedback_classifier_v1",
        "applied_scope": "project_only", "suggested_scope": suggested,
        "feedback_polarity": feedback_polarity,
        "confidence": confidence, "promotion_status": "not_promoted",
        "requires_confirmation": suggested == "user_preference_candidate",
        "instruction": "Use immediately only for this project; retain as evidence for later governed review.",
    }


def _ranges(plan: Dict[str, Any]) -> Dict[str, List[tuple[float, float]]]:
    result: Dict[str, List[tuple[float, float]]] = {}
    for segment in plan.get("video_segments") or []:
        source = segment.get("source_file_id")
        start, end = float(segment.get("source_start") or 0), float(segment.get("source_end") or 0)
        if source and end > start:
            result.setdefault(source, []).append((start, end))
    return result


def approval_outcomes(initial_plan: Dict[str, Any], approved_plan: Dict[str, Any], revision_count: int) -> Dict[str, Any]:
    initial, approved = _ranges(initial_plan or {}), _ranges(approved_plan or {})
    initial_seconds = sum(end - start for ranges in initial.values() for start, end in ranges)
    retained = 0.0
    for source, ranges in initial.items():
        for start, end in ranges:
            retained += sum(max(0.0, min(end, other_end) - max(start, other_start)) for other_start, other_end in approved.get(source, []))
    retained = min(retained, initial_seconds)
    ratio = retained / initial_seconds if initial_seconds else None
    initial_segments, approved_segments = initial_plan.get("video_segments") or [], approved_plan.get("video_segments") or []
    def edge_retained(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        return bool(first and second and first.get("source_file_id") == second.get("source_file_id") and
                    min(float(first.get("source_end") or 0), float(second.get("source_end") or 0)) >
                    max(float(first.get("source_start") or 0), float(second.get("source_start") or 0)))
    return {
        "schema_version": "1.0", "revision_count": revision_count,
        "first_cut_approved": revision_count == 1,
        "first_cut_selected_source_seconds": round(initial_seconds, 3),
        "retained_source_seconds": round(retained, 3),
        "first_cut_retention_ratio": round(ratio, 4) if ratio is not None else None,
        "opening_retained": edge_retained(initial_segments[0] if initial_segments else {}, approved_segments[0] if approved_segments else {}),
        "ending_retained": edge_retained(initial_segments[-1] if initial_segments else {}, approved_segments[-1] if approved_segments else {}),
    }
