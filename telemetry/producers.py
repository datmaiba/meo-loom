"""Closed Telemetry v3 producer status registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PRODUCER_IDS = (
    "build-loop-harvest",
    "diagnosing-bugs",
    "knowledge-work-fact-check",
    "task-handoff",
    "reports",
)
def _duplicate_object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("producer registry contains a duplicate key")
        result[key] = value
    return result


def validate_producer_registry(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "producers"}:
        raise ValueError("producer registry must use the closed versioned shape")
    if value["schema_version"] != 1 or isinstance(value["schema_version"], bool):
        raise ValueError("producer registry schema_version must be 1")
    entries = value["producers"]
    if not isinstance(entries, dict) or set(entries) != set(PRODUCER_IDS):
        raise ValueError("producer registry must contain exactly the five required producers")
    for producer_id, entry in entries.items():
        if not isinstance(entry, dict) or set(entry) != {"status", "event_id"}:
            raise ValueError(f"producer {producer_id} must use the closed status shape")
        if not isinstance(entry["status"], str) or entry["status"] not in {"planned", "active"}:
            raise ValueError(f"producer {producer_id} status must be planned or active")
        event_id = entry["event_id"]
        if entry["status"] == "planned" and event_id is not None:
            raise ValueError(f"planned producer {producer_id} event_id must be null")
        if entry["status"] == "active":
            raise ValueError(
                f"active producer {producer_id} requires a future approved resolver contract"
            )
    return value


def load_producer_registry(
    path: Path | str | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else Path(__file__).with_name("producers.json")
    try:
        value = json.loads(
            target.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_object_pairs,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("producer registry is not valid UTF-8 JSON") from error
    return validate_producer_registry(value)
