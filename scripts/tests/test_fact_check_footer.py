"""B3 subset #3 — knowledge-work fact-check footer parser (telemetry-v3 T3.12).

Covers ``parse_fact_check_footer``: the closed ``fact_check_recorded`` payload
round-trip for both verdicts, every one of the seven failure classes, malformed-
footer rejection (unsorted/duplicate classes, sourced-with-findings, missing key,
duplicate JSON key, oversized input, non-object, wrong gate_id, bad markers),
newline-agnostic (CRLF) parsing, no-echo of the rejected value, that the shipped
deliverable template still carries the human verdict section (verdict preserved),
and that parsing activates NO producer (producers.json untouched, function pure).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import telemetry


REPO = SCRIPTS.parent
TEMPLATE = REPO / "domains" / "knowledge-work" / "deliverables" / "fact-check.template.md"
PRODUCERS = REPO / "telemetry" / "producers.json"

BEGIN = telemetry.FACT_CHECK_FOOTER_BEGIN
END = telemetry.FACT_CHECK_FOOTER_END

ALL_CLASSES = [
    "unsupported_claim", "weaker_than_claim", "contradiction", "unreliable_source",
    "stale_source", "inadequate_coverage", "prose_contradiction",
]


def footer(payload: dict, *, newline: str = "\n") -> str:
    body = json.dumps(payload, indent=2)
    text = f"prose above\n{BEGIN}\n```json\n{body}\n```\n{END}\nprose below\n"
    if newline != "\n":
        text = text.replace("\n", newline)
    return text


def sourced_payload(**over) -> dict:
    base = {
        "gate_id": "gate:fact", "verdict": "sourced", "verdict_source": "human",
        "finding_count": 0, "failure_classes": [], "evidence_ref": "evidence:fact:1",
    }
    base.update(over)
    return base


def rtb_payload(classes, **over) -> dict:
    base = {
        "gate_id": "gate:fact", "verdict": "return_to_builder", "verdict_source": "human",
        "finding_count": len(classes), "failure_classes": sorted(classes),
        "evidence_ref": "evidence:fact:1",
    }
    base.update(over)
    return base


def test_sourced_footer_round_trips():
    result = telemetry.parse_fact_check_footer(footer(sourced_payload()))
    assert result["verdict"] == "sourced"
    assert result["finding_count"] == 0
    assert result["failure_classes"] == []
    assert result["gate_id"] == "gate:fact"


def test_return_to_builder_footer_round_trips():
    result = telemetry.parse_fact_check_footer(footer(rtb_payload(["unsupported_claim", "stale_source"])))
    assert result["verdict"] == "return_to_builder"
    assert result["finding_count"] == 2
    assert result["failure_classes"] == ["stale_source", "unsupported_claim"]


@pytest.mark.parametrize("failure_class", ALL_CLASSES)
def test_each_failure_class_round_trips(failure_class):
    result = telemetry.parse_fact_check_footer(footer(rtb_payload([failure_class])))
    assert result["failure_classes"] == [failure_class]
    assert result["finding_count"] == 1


def test_crlf_checkout_parses_identically():
    crlf = telemetry.parse_fact_check_footer(footer(sourced_payload(), newline="\r\n"))
    lf = telemetry.parse_fact_check_footer(footer(sourced_payload()))
    assert crlf == lf


def test_verdict_source_agent_and_automation_accepted():
    for source in ("agent", "automation", "human"):
        result = telemetry.parse_fact_check_footer(footer(sourced_payload(verdict_source=source)))
        assert result["verdict_source"] == source


def test_sourced_with_findings_is_rejected():
    bad = sourced_payload(finding_count=1, failure_classes=["stale_source"])
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(bad))


def test_return_to_builder_without_findings_is_rejected():
    bad = rtb_payload([])
    bad["verdict"] = "return_to_builder"
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(bad))


def test_unsorted_failure_classes_rejected():
    bad = rtb_payload(["stale_source", "unsupported_claim"])
    bad["failure_classes"] = ["unsupported_claim", "stale_source"]  # not sorted
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(bad))


def test_duplicate_failure_classes_rejected():
    bad = rtb_payload(["stale_source"])
    bad["failure_classes"] = ["stale_source", "stale_source"]
    bad["finding_count"] = 2
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(bad))


def test_unknown_failure_class_rejected():
    bad = rtb_payload(["stale_source"])
    bad["failure_classes"] = ["not_a_real_class"]
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(bad))


def test_missing_key_rejected():
    bad = sourced_payload()
    del bad["evidence_ref"]
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(bad))


def test_wrong_gate_id_rejected():
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(footer(sourced_payload(gate_id="gate:pytest")))


def test_duplicate_json_key_rejected():
    raw = (
        f'{BEGIN}\n```json\n'
        '{"gate_id": "gate:fact", "gate_id": "gate:fact", "verdict": "sourced",'
        ' "verdict_source": "human", "finding_count": 0, "failure_classes": [],'
        ' "evidence_ref": "evidence:fact:1"}\n```\n' + END + "\n"
    )
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(raw)


def test_oversized_input_rejected():
    huge = "x" * (telemetry.MAX_RECORD_BYTES + 1)
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(huge)


def test_non_object_json_rejected():
    raw = f'{BEGIN}\n```json\n[1, 2, 3]\n```\n{END}\n'
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer(raw)


def test_missing_markers_rejected():
    with pytest.raises(telemetry.TelemetryError):
        telemetry.parse_fact_check_footer("no footer here")


def test_rejected_value_is_not_echoed():
    # The secret lives in evidence_ref AND is the field that triggers the
    # rejection (a space fails STABLE_REF grammar), so this actually exercises
    # the no-echo control rather than passing incidentally.
    secret = "SUPER SECRET TOKEN 9f3a"
    bad = sourced_payload(evidence_ref=secret)
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.parse_fact_check_footer(footer(bad))
    assert secret not in str(excinfo.value)
    assert "9f3a" not in str(excinfo.value)


def test_shipped_template_footer_parses():
    text = TEMPLATE.read_text(encoding="utf-8")
    result = telemetry.parse_fact_check_footer(text)
    assert result["gate_id"] == "gate:fact"
    assert result["verdict"] == "sourced"


def test_template_preserves_human_verdict_section():
    text = TEMPLATE.read_text(encoding="utf-8")
    # The human-facing sections must remain after the machine footer was added.
    assert "## Verdict summary" in text
    assert "## Claim-by-claim" in text
    assert "Verification record" in text


def test_parsing_does_not_activate_producer():
    before = json.loads(PRODUCERS.read_text(encoding="utf-8"))
    telemetry.parse_fact_check_footer(footer(sourced_payload()))
    after = json.loads(PRODUCERS.read_text(encoding="utf-8"))
    assert before == after
    assert after["producers"]["knowledge-work-fact-check"]["status"] == "planned"
