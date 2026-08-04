"""B3 subset #5 — reports-producer view constructor tests.

Two pure derivation functions over an already-validated lifecycle corpus:
``build_per_reviewer_view`` and ``build_event_coverage_rate_view``. No CLI, no
emit, no activation; the ``reports`` producer stays ``planned`` (telemetry-v3
T3.12). Every constructed event is re-validated through the UNCHANGED
``validate_event`` so the fixtures are contract-legal and the views are the only
new logic. Written observed-red-before-green per docs/agent-working-rules.md:
run against telemetry.py BEFORE the two functions exist to confirm the import /
AttributeError, then implement.
"""

from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import telemetry


# --- fixture helpers ---------------------------------------------------------

def _valid(event):
    """Re-validate every constructed event so fixtures cannot drift from the contract.

    ``producer.id`` is injected by the writer at append (telemetry-v3 L354); a raw
    ``_new_event`` omits it, so the fixture supplies it before validating.
    """
    event["producer"] = {"id": "reports", "revision": event["producer"]["revision"]}
    telemetry.validate_event(event)
    return event


def _host(event, host):
    """Set the host-adapter revision value used as the coverage-rate grouping key (D-1)."""
    if host is None:
        event["revisions"]["adapter"] = {"value": None, "unavailable_reason": "not_emitted"}
    else:
        event["revisions"]["adapter"] = {"value": host, "unavailable_reason": None}
    return event


_FULL = {"status": "full", "missing_event_types": [], "missing_requirement_refs": [], "reason": None}


def _partial(reason="producer_failure", missing=("review_result",)):
    return {
        "status": "partial",
        "missing_event_types": sorted(missing),
        "missing_requirement_refs": [],
        "reason": reason,
    }


def _start(task_id, workflow="software-dev", host="codex"):
    return _host(_valid(telemetry._new_event(task_id, "task_started", {"workflow": workflow})), host)


def _review(task_id, reviewer_id, reviewer_class, verdict, *, round=1, findings=0, host="codex"):
    ev = telemetry._new_event(
        task_id,
        "review_result",
        {
            "reviewer_id": reviewer_id,
            "reviewer_class": reviewer_class,
            "round": round,
            "verdict": verdict,
            "verdict_source": "agent",
            "finding_count": findings,
            "evidence_ref": None,
        },
    )
    return _host(_valid(ev), host)


def _defect(task_id, defect_id, approving, *, gate="gate:qa", host="codex"):
    ev = telemetry._new_event(
        task_id,
        "defect_recorded",
        {
            "defect_id": defect_id,
            "introduced_task": None,
            "approving_reviewers": sorted(approving),
            "gate_that_should_have_caught_it": gate,
            "evidence_ref": "defects/d.md",
        },
    )
    return _host(_valid(ev), host)


def _finish(task_id, coverage, *, host="codex"):
    ev = telemetry._new_event(task_id, "task_finished", {"outcome": "completed", "scorecard_ref": None})
    ev["coverage"] = coverage
    return _host(_valid(ev), host)


def _finish_aborted(task_id, coverage, *, host="codex"):
    ev = telemetry._new_event(task_id, "task_finished", {"outcome": "aborted", "scorecard_ref": None})
    ev["coverage"] = coverage
    return _host(_valid(ev), host)


def _scorecard(task_id, *, host="codex"):
    ev = telemetry._new_event(
        task_id,
        "scorecard_imported",
        {
            "source_path": "benchmarks/scorecard.jsonl",
            "source_record_ordinal": 1,
            "source_record_hash": "a" * 64,
            "source_record_ref": "scorecard#1",
        },
    )
    return _host(_valid(ev), host)


def _correct_finish(target_event, coverage):
    """A correction of ``target_event`` (a task_finished) carrying a new terminal coverage."""
    ev = telemetry._new_event(target_event["task_id"], "task_finished", {"outcome": "completed", "scorecard_ref": None})
    ev["coverage"] = coverage
    ev["lineage"]["correction_of"] = target_event["event_id"]
    ev["lineage"]["correction_evidence_ref"] = "corrections/c.md"
    ev["revisions"] = dict(target_event["revisions"])
    return _valid(ev)


T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
T3 = "33333333-3333-4333-8333-333333333333"
T4 = "44444444-4444-4444-8444-444444444444"


# --- per-reviewer view -------------------------------------------------------

def test_per_reviewer_groups_rounds_and_verdicts():
    events = [
        _start(T1),
        _review(T1, "rev:alice", "qa", "return_to_builder", round=1, findings=3),
        _review(T1, "rev:alice", "qa", "phase_done", round=2, findings=0),
        _review(T1, "rev:bob", "security", "approve", round=1),
        _finish(T1, _FULL),
    ]
    view = telemetry.build_per_reviewer_view(events)
    alice = next(r for r in view["reviewers"] if r["reviewer_id"] == "rev:alice")
    assert alice["reviewer_class"] == "qa"
    assert alice["rounds"] == 2
    assert alice["verdicts"] == {"return_to_builder": 1, "phase_done": 1}
    assert alice["linked_defects"] == []
    # deterministic ordering by (reviewer_class, reviewer_id)
    assert [r["reviewer_id"] for r in view["reviewers"]] == ["rev:alice", "rev:bob"]


def test_per_reviewer_joins_defect_on_approving_reviewers():
    events = [
        _start(T1),
        _review(T1, "rev:alice", "qa", "phase_done"),
        _defect(T1, "defect:x", ["rev:alice"]),
    ]
    view = telemetry.build_per_reviewer_view(events)
    alice = next(r for r in view["reviewers"] if r["reviewer_id"] == "rev:alice")
    assert alice["linked_defects"] == ["defect:x"]
    assert view["unlinked_defects"] == []
    assert view["unknown_reviewers"] == []


def test_per_reviewer_empty_approving_is_unlinked_not_dropped():
    events = [
        _start(T1),
        _review(T1, "rev:alice", "qa", "phase_done"),
        _defect(T1, "defect:orphan", []),
    ]
    view = telemetry.build_per_reviewer_view(events)
    assert view["unlinked_defects"] == ["defect:orphan"]


def test_per_reviewer_mixed_known_and_unknown_edges_both_surface():
    # finding 4: [known, unknown] links the known reviewer AND exposes the unknown id.
    events = [
        _start(T1),
        _review(T1, "rev:alice", "qa", "phase_done"),
        _defect(T1, "defect:m", ["rev:alice", "rev:ghost"]),
    ]
    view = telemetry.build_per_reviewer_view(events)
    alice = next(r for r in view["reviewers"] if r["reviewer_id"] == "rev:alice")
    assert alice["linked_defects"] == ["defect:m"]
    assert view["unknown_reviewers"] == ["rev:ghost"]
    assert view["unlinked_defects"] == []


def test_per_reviewer_all_unknown_approvers_defect_not_dropped():
    # finding 1: every approver unknown -> defect_id must still surface (unlinked),
    # and each unknown id surfaces in unknown_reviewers. No dropped defect (T3.12).
    events = [
        _start(T1),
        _review(T1, "rev:alice", "qa", "phase_done"),
        _defect(T1, "defect:ghosted", ["rev:ghost", "rev:phantom"]),
    ]
    view = telemetry.build_per_reviewer_view(events)
    assert view["unlinked_defects"] == ["defect:ghosted"]
    assert view["unknown_reviewers"] == ["rev:ghost", "rev:phantom"]
    alice = next(r for r in view["reviewers"] if r["reviewer_id"] == "rev:alice")
    assert alice["linked_defects"] == []


def test_per_reviewer_correction_does_not_double_count():
    base = _review(T1, "rev:alice", "qa", "return_to_builder", round=1)
    correction = telemetry._new_event(
        T1, "review_result",
        {
            "reviewer_id": "rev:alice", "reviewer_class": "qa", "round": 1,
            "verdict": "phase_done", "verdict_source": "agent",
            "finding_count": 0, "evidence_ref": None,
        },
    )
    correction["lineage"]["correction_of"] = base["event_id"]
    correction["lineage"]["correction_evidence_ref"] = "corrections/r.md"
    _valid(correction)
    events = [_start(T1), base, correction, _finish(T1, _FULL)]
    view = telemetry.build_per_reviewer_view(events)
    alice = next(r for r in view["reviewers"] if r["reviewer_id"] == "rev:alice")
    assert alice["rounds"] == 1  # correction is not a second original round
    assert alice["verdicts"] == {"return_to_builder": 1}


# --- event-coverage-rate view ------------------------------------------------

def test_coverage_rate_full_over_mixed():
    events = [
        _start(T1), _finish(T1, _FULL),
        _start(T2), _finish(T2, _partial()),
    ]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["numerator"] == 1
    assert host["denominator"] == 2
    assert host["rate"] == 0.5
    assert host["reason"] is None


def test_coverage_rate_completion_only_stays_in_denominator():
    # completion-only task: lone partial task_finished, no start (T3.5.1 L176).
    lone = _finish(T2, _partial(reason="completion_only", missing=("task_started",)))
    events = [_start(T1), _finish(T1, _FULL), lone]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["numerator"] == 1
    assert host["denominator"] == 2


def test_coverage_rate_aborted_counts_in_denominator():
    # D-3: outcome=aborted is terminal-observed -> denominator.
    events = [_start(T1), _finish(T1, _FULL), _start(T2), _finish_aborted(T2, _partial())]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["denominator"] == 2
    assert host["numerator"] == 1


def test_coverage_rate_scorecard_only_counts_in_denominator():
    events = [_start(T1), _finish(T1, _FULL), _scorecard(T2)]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["denominator"] == 2
    assert host["numerator"] == 1  # scorecard_imported is partial, never full


def test_coverage_rate_zero_completed_is_null_no_observed_tasks():
    # a started-but-unfinished task is not terminal-observed.
    events = [_start(T1)]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["denominator"] == 0
    assert host["rate"] is None
    assert host["reason"] == "no_observed_tasks"


def test_coverage_rate_numerator_is_correction_aware():
    # finding 1 (BLOCKER): a full finish corrected down to partial leaves the numerator.
    original = _finish(T1, _FULL)
    correction = _correct_finish(original, _partial())
    events = [_start(T1), original, correction]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["denominator"] == 1
    assert host["numerator"] == 0  # latest valid terminal coverage is the correction's partial


def test_coverage_rate_multi_level_correction_chain():
    # finding 3: correction-of-a-correction -> the chain tip's coverage wins.
    original = _finish(T1, _FULL)
    first = _correct_finish(original, _partial())
    second = _correct_finish(first, _FULL)  # corrects the correction, back to full
    events = [_start(T1), original, first, second]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["numerator"] == 1  # latest valid terminal coverage is the tip's full


def test_coverage_rate_ignores_in_progress_snapshot():
    # a non-terminal snapshot must not be read as the terminal coverage.
    events = [_start(T1), _finish(T1, _FULL)]
    view = telemetry.build_event_coverage_rate_view(events)
    host = next(h for h in view["hosts"] if h["host"] == "codex")
    assert host["numerator"] == 1


def test_coverage_rate_groups_by_host():
    events = [
        _start(T1, host="codex"), _finish(T1, _FULL, host="codex"),
        _start(T2, host="claude-code"), _finish(T2, _partial(), host="claude-code"),
    ]
    view = telemetry.build_event_coverage_rate_view(events)
    assert [h["host"] for h in view["hosts"]] == ["claude-code", "codex"]
    codex = next(h for h in view["hosts"] if h["host"] == "codex")
    cc = next(h for h in view["hosts"] if h["host"] == "claude-code")
    assert codex["rate"] == 1.0
    assert cc["rate"] == 0.0
