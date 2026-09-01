"""Transparent usage and estimate reporting.

Rates are deliberately scoped to the configured analyzer defaults and stamped
with an as-of date. Provider dashboards remain authoritative for billing.
"""

from typing import Any, Dict, Iterable


PRICING_AS_OF = "2026-08-25"
GEMINI_37_FLASH_INPUT_PER_MILLION = 0.75
GEMINI_37_FLASH_OUTPUT_PER_MILLION = 3.75
PEGASUS_INPUT_PER_MINUTE = 0.0292
PEGASUS_OUTPUT_PER_THOUSAND = 0.0075


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _usage_value(usage: Dict[str, Any], *names: str) -> float:
    for name in names:
        if name in usage:
            return _number(usage[name])
    return 0.0


def analysis_cost_summary(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    total = 0.0
    records = []
    for result in results:
        provider = result.get("provider")
        usage = result.get("usage") or {}
        duration_seconds = _number(result.get("duration_seconds"))
        estimate = None
        basis = "Usage captured; rate not configured"
        if (result.get("cache") or {}).get("hit"):
            estimate = 0.0
            basis = "Reused local checksum cache; no new analyzer request"
        elif provider == "pegasus":
            output_tokens = _usage_value(usage, "output_tokens")
            estimate = duration_seconds / 60 * PEGASUS_INPUT_PER_MINUTE + output_tokens / 1000 * PEGASUS_OUTPUT_PER_THOUSAND
            basis = "$0.0292/input minute + $0.0075/1K output tokens"
        elif provider == "gemini" and result.get("model") == "gemini-3.7-flash":
            input_tokens = _usage_value(usage, "prompt_token_count", "input_tokens")
            output_tokens = _usage_value(usage, "candidates_token_count", "output_tokens") + _usage_value(usage, "thoughts_token_count")
            estimate = input_tokens / 1_000_000 * GEMINI_37_FLASH_INPUT_PER_MILLION + output_tokens / 1_000_000 * GEMINI_37_FLASH_OUTPUT_PER_MILLION
            basis = "$0.75/1M input + $3.75/1M output/thinking tokens (introductory rate)"
        if estimate is not None:
            total += estimate
        records.append({
            "file_id": result.get("file_id"), "provider": provider,
            "model": result.get("model"), "duration_seconds": duration_seconds,
            "usage": usage, "estimated_usd": round(estimate, 6) if estimate is not None else None,
            "basis": basis,
        })
    return {
        "pricing_as_of": PRICING_AS_OF, "currency": "USD",
        "estimated_usd": round(total, 6), "records": records,
        "disclaimer": "Estimate only. Free-tier credits, cached tokens, rounding, taxes, and provider changes may differ. Provider dashboards are authoritative.",
    }


def decision_usage_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    metadata = plan.get("decision_metadata") or {}
    return {
        "provider": "openai", "model": plan.get("decision_model"),
        "selection_usage": metadata.get("selection_usage", {}),
        "plan_usage": metadata.get("plan_usage", {}),
        "estimated_usd": None,
        "note": "Exact token usage is retained. No dollar estimate is shown unless the pinned model's current rate is verified for the account tier.",
    }
