"""Public structural and authorization checks for the Telemetry v3 boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
CONTRACT = ROOT / "docs/contracts/telemetry-v3.md"
DECISION = ROOT / "docs/decisions/0007-telemetry-v3-public-baseline.md"
sys.path.insert(0, str(SCRIPTS))

from registry import Catalog, Diagnostic  # noqa: E402


def contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def prose(text: str) -> str:
    return " ".join(text.split())


def section(text: str, start: str, end: str) -> str:
    assert text.count(start) == 1, start
    assert text.count(end) == 1, end
    return text.split(start, 1)[1].split(end, 1)[0]


def markdown_table(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0].startswith("---") or cells[1] in {
            "Type and rule",
            "Exact payload fields",
        }:
            continue
        rows[cells[0].strip("`")] = cells[1]
    return rows


def canonical_hash(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def test_contract_is_routed_as_class_c_platform_contract() -> None:
    catalog = Catalog.load(ROOT)
    assert isinstance(catalog, Catalog), catalog
    explanation = catalog.explain_path("docs/contracts/telemetry-v3.md")
    assert not isinstance(explanation, Diagnostic), explanation
    assert explanation["component_id"] == "registry-contract"
    assert explanation["governance_class"] == "C"
    assert explanation["policy_revision"] == "platform-contract-policy/1"
    assert explanation["required_reviewers"] == [
        "knowledge-work-reviewer",
        "software-dev-reviewer",
    ]
    assert explanation["closer_authority_ref"] == "platform-owner"


def test_public_owner_decision_binds_the_exact_contract_hash() -> None:
    decision = DECISION.read_text(encoding="utf-8")
    match = re.search(r"Contract SHA-256: `([0-9a-f]{64})`", decision)
    assert match, "Decision 0007 must bind one lowercase SHA-256"
    assert match.group(1) == canonical_hash(CONTRACT)
    assert "Owner and approving authority: Dat Mai Ba" in decision
    assert "Effective boundary: MeoLoom 3.0 public clean-root commit" in decision


def test_effective_boundary_authorizes_runtime_without_activating_producers() -> None:
    text = contract_text()
    assert "Status: accepted and effective from the MeoLoom 3.0 public clean root" in text
    assert "docs/decisions/0007-telemetry-v3-public-baseline.md" in text
    assert "authorizes the contract, `scripts/telemetry.py`" in text
    assert "does not activate a producer by itself" in prose(text)
    assert "proposed; not effective" not in text
    assert "this proposal does not authorize" not in text


def test_envelope_table_owns_every_required_field_and_bound() -> None:
    text = contract_text()
    envelope = markdown_table(section(text, "## T3.3 Closed event envelope", "### T3.3.1 String grammars"))
    assert set(envelope) == {
        "schema_version", "event_id", "task_id", "event_type", "occurred_at",
        "producer", "revisions", "lineage", "source_class", "privacy_class",
        "coverage", "tokens", "elapsed", "payload",
    }
    assert envelope["schema_version"] == "integer literal `3`"
    assert "UUIDv4" in envelope["event_id"] and "unique" in envelope["event_id"]
    assert "correction_evidence_ref" in envelope["lineage"]
    bounded = prose(section(text, "## T3.3 Closed event envelope", "### T3.3.1 String grammars"))
    assert "maximum encoded event record is 65,536 UTF-8 bytes including its terminal LF" in bounded
    assert "Unknown fields are invalid" in text


def test_payload_table_owns_all_closed_event_shapes() -> None:
    lifecycle = section(contract_text(), "## T3.6 Lifecycle and closed event payloads", "## T3.7 Lineage and corrections")
    payloads = markdown_table(lifecycle)
    assert set(payloads) == {
        "task_started", "task_finished", "handoff_created", "task_resumed",
        "delegation_started", "gate_result", "review_result", "defect_recorded",
        "rework_recorded", "lesson_candidate_recorded", "fact_check_recorded",
        "scorecard_imported", "benchmark_exported",
    }
    assert "first_pass: bool" in payloads["gate_result"]
    assert "reviewer_id: stable-id" in payloads["review_result"]
    assert "finding_count: non-negative-integer" in payloads["fact_check_recorded"]


def test_coverage_lifecycle_lineage_and_corrections_are_closed() -> None:
    text = contract_text()
    coverage = prose(section(text, "### T3.5.1 Coverage", "### T3.5.2 Tokens"))
    lifecycle = section(text, "## T3.6 Lifecycle and closed event payloads", "## T3.7 Lineage and corrections")
    lineage = prose(section(text, "## T3.7 Lineage and corrections", "## T3.8 Append, validation, and recovery"))
    assert "requires at least one non-empty missing array" in coverage
    assert "full coverage requires both `task_started` and `task_finished`" in coverage
    assert "Exactly one original `task_started`" in lifecycle
    assert "Exactly one original `task_finished`" in lifecycle
    assert "forward, self, missing, or cyclic correction" in lineage
    assert "v3 has no owner-override shortcut" in lineage
    assert "fails with `TELEMETRY_PRIVACY_IRREVERSIBLE`" in lineage


def test_privacy_storage_and_recovery_are_bounded() -> None:
    text = prose(contract_text())
    for requirement in (
        "No telemetry field accepts free-form text",
        "Raw prompts, full user messages, tool request or response bodies",
        "environment values, credentials, secrets, arbitrary file contents",
        "open with `O_APPEND`",
        "rejects any symlink or reparse point",
        "regular file with link count one",
        "must not block the work loop",
    ):
        assert requirement in text


def test_import_export_and_append_only_surfaces_are_explicit() -> None:
    text = contract_text()
    transfer = prose(section(text, "## T3.10 Import, export, retention, and durable history", "## T3.11 Disable, downgrade, and compatibility"))
    assert "immutable source-record slot is path + ordinal" in transfer
    assert "never rewrites existing benchmark bytes" in transfer
    assert "`benchmark_exported` events are never export-eligible" in transfer
    for path in (
        "`telemetry/events.jsonl`",
        "`benchmarks/telemetry-v3.jsonl`",
        "`benchmarks/defects.jsonl`",
        "`benchmarks/scorecard.jsonl`",
    ):
        assert path in text


def test_required_producer_rows_match_public_status_truth() -> None:
    text = contract_text()
    producer_section = section(text, "## T3.12 Required producers and status truthfulness", "## T3.13 Conformance and release boundary")
    for requirement in (
        "build-loop HARVEST", "diagnosing-bugs", "knowledge-work fact-check",
        "task/handoff schema", "reports", "Every producer begins `planned`",
    ):
        assert requirement in producer_section
    descriptor = json.loads((ROOT / "telemetry/producers.json").read_text(encoding="utf-8"))
    assert set(descriptor["producers"]) == {
        "build-loop-harvest", "diagnosing-bugs", "knowledge-work-fact-check",
        "task-handoff", "reports",
    }
    assert {item["status"] for item in descriptor["producers"].values()} == {"planned"}


def test_public_runtime_schema_and_empty_corpus_baseline_exist() -> None:
    assert (ROOT / "scripts/telemetry.py").is_file()
    schema = json.loads((ROOT / "telemetry/schema-v3.json").read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == 3
    for relative in (
        "benchmarks/telemetry-v3.jsonl",
        "benchmarks/defects.jsonl",
        "benchmarks/scorecard.jsonl",
    ):
        assert (ROOT / relative).read_bytes() == b""
