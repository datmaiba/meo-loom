"""B3 subset #4 — build_resume_linkage constructor tests.

Fork A: a pure helper that derives the linkage-correct ``task_resumed`` inputs
from an already-validated event stream. No CLI, no activation; the ``task-handoff``
producer stays ``planned``. Every constructed event is re-validated through the
UNCHANGED validators (`_validate_payload`, `_validate_task_sequences`,
`_expected_coverage`) so there is no second source of truth for linkage.
"""

import copy
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import telemetry


def _start(task_id, workflow="software-dev", parent_task_id=None, delegation_id=None):
    return telemetry._new_event(
        task_id, "task_started", {"workflow": workflow},
        parent_task_id=parent_task_id, delegation_id=delegation_id,
    )


def _handoff(task_id, ref, reason="deliberate_pause", parent_task_id=None, delegation_id=None):
    return telemetry._new_event(
        task_id, "handoff_created", {"handoff_ref": ref, "reason": reason},
        parent_task_id=parent_task_id, delegation_id=delegation_id,
    )


def _resume_event(link):
    return telemetry._new_event(
        link["task_id"], "task_resumed", link["payload"],
        parent_task_id=link["parent_task_id"], delegation_id=link["delegation_id"],
    )


def _finish(task_id, parent_task_id=None, delegation_id=None):
    return telemetry._new_event(
        task_id, "task_finished", {"outcome": "completed", "scorecard_ref": None},
        parent_task_id=parent_task_id, delegation_id=delegation_id,
    )


TASK = "11111111-1111-4111-8111-111111111111"
CHILD = "22222222-2222-4222-8222-222222222222"
DELEG = "33333333-3333-4333-8333-333333333333"


def test_single_open_handoff_builds_correct_payload():
    handoff = _handoff(TASK, "handoffs/a.md")
    events = [_start(TASK), handoff]
    link = telemetry.build_resume_linkage(events, TASK)
    assert link["task_id"] == TASK
    assert link["payload"] == {
        "handoff_ref": "handoffs/a.md",
        "resumed_from_handoff": True,
        "resumed_from_event_id": handoff["event_id"],
    }
    assert link["parent_task_id"] is None
    assert link["delegation_id"] is None


def test_selects_most_recent_unmatched_handoff():
    first = _handoff(TASK, "handoffs/first.md")
    second = _handoff(TASK, "handoffs/second.md")
    events = [_start(TASK), first, second]
    link = telemetry.build_resume_linkage(events, TASK)
    assert link["payload"]["resumed_from_event_id"] == second["event_id"]
    assert link["payload"]["handoff_ref"] == "handoffs/second.md"


def test_after_resume_older_handoff_remains_selectable():
    first = _handoff(TASK, "handoffs/first.md")
    second = _handoff(TASK, "handoffs/second.md")
    events = [_start(TASK), first, second]
    resume_second = _resume_event(telemetry.build_resume_linkage(events, TASK))
    events.append(resume_second)
    link = telemetry.build_resume_linkage(events, TASK)
    assert link["payload"]["resumed_from_event_id"] == first["event_id"]
    assert link["payload"]["handoff_ref"] == "handoffs/first.md"


def test_delegation_brief_handoff_is_never_selected():
    events = [_start(TASK), _handoff(TASK, "handoffs/brief.md", reason="delegation_brief")]
    with pytest.raises(telemetry.TelemetryError):
        telemetry.build_resume_linkage(events, TASK)


def test_real_handoff_selected_over_delegation_brief():
    real = _handoff(TASK, "handoffs/real.md")
    brief = _handoff(TASK, "handoffs/brief.md", reason="delegation_brief")
    events = [_start(TASK), real, brief]
    link = telemetry.build_resume_linkage(events, TASK)
    assert link["payload"]["resumed_from_event_id"] == real["event_id"]
    assert link["payload"]["handoff_ref"] == "handoffs/real.md"


def test_delegated_child_lineage_is_preserved():
    events = [
        _start(CHILD, parent_task_id=TASK, delegation_id=DELEG),
        _handoff(CHILD, "handoffs/child.md", parent_task_id=TASK, delegation_id=DELEG),
    ]
    link = telemetry.build_resume_linkage(events, CHILD)
    assert link["parent_task_id"] == TASK
    assert link["delegation_id"] == DELEG


def test_no_lifecycle_events_for_task_is_rejected():
    events = [_start("44444444-4444-4444-8444-444444444444")]
    with pytest.raises(telemetry.TelemetryError):
        telemetry.build_resume_linkage(events, TASK)


def test_finished_task_is_rejected():
    events = [_start(TASK), _handoff(TASK, "handoffs/a.md"), _finish(TASK)]
    with pytest.raises(telemetry.TelemetryError):
        telemetry.build_resume_linkage(events, TASK)


def test_all_handoffs_already_resumed_is_rejected():
    handoff = _handoff(TASK, "handoffs/a.md")
    events = [_start(TASK), handoff]
    events.append(_resume_event(telemetry.build_resume_linkage(events, TASK)))
    with pytest.raises(telemetry.TelemetryError):
        telemetry.build_resume_linkage(events, TASK)


def test_round_trip_validates_and_reports_full_coverage():
    events = [_start(TASK), _handoff(TASK, "handoffs/a.md")]
    events.append(_resume_event(telemetry.build_resume_linkage(events, TASK)))
    events.append(_finish(TASK))
    # Unchanged linkage validators accept the constructed sequence.
    telemetry._validate_task_sequences(events)
    telemetry._validate_delegations(events)
    coverage = telemetry._expected_coverage(events, TASK)
    assert coverage["status"] == "full"


def test_payload_passes_task_resumed_validator():
    events = [_start(TASK), _handoff(TASK, "handoffs/a.md")]
    link = telemetry.build_resume_linkage(events, TASK)
    telemetry._validate_payload("task_resumed", link["payload"])


def test_helper_does_not_mutate_input():
    events = [_start(TASK), _handoff(TASK, "handoffs/a.md")]
    before = copy.deepcopy(events)
    telemetry.build_resume_linkage(events, TASK)
    assert events == before


def test_helper_writes_nothing(tmp_path):
    events = [_start(TASK), _handoff(TASK, "handoffs/a.md")]
    before = {p.name for p in tmp_path.iterdir()}
    telemetry.build_resume_linkage(events, TASK)
    assert {p.name for p in tmp_path.iterdir()} == before
