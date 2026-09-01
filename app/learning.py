"""Deterministic learning aggregation and project-requirement extraction.

The base recipe remains evidence-backed and immutable. This module builds a
reversible learned overlay from project outcomes, so every event contributes
without allowing one project to silently become a universal rule.
"""

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List
import re


CATEGORIES = ("structure", "pacing", "selection", "visual", "audio", "ending")
SCORE_TO_CATEGORY = {
    "story_order": "structure", "pacing": "pacing", "footage_selection": "selection",
    "style_match": "visual", "opening": "structure", "ending": "ending",
}


def permission_scoped_signals(signals: Iterable[Dict[str, Any]], project_id: str,
                              device_id: str | None) -> List[Dict[str, Any]]:
    """Return only learning evidence permitted to influence this project.

    Reference and governance evidence without a project owner remains part of
    the shared recipe. Project-derived evidence may cross projects only on the
    same device until account-level consent and permissions exist.
    """
    allowed = []
    for signal in signals:
        source_project = signal.get("project_id")
        if not source_project or source_project == project_id:
            allowed.append(signal)
            continue
        source_device = signal.get("device_id")
        if device_id is not None and source_device == device_id:
            allowed.append(signal)
        elif device_id is None and source_device is None:
            allowed.append(signal)
    return allowed


def _words(value: str) -> set:
    return {item for item in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(item) > 2}


def signal_categories(signal: Dict[str, Any]) -> List[str]:
    # Context and technical evidence are available to planning and evaluation,
    # but they cannot independently count as support for a style overlay.
    if signal.get("type") in (
        "raw_footage_upload", "reference_upload", "reference_analysis", "rough_cut_run",
        "recipe_correction", "recipe_version_approved",
    ):
        return []
    found = set()
    for item in signal.get("focus") or []:
        normalized = str(item).lower()
        for category in CATEGORIES:
            if category in normalized:
                found.add(category)
    text = " ".join(str(signal.get(key) or "") for key in ("instruction", "comments")).lower()
    aliases = {
        "structure": ("chronolog", "story", "order", "opening", "hook"),
        "pacing": ("pace", "pacing", "faster", "slower", "shorter", "longer"),
        "selection": ("include", "keep", "remove", "clip", "footage", "b-roll", "b roll"),
        "visual": ("crop", "framing", "zoom", "visual", "shot"),
        "audio": ("audio", "sound", "dialogue", "voice"),
        "ending": ("ending", "end on", "closure", "finish"),
    }
    for category, terms in aliases.items():
        if any(term in text for term in terms):
            found.add(category)
    for score_name, score in (signal.get("scores") or {}).items():
        if score and score_name in SCORE_TO_CATEGORY:
            found.add(SCORE_TO_CATEGORY[score_name])
    return sorted(found)


def consolidate_signals(signals: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    signals = list(signals)
    buckets = defaultdict(lambda: {"projects": set(), "support": set(), "contradict": set(), "scores": [], "instructions": []})
    for signal in signals:
        project_id = signal.get("project_id")
        for category in signal_categories(signal):
            bucket = buckets[category]
            if project_id:
                bucket["projects"].add(project_id)
            instruction = (signal.get("instruction") or signal.get("comments") or "").strip()
            if instruction and instruction not in bucket["instructions"]:
                bucket["instructions"].append(instruction)
            for score_name, score in (signal.get("scores") or {}).items():
                if SCORE_TO_CATEGORY.get(score_name) != category or not score:
                    continue
                bucket["scores"].append(float(score))
                if score >= 4 and project_id:
                    bucket["support"].add(project_id)
                elif score <= 2 and project_id:
                    bucket["contradict"].add(project_id)
            # A revision proves that a change was requested, not that the
            # existing recipe behavior was correct. Only explicit positive
            # confirmation may support a shared overlay.
            if signal.get("type") == "cut_revision" and project_id:
                polarity = (signal.get("feedback_classification") or {}).get("feedback_polarity")
                if polarity == "positive":
                    bucket["support"].add(project_id)

    insights = []
    for category in CATEGORIES:
        bucket = buckets.get(category)
        if not bucket:
            continue
        project_count = len(bucket["projects"])
        supporting = len(bucket["support"])
        contradicting = len(bucket["contradict"])
        average = round(sum(bucket["scores"]) / len(bucket["scores"]), 2) if bucket["scores"] else None
        if project_count >= 5 and supporting >= 3 and contradicting <= 1 and (average is None or average >= 3.5):
            status = "promoted_overlay"
        elif project_count >= 3:
            status = "candidate"
        else:
            status = "emerging"
        confidence = min(.95, round(.2 + project_count * .1 + supporting * .08 - contradicting * .1, 2))
        insights.append({
            "category": category, "status": status, "scope": "style",
            "project_count": project_count, "supporting_project_count": supporting,
            "contradicting_project_count": contradicting, "average_score": average,
            "confidence": max(.05, confidence), "recent_instructions": bucket["instructions"][:5],
        })
    return {
        "schema_version": "1.0", "signal_count": len(signals),
        "project_count": len({item.get("project_id") for item in signals if item.get("project_id")}),
        "promotion_policy": {"candidate_projects": 3, "promotion_projects": 5, "minimum_supporting_projects": 3, "maximum_contradicting_projects": 1},
        "insights": insights,
    }


def relevant_signals(signals: Iterable[Dict[str, Any]], prompt: str, project_id: str = "", limit: int = 12) -> List[Dict[str, Any]]:
    prompt_words = _words(prompt)
    ranked = []
    for signal in signals:
        text = " ".join(str(signal.get(key) or "") for key in ("instruction", "comments", "focus"))
        overlap = len(prompt_words & _words(text))
        score = overlap * 2
        if signal.get("project_id") == project_id:
            score += 6
        if signal.get("type") == "approved_cut":
            score += 3
        if signal.get("status") in ("candidate", "promoted_overlay"):
            score += 1
        ranked.append((score, signal.get("recorded_at", ""), signal))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit] if item[0] > 0]


def summarize_run_evidence(run: Dict[str, Any], plan_diff: Dict[str, Any],
                           decisions: Dict[str, Any], receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Compact run evidence for retrieval; exact artifacts remain path-linked."""
    decision_items = decisions.get("decisions") or []
    by_source = Counter(item.get("source_file_id") for item in decision_items if item.get("source_file_id"))
    selected_duration = round(sum(
        max(0.0, float(item.get("timeline_end") or 0) - float(item.get("timeline_start") or 0))
        for item in decision_items
    ), 3)
    checks = (receipt.get("verification") or {}).get("checks") or {}
    return {
        "run_id": run.get("run_id"),
        "revision_number": run.get("revision_number"),
        "feedback": run.get("feedback"),
        "plan_hash": receipt.get("plan_hash") or run.get("plan_hash"),
        "compiled_command_hash": receipt.get("compiled_command_hash"),
        "output_sha256": (receipt.get("output") or {}).get("sha256") or run.get("output_sha256"),
        "recipe_version": receipt.get("recipe_version"),
        "change_summary": plan_diff.get("summary") or {"added": plan_diff.get("change_count", 0)},
        "change_count": plan_diff.get("change_count", 0),
        "decision_count": len(decision_items),
        "selected_timeline_duration_seconds": selected_duration,
        "selected_segments_by_source": dict(sorted(by_source.items())),
        "qa": {name: {"status": value.get("status"), "required": value.get("required"),
                       **{key: value[key] for key in ("segment_count", "threshold_seconds") if key in value}}
               for name, value in checks.items()},
        "artifacts": {
            "plan_path": run.get("plan_path"),
            "decisions_path": run.get("decisions_path"),
            "plan_diff_path": run.get("plan_diff_path"),
            "render_receipt_path": run.get("render_receipt_path"),
            "output_path": run.get("output_path"),
        },
    }


def extract_requirements(prompt: str) -> List[Dict[str, Any]]:
    text = (prompt or "").strip()
    lowered = text.lower()
    requirements = []
    if any(term in lowered for term in ("chronological", "chronologic", "in order", "start to finish")):
        requirements.append({"requirement_id": "chronological", "type": "structure", "description": "Keep the story in chronological order", "required": True})
    if "b-roll" in lowered or "b roll" in lowered:
        requirements.append({"requirement_id": "b_roll", "type": "editorial_role", "role": "b_roll", "description": "Include relevant supplied B-roll", "required": True})
    patterns = (
        r"(?:include|keep|show|feature)\s+(?:the\s+)?([^,.!\n]{2,45})",
        r"make sure (?:to\s+)?(?:include|keep|show|feature)\s+(?:the\s+)?([^,.!\n]{2,45})",
    )
    ignored = {"video", "footage", "clip", "b roll", "b-roll", "chronological order"}
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, lowered):
            phrase = re.sub(r"\s+", " ", match.group(1)).strip(" -")
            phrase = re.split(r"\b(?:and then|while|but|with)\b", phrase)[0].strip()
            if phrase and phrase not in ignored and phrase not in seen:
                seen.add(phrase)
                requirements.append({"requirement_id": "include_%s" % re.sub(r"[^a-z0-9]+", "_", phrase).strip("_"), "type": "content", "term": phrase, "description": "Include footage showing %s" % phrase, "required": True})
    return requirements
