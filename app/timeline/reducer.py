from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Tuple

from .contracts import refresh_hash
from .operations import apply_inverse, apply_operation
from .validation import validate_timeline


def apply_transaction(timeline: Dict[str, Any], transaction: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    updated = deepcopy(timeline)
    inverses: List[Dict[str, Any]] = []
    try:
        for operation in transaction.get("operations") or []:
            inverse = apply_operation(updated, operation)
            if inverse:
                inverse.setdefault("operation_id", "inverse-" + str(operation.get("operation_id", "operation")))
                inverses.insert(0, inverse)
        updated["revision"] = int(timeline.get("revision", 0)) + 1
        refresh_hash(updated)
        validate_timeline(updated)
    except Exception:
        raise
    inverse_transaction = {
        "transaction_id": "inverse-" + transaction["transaction_id"],
        "origin": "system_undo",
        "reason": "Undo %s" % (transaction.get("reason") or transaction["transaction_id"]),
        "operations": inverses,
    }
    return updated, inverse_transaction


def apply_inverse_transaction(timeline: Dict[str, Any], transaction: Dict[str, Any]) -> Dict[str, Any]:
    updated = deepcopy(timeline)
    for operation in transaction.get("operations") or []:
        apply_inverse(updated, operation)
    updated["revision"] = int(timeline.get("revision", 0)) + 1
    refresh_hash(updated)
    validate_timeline(updated)
    return updated
