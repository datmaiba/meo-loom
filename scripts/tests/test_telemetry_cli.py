import argparse
import json
from pathlib import Path
import sys
import uuid

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import telemetry


def invoke(capsys, root: Path, *args: str, env=None):
    code = telemetry.main(
        ["--repository-root", str(root), *args],
        environ={} if env is None else env,
    )
    captured = capsys.readouterr()
    stream = captured.out if captured.out else captured.err
    return code, json.loads(stream)


def append(capsys, root: Path, task_id: str, event_type: str, payload: dict, *lineage: str):
    return invoke(
        capsys,
        root,
        "append",
        "--task-id",
        task_id,
        "--event",
        event_type,
        "--payload-json",
        json.dumps(payload, separators=(",", ":")),
        *lineage,
    )


def start(capsys, root: Path, workflow="other"):
    code, result = invoke(capsys, root, "start", "--workflow", workflow)
    assert code == 0 and result["status"] == "ok"
    return result["task_id"]


def records(root: Path):
    return telemetry.validate_lifecycle_events(root)


def test_start_mints_uuidv4_and_validate_is_structured_and_read_only(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    assert uuid.UUID(task_id).version == 4
    first = records(tmp_path)[0]
    assert first["task_id"] == task_id
    assert first["event_type"] == "task_started"
    assert first["producer"] == {"id": "dat-kit-cli", "revision": "telemetry-cli/1"}
    before = (tmp_path / telemetry.EVENT_PATH).read_bytes()

    code, result = invoke(capsys, tmp_path, "validate")
    assert (code, result["status"], result["event_count"]) == (0, "ok", 1)
    assert (tmp_path / telemetry.EVENT_PATH).read_bytes() == before


def test_normal_cardinality_and_post_finish_rejection_are_non_mutating(tmp_path, capsys):
    task_id = start(capsys, tmp_path, "build-loop")
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()

    code, result = append(capsys, tmp_path, task_id, "task_started", {"workflow": "build-loop"})
    assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"
    assert path.read_bytes() == before

    append(capsys, tmp_path, task_id, "gate_result", {
        "gate_id": "gate:pytest", "outcome": "pass", "first_pass": True,
        "verdict_source": "automation", "evidence_ref": "evidence:pytest:1",
    })
    append(capsys, tmp_path, task_id, "review_result", {
        "reviewer_id": "reviewer:code", "reviewer_class": "software-dev",
        "round": 1, "verdict": "approve", "verdict_source": "agent",
        "finding_count": 0, "evidence_ref": "evidence:review:1",
    })
    code, result = invoke(capsys, tmp_path, "finish", "--task-id", task_id, "--outcome", "completed")
    assert code == 0 and result["status"] == "ok"
    before = path.read_bytes()

    for args in [
        ("finish", "--task-id", task_id, "--outcome", "completed"),
        ("append", "--task-id", task_id, "--event", "gate_result", "--payload-json", json.dumps({
            "gate_id": "gate:late", "outcome": "pass", "first_pass": True,
            "verdict_source": "automation", "evidence_ref": None,
        })),
    ]:
        code, result = invoke(capsys, tmp_path, *args)
        assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"
        assert path.read_bytes() == before


def test_completion_only_is_the_sole_finish_time_minting_path(tmp_path, capsys):
    code, result = invoke(capsys, tmp_path, "finish", "--completion-only", "--outcome", "completed")
    assert code == 0 and uuid.UUID(result["task_id"]).version == 4
    item = records(tmp_path)[0]
    assert item["event_type"] == "task_finished"
    assert item["coverage"] == {
        "status": "partial",
        "missing_event_types": ["task_started"],
        "missing_requirement_refs": [],
        "reason": "completion_only",
    }
    before = (tmp_path / telemetry.EVENT_PATH).read_bytes()
    code, result = invoke(capsys, tmp_path, "finish", "--task-id", item["task_id"])
    assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"
    assert (tmp_path / telemetry.EVENT_PATH).read_bytes() == before

    code, result = invoke(
        capsys, tmp_path, "finish", "--completion-only",
        "--degraded-reason", "producer_failure",
    )
    assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"

    imported = {
        **item,
        "source_class": "legacy_import",
        "coverage": {**item["coverage"], "reason": "telemetry_disabled"},
    }
    (tmp_path / telemetry.EVENT_PATH).write_text(
        json.dumps(imported, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert telemetry.validate_lifecycle_events(tmp_path) == [imported]


def test_correction_coverage_is_validated_against_current_lifecycle(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    invoke(capsys, tmp_path, "finish", "--task-id", task_id)
    path = tmp_path / telemetry.EVENT_PATH
    original = records(tmp_path)[-1]
    correction = {
        **original,
        "event_id": str(uuid.uuid4()),
        "lineage": {
            **original["lineage"],
            "correction_of": original["event_id"],
            "correction_evidence_ref": "evidence:correction:1",
        },
        "coverage": {
            "status": "partial",
            "missing_event_types": ["task_started"],
            "missing_requirement_refs": [],
            "reason": "completion_only",
        },
    }
    with path.open("a", encoding="utf-8", newline="") as stream:
        stream.write(json.dumps(correction, sort_keys=True, separators=(",", ":")) + "\n")
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry.validate_lifecycle_events(tmp_path)
    assert caught.value.code == "TELEMETRY_LIFECYCLE_INVALID"


def test_closed_append_surface_accepts_every_nonterminal_payload(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    cause = str(uuid.uuid4())
    delegation = str(uuid.uuid4())
    child = str(uuid.uuid4())
    handoff_payload = {"handoff_ref": "handoffs/task.md", "reason": "deliberate_pause"}
    payloads = [
        ("handoff_created", handoff_payload),
        ("delegation_started", {"delegation_id": delegation, "child_task_id": child,
                                "delegated_role": "role:builder", "brief_ref": "handoffs/brief.md"}),
        ("gate_result", {"gate_id": "gate:pytest", "outcome": "pass", "first_pass": True,
                         "verdict_source": "automation", "evidence_ref": "evidence:gate:1"}),
        ("review_result", {"reviewer_id": "reviewer:code", "reviewer_class": "software-dev",
                           "round": 1, "verdict": "approve", "verdict_source": "agent",
                           "finding_count": 0, "evidence_ref": "evidence:review:1"}),
        ("defect_recorded", {"defect_id": "defect:1", "introduced_task": None,
                             "approving_reviewers": ["reviewer:code"],
                             "gate_that_should_have_caught_it": "gate:pytest",
                             "evidence_ref": "evidence:defect:1"}),
        ("rework_recorded", {"cause_event_id": cause, "round": 1,
                             "reason": "review_finding", "evidence_ref": None}),
        ("lesson_candidate_recorded", {"kit_facing": True,
                                       "root_cause_ref": "evidence:root:1",
                                       "candidate_ref": "evidence:candidate:1"}),
        ("fact_check_recorded", {"gate_id": "gate:fact", "verdict": "sourced",
                                 "verdict_source": "human", "finding_count": 0,
                                 "failure_classes": [], "evidence_ref": "evidence:fact:1"}),
        ("scorecard_imported", {"source_path": "benchmarks/scorecard.jsonl",
                                "source_record_ordinal": 1, "source_record_hash": "a" * 64,
                                "source_record_ref": "scorecard:1"}),
        ("benchmark_exported", {"export_batch_id": str(uuid.uuid4()),
                                "target_path": "benchmarks/telemetry-v3.jsonl",
                                "prior_hash": None, "exported_event_ids": [str(uuid.uuid4())]}),
    ]
    handoff_event_id = None
    for event_type, payload in payloads:
        code, result = append(capsys, tmp_path, task_id, event_type, payload)
        assert code == 0 and result["status"] == "ok"
        if event_type == "handoff_created":
            handoff_event_id = result["event_id"]
    code, result = append(capsys, tmp_path, task_id, "task_resumed", {
        "handoff_ref": "handoffs/task.md", "resumed_from_handoff": True,
        "resumed_from_event_id": handoff_event_id,
    })
    assert code == 0 and result["status"] == "ok"
    code, _ = invoke(capsys, tmp_path, "finish", "--task-id", task_id)
    assert code == 0


def test_delegation_pair_uniqueness_and_cycles_fail_without_mutation(tmp_path, capsys):
    parent = start(capsys, tmp_path)
    child = str(uuid.uuid4())
    delegation = str(uuid.uuid4())
    payload = {"delegation_id": delegation, "child_task_id": child,
               "delegated_role": "role:builder", "brief_ref": "handoffs/brief.md"}
    assert append(capsys, tmp_path, parent, "delegation_started", payload)[0] == 0
    lineage = ("--parent-task-id", parent, "--delegation-id", delegation)
    assert append(capsys, tmp_path, child, "task_started", {"workflow": "other"}, *lineage)[0] == 0
    path = tmp_path / telemetry.EVENT_PATH

    before = path.read_bytes()
    duplicate = {**payload, "child_task_id": str(uuid.uuid4())}
    code, result = append(capsys, tmp_path, parent, "delegation_started", duplicate)
    assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"
    assert path.read_bytes() == before

    cycle = {"delegation_id": str(uuid.uuid4()), "child_task_id": parent,
             "delegated_role": "role:builder", "brief_ref": "handoffs/cycle.md"}
    code, result = append(capsys, tmp_path, child, "delegation_started", cycle, *lineage)
    assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"
    assert path.read_bytes() == before


def test_handoff_resume_requires_same_task_ref_event_and_one_use(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    _, handoff = append(capsys, tmp_path, task_id, "handoff_created", {
        "handoff_ref": "handoffs/task.md", "reason": "context_ceiling",
    })
    resume = {"handoff_ref": "handoffs/task.md", "resumed_from_handoff": True,
              "resumed_from_event_id": handoff["event_id"]}
    assert append(capsys, tmp_path, task_id, "task_resumed", resume)[0] == 0
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()
    code, result = append(capsys, tmp_path, task_id, "task_resumed", resume)
    assert code != 0 and result["code"] == "TELEMETRY_LIFECYCLE_INVALID"
    assert path.read_bytes() == before


def test_coverage_arrays_shrink_exactly_and_finish_full(tmp_path, capsys):
    task_id = start(capsys, tmp_path, "build-loop")
    append(capsys, tmp_path, task_id, "gate_result", {
        "gate_id": "gate:pytest", "outcome": "pass", "first_pass": True,
        "verdict_source": "automation", "evidence_ref": None,
    })
    append(capsys, tmp_path, task_id, "review_result", {
        "reviewer_id": "reviewer:code", "reviewer_class": "software-dev", "round": 1,
        "verdict": "approve", "verdict_source": "agent", "finding_count": 0,
        "evidence_ref": None,
    })
    _, handoff = append(capsys, tmp_path, task_id, "handoff_created", {
        "handoff_ref": "handoffs/task.md", "reason": "deliberate_pause",
    })
    append(capsys, tmp_path, task_id, "task_resumed", {
        "handoff_ref": "handoffs/task.md", "resumed_from_handoff": True,
        "resumed_from_event_id": handoff["event_id"],
    })
    invoke(capsys, tmp_path, "finish", "--task-id", task_id)
    coverages = [item["coverage"] for item in records(tmp_path)]
    assert coverages[0]["missing_event_types"] == ["gate_result", "review_result", "task_finished"]
    assert coverages[1]["missing_event_types"] == ["review_result", "task_finished"]
    assert coverages[2]["missing_event_types"] == ["task_finished"]
    assert coverages[3]["missing_requirement_refs"] == [
        f"handoff:{handoff['event_id']}:task_resumed"
    ]
    assert coverages[4]["missing_requirement_refs"] == []
    assert coverages[-1] == {"status": "full", "missing_event_types": [],
                             "missing_requirement_refs": [], "reason": None}


def test_disabled_and_operational_failure_are_nonblocking_and_non_mutating(tmp_path, capsys, monkeypatch):
    code, result = invoke(capsys, tmp_path, "start", "--workflow", "other",
                          env={"DAT_KIT_TELEMETRY": "off"})
    assert (code, result["status"]) == (0, "disabled")
    assert not (tmp_path / telemetry.EVENT_PATH).exists()

    real_open = telemetry.os.open

    def unavailable(path, *args, **kwargs):
        if str(path).endswith("events.jsonl"):
            raise PermissionError("secret operational detail")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(telemetry.os, "open", unavailable)
    code, result = invoke(capsys, tmp_path, "start", "--workflow", "other")
    assert (code, result["status"], result["code"]) == (0, "degraded", "TELEMETRY_OPERATIONAL_FAILURE")
    assert "secret operational detail" not in json.dumps(result)
    assert not (tmp_path / telemetry.EVENT_PATH).exists()

    monkeypatch.undo()
    real_lstat = Path.lstat

    def root_unavailable(path):
        if path == tmp_path:
            raise PermissionError("secret repository-root detail")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", root_unavailable)
    code, result = invoke(capsys, tmp_path, "start", "--workflow", "other")
    assert (code, result["status"], result["code"]) == (0, "degraded", "TELEMETRY_OPERATIONAL_FAILURE")
    assert "secret repository-root detail" not in json.dumps(result)


@pytest.mark.parametrize("case", ["malformed", "oversized", "unknown-task", "corrupt", "future"])
def test_strict_failures_are_nonzero_do_not_echo_and_do_not_mutate(tmp_path, capsys, case):
    path = tmp_path / telemetry.EVENT_PATH
    secret = "synthetic-secret-value-that-must-not-echo"
    if case in {"corrupt", "future"}:
        path.parent.mkdir()
        raw = b"not-json\n" if case == "corrupt" else b'{"schema_version":4}\n'
        path.write_bytes(raw)
        before = raw
        code, result = invoke(capsys, tmp_path, "validate")
    elif case == "unknown-task":
        before = None
        code, result = append(capsys, tmp_path, str(uuid.uuid4()), "gate_result", {
            "gate_id": "gate:pytest", "outcome": "pass", "first_pass": True,
            "verdict_source": "automation", "evidence_ref": None,
        })
    else:
        task_id = start(capsys, tmp_path)
        before = path.read_bytes()
        payload = "{" + secret if case == "malformed" else json.dumps({"x": secret * 4000})
        code, result = invoke(capsys, tmp_path, "append", "--task-id", task_id,
                              "--event", "gate_result", "--payload-json", payload)
    assert code != 0 and result["status"] == "error"
    assert secret not in json.dumps(result)
    if before is None:
        assert not path.exists()
    else:
        assert path.read_bytes() == before
    if case == "future":
        assert result["code"] == "TELEMETRY_SCHEMA_UNSUPPORTED"


def finish_event(events, task_id):
    lineage = events[0]["lineage"]
    return telemetry._new_event(
        task_id,
        "task_finished",
        {"outcome": "completed", "scorecard_ref": None},
        parent_task_id=lineage["parent_task_id"],
        delegation_id=lineage["delegation_id"],
    )


def test_raced_duplicate_finish_is_rejected_against_the_locked_corpus(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    stale = records(tmp_path)
    invoke(capsys, tmp_path, "finish", "--task-id", task_id)
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._append_lifecycle_event(tmp_path, stale, finish_event(stale, task_id))
    assert caught.value.code == "TELEMETRY_LIFECYCLE_INVALID"
    assert path.read_bytes() == before


def test_raced_duplicate_resume_is_rejected_against_the_locked_corpus(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    _, handoff = append(capsys, tmp_path, task_id, "handoff_created", {
        "handoff_ref": "handoffs/task.md", "reason": "context_ceiling",
    })
    resume = {"handoff_ref": "handoffs/task.md", "resumed_from_handoff": True,
              "resumed_from_event_id": handoff["event_id"]}
    stale = records(tmp_path)
    assert append(capsys, tmp_path, task_id, "task_resumed", resume)[0] == 0
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._append_lifecycle_event(
            tmp_path, stale, telemetry._new_event(task_id, "task_resumed", resume)
        )
    assert caught.value.code == "TELEMETRY_LIFECYCLE_INVALID"
    assert path.read_bytes() == before


def test_cli_lifecycle_append_rejects_a_raced_interrupted_tail(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    stale = records(tmp_path)
    path = tmp_path / telemetry.EVENT_PATH
    with path.open("ab") as stream:
        stream.write(b'{"interrupted')
    before = path.read_bytes()
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._append_lifecycle_event(tmp_path, stale, finish_event(stale, task_id))
    assert caught.value.code == "TELEMETRY_HISTORY_CORRUPT"
    assert path.read_bytes() == before


def test_generic_writer_recovery_of_interrupted_tail_is_preserved(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    path = tmp_path / telemetry.EVENT_PATH
    complete = path.read_bytes()
    with path.open("ab") as stream:
        stream.write(b'{"interrupted')
    event = telemetry._new_event(task_id, "gate_result", {
        "gate_id": "gate:pytest", "outcome": "pass", "first_pass": True,
        "verdict_source": "automation", "evidence_ref": None,
    })
    stored = telemetry._cli_writer(tmp_path).append(event)
    raw = path.read_bytes()
    assert raw.startswith(complete) and b'{"interrupted' not in raw
    assert records(tmp_path)[-1]["event_id"] == stored["event_id"]


@pytest.mark.parametrize("event_type,payload_json", [
    pytest.param("handoff_created", "{}", id="handoff_created-empty-payload"),
    pytest.param("task_resumed", json.dumps({
        "handoff_ref": "handoffs/task.md", "resumed_from_handoff": True,
        "resumed_from_event_id": [],
    }), id="task_resumed-type-confused-event-id"),
    pytest.param("gate_result", '{"x":' + "[" * 20000 + "]" * 20000 + "}", id="gate_result-deep-recursion"),
])
def test_lifecycle_payload_failures_stay_structured_and_non_mutating(
    tmp_path, capsys, event_type, payload_json
):
    task_id = start(capsys, tmp_path)
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()
    code, result = invoke(capsys, tmp_path, "append", "--task-id", task_id,
                          "--event", event_type, "--payload-json", payload_json)
    assert code != 0 and result["status"] == "error"
    assert path.read_bytes() == before


def test_validate_reports_dangling_linklike_parent_as_corrupt_not_empty(tmp_path, capsys):
    try:
        (tmp_path / "telemetry").symlink_to("missing-target")
    except OSError:
        pytest.skip("symlink creation is unavailable")
    code, result = invoke(capsys, tmp_path, "validate")
    assert code != 0 and (result["status"], result["code"]) == ("error", "TELEMETRY_HISTORY_CORRUPT")


def test_validate_reports_truly_absent_parent_as_empty(tmp_path, capsys):
    code, result = invoke(capsys, tmp_path, "validate")
    assert (code, result["status"], result["event_count"]) == (0, "ok", 0)


# --- `resume` emit CLI -------------------------------------------------------
#
# The `resume` subcommand wraps the pure helper `build_resume_linkage` so an
# operator cannot hand-mis-build the `task_resumed` payload or drop lineage. The
# producer stays `planned` (the generic CLI is not a trusted LOAD/HARVEST
# context). The happy/delegated/disabled tests are red-anchored at the CLI; the
# error-path tests assert the exact `TelemetryError.detail` at the
# `_execute_command` seam, because `main` emits only the error `code` and the
# helper's `_error` shares `TELEMETRY_EVENT_INVALID` with the parser's
# unknown-subcommand rejection (so a code/exit assertion would pass vacuously).


def _resume_ns(root: Path, task_id: str) -> argparse.Namespace:
    return argparse.Namespace(
        command="resume", repository_root=str(root), task_id=task_id
    )


def test_resume_emits_linkage_correct_event_and_finishes_full(tmp_path, capsys):
    task_id = start(capsys, tmp_path, "build-loop")
    append(capsys, tmp_path, task_id, "gate_result", {
        "gate_id": "gate:pytest", "outcome": "pass", "first_pass": True,
        "verdict_source": "automation", "evidence_ref": None,
    })
    append(capsys, tmp_path, task_id, "review_result", {
        "reviewer_id": "reviewer:code", "reviewer_class": "software-dev", "round": 1,
        "verdict": "approve", "verdict_source": "agent", "finding_count": 0,
        "evidence_ref": None,
    })
    _, handoff = append(capsys, tmp_path, task_id, "handoff_created", {
        "handoff_ref": "handoffs/task.md", "reason": "deliberate_pause",
    })

    code, result = invoke(capsys, tmp_path, "resume", "--task-id", task_id)
    assert (code, result["status"], result["command"]) == (0, "ok", "resume")
    assert result["task_id"] == task_id

    resumed = records(tmp_path)[-1]
    assert resumed["event_type"] == "task_resumed"
    assert resumed["event_id"] == result["event_id"]
    assert resumed["payload"] == {
        "handoff_ref": "handoffs/task.md",
        "resumed_from_handoff": True,
        "resumed_from_event_id": handoff["event_id"],
    }

    invoke(capsys, tmp_path, "finish", "--task-id", task_id)
    assert records(tmp_path)[-1]["coverage"] == {
        "status": "full", "missing_event_types": [],
        "missing_requirement_refs": [], "reason": None,
    }


def test_resume_preserves_delegated_child_lineage(tmp_path, capsys):
    parent = start(capsys, tmp_path)
    child = str(uuid.uuid4())
    delegation = str(uuid.uuid4())
    append(capsys, tmp_path, parent, "delegation_started", {
        "delegation_id": delegation, "child_task_id": child,
        "delegated_role": "role:builder", "brief_ref": "handoffs/brief.md",
    })
    lineage = ("--parent-task-id", parent, "--delegation-id", delegation)
    append(capsys, tmp_path, child, "task_started", {"workflow": "other"}, *lineage)
    append(capsys, tmp_path, child, "handoff_created", {
        "handoff_ref": "handoffs/child.md", "reason": "deliberate_pause",
    }, *lineage)

    code, result = invoke(capsys, tmp_path, "resume", "--task-id", child)
    assert (code, result["status"]) == (0, "ok")
    resumed = records(tmp_path)[-1]
    assert resumed["event_type"] == "task_resumed" and resumed["task_id"] == child
    assert resumed["lineage"]["parent_task_id"] == parent
    assert resumed["lineage"]["delegation_id"] == delegation


def test_resume_is_disabled_by_kill_switch_without_mutation(tmp_path, capsys):
    code, result = invoke(capsys, tmp_path, "resume", "--task-id", str(uuid.uuid4()),
                          env={"DAT_KIT_TELEMETRY": "off"})
    assert (code, result["status"], result["command"]) == (0, "disabled", "resume")
    assert not (tmp_path / telemetry.EVENT_PATH).exists()


def test_resume_seam_no_unmatched_handoff_raises_exact_detail(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._execute_command(_resume_ns(tmp_path, task_id))
    assert caught.value.detail == "no unmatched handoff to resume"
    assert path.read_bytes() == before


def test_resume_seam_finished_task_raises_exact_detail(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    _, handoff = append(capsys, tmp_path, task_id, "handoff_created", {
        "handoff_ref": "handoffs/task.md", "reason": "deliberate_pause",
    })
    append(capsys, tmp_path, task_id, "task_resumed", {
        "handoff_ref": "handoffs/task.md", "resumed_from_handoff": True,
        "resumed_from_event_id": handoff["event_id"],
    })
    invoke(capsys, tmp_path, "finish", "--task-id", task_id)
    path = tmp_path / telemetry.EVENT_PATH
    before = path.read_bytes()
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._execute_command(_resume_ns(tmp_path, task_id))
    assert caught.value.detail == "cannot resume a finished task"
    assert path.read_bytes() == before


def test_resume_seam_unknown_task_raises_exact_detail(tmp_path, capsys):
    start(capsys, tmp_path)  # a seeded, unrelated task keeps the corpus non-empty
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._execute_command(_resume_ns(tmp_path, str(uuid.uuid4())))
    assert caught.value.detail == "resume target has no lifecycle events"


def test_resume_seam_non_uuid_task_id_is_rejected_without_echo(tmp_path, capsys):
    start(capsys, tmp_path)
    with pytest.raises(telemetry.TelemetryError) as caught:
        telemetry._execute_command(_resume_ns(tmp_path, "NOT-A-UUID"))
    assert caught.value.detail == "task_id must be a canonical lowercase UUIDv4"
    assert "NOT-A-UUID" not in caught.value.detail


def test_resume_does_not_create_producer_state(tmp_path, capsys):
    task_id = start(capsys, tmp_path)
    append(capsys, tmp_path, task_id, "handoff_created", {
        "handoff_ref": "handoffs/task.md", "reason": "deliberate_pause",
    })
    invoke(capsys, tmp_path, "resume", "--task-id", task_id)
    assert not (tmp_path / "telemetry" / "producers.json").exists()
