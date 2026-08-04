"""B4 — general event export to benchmarks/telemetry-v3.jsonl (telemetry-v3 T3.10.2).

Covers the general export that copies the COMPLETE eligible validated event to the
committed, append-only benchmarks/telemetry-v3.jsonl: eligibility (local_private
and benchmark_exported excluded, everything else retained), idempotency by
event_id, collision on tampered bytes, the receipt-after-append ordering and
prior_hash, the "ALSO" clause (a defect_recorded lands full here AND as a 13-field
projection in defects.jsonl), CLI routing through the existing `export` subcommand,
disabled behavior, rejected-value redaction, and append-only integrity. The export
emits benchmark_exported but activates NO producer (receipt producer.id stays the
generic dat-kit-cli).

Written observed-red-before-green per docs/agent-working-rules.md: run against
telemetry.py BEFORE export_event_corpus / _export_eligible / the CLI --target
extension exist to confirm the AttributeError and the CLI reject, then implement.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import telemetry


GENERAL = telemetry.GENERAL_EXPORT_PATH
GENERAL_TARGET = telemetry.GENERAL_EXPORT_TARGET
DEFECT = telemetry.DEFECT_PROJECTION_PATH
DEFECT_TARGET = telemetry.DEFECT_PROJECTION_TARGET


# --- CLI harness (drives the real `export` subcommand end-to-end) -------------

def invoke(capsys, root: Path, *args: str, env=None):
    code = telemetry.main(["--repository-root", str(root), *args], environ={} if env is None else env)
    captured = capsys.readouterr()
    stream = captured.out if captured.out else captured.err
    return code, json.loads(stream)


def start(capsys, root: Path, workflow="other") -> str:
    code, result = invoke(capsys, root, "start", "--workflow", workflow)
    assert code == 0 and result["status"] == "ok"
    return result["task_id"]


def append_defect(capsys, root: Path, task_id: str, defect_id: str):
    payload = {
        "defect_id": defect_id,
        "introduced_task": None,
        "approving_reviewers": ["reviewer:code"],
        "gate_that_should_have_caught_it": "gate:pytest",
        "evidence_ref": f"evidence:{defect_id}",
    }
    return invoke(capsys, root, "append", "--task-id", task_id, "--event", "defect_recorded",
                  "--payload-json", json.dumps(payload, separators=(",", ":")))


def finish(capsys, root: Path, task_id: str):
    return invoke(capsys, root, "finish", "--task-id", task_id)


def export(capsys, root: Path, task_id: str, target: str = GENERAL_TARGET, env=None):
    return invoke(capsys, root, "export", "--task-id", task_id, "--target", target, env=env)


def general_lines(root: Path) -> list[dict]:
    raw = (root / GENERAL).read_bytes()
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def stream_events(root: Path) -> list[dict]:
    return telemetry.validate_lifecycle_events(root)


# --- constant hygiene ---------------------------------------------------------

def test_general_target_is_posix_literal_not_os_path():
    assert telemetry.GENERAL_EXPORT_TARGET == "benchmarks/telemetry-v3.jsonl"
    assert "\\" not in telemetry.GENERAL_EXPORT_TARGET


# --- eligibility filter (pure helper) ----------------------------------------

def _ev(event_type, privacy_class, event_id):
    return {"event_type": event_type, "privacy_class": privacy_class, "event_id": event_id}


def test_eligible_excludes_local_private():
    events = [_ev("task_started", "project", "a"), _ev("gate_result", "local_private", "b")]
    kept = telemetry._export_eligible(events)
    assert [e["event_id"] for e in kept] == ["a"]  # local_private excluded (T3.9 L445)


def test_eligible_excludes_benchmark_exported_receipt():
    events = [_ev("task_started", "project", "a"), _ev("benchmark_exported", "project", "r")]
    kept = telemetry._export_eligible(events)
    assert [e["event_id"] for e in kept] == ["a"]  # receipts never export-eligible (T3.10.2 L545)


def test_eligible_retains_public_project_defect_and_corrections():
    events = [
        _ev("task_started", "public", "a"),
        _ev("defect_recorded", "project", "b"),
        _ev("task_finished", "project", "c"),
    ]
    kept = telemetry._export_eligible(events)
    assert [e["event_id"] for e in kept] == ["a", "b", "c"]


# --- happy path: copy complete eligible events -------------------------------

def test_export_copies_complete_eligible_events_byte_exact(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")

    code, result = export(capsys, tmp_path, task)
    assert code == 0 and result["status"] == "ok" and result["no_op"] is False

    exported = general_lines(tmp_path)
    source = [e for e in stream_events(tmp_path) if e["event_type"] != "benchmark_exported"]
    # Every eligible non-receipt event is present as a full envelope, byte-exact.
    assert {e["event_id"] for e in exported} == {e["event_id"] for e in source}
    for record in exported:
        src = next(e for e in source if e["event_id"] == record["event_id"])
        assert telemetry._encode_validated_event(record) == telemetry._encode_validated_event(src)


def test_finished_task_events_are_copied_via_open_exporter(tmp_path, capsys):
    # A finished task's events are eligible; the export receipt is owned by a
    # separate still-open task (a receipt cannot append after its own finish).
    data = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, data, "defect:alpha")
    finish(capsys, tmp_path, data)
    exporter = start(capsys, tmp_path)

    code, result = export(capsys, tmp_path, exporter)
    assert code == 0 and result["no_op"] is False
    exported_ids = {r["event_id"] for r in general_lines(tmp_path)}
    data_finished = next(e for e in stream_events(tmp_path)
                         if e["event_type"] == "task_finished" and e["task_id"] == data)
    assert data_finished["event_id"] in exported_ids  # terminal event copied whole


def test_also_clause_defect_full_here_and_projected_in_defects(tmp_path, capsys):
    # Contract L509-511: a defect_recorded is copied FULL to telemetry-v3.jsonl AND
    # additionally projected (13 fields) to defects.jsonl.
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")

    export(capsys, tmp_path, task, target=GENERAL_TARGET)
    export(capsys, tmp_path, task, target=DEFECT_TARGET)

    defect_src = next(e for e in stream_events(tmp_path) if e["event_type"] == "defect_recorded")
    general = next(r for r in general_lines(tmp_path) if r["event_id"] == defect_src["event_id"])
    assert set(general) == telemetry.TOP_LEVEL_FIELDS  # full envelope
    projection = [json.loads(x) for x in (tmp_path / DEFECT).read_bytes().splitlines() if x.strip()]
    assert any(r["event_id"] == defect_src["event_id"] and "defect_id" in r and "coverage" not in r
               for r in projection)  # 13-field projection, not the envelope


# --- receipt correctness ------------------------------------------------------

def test_first_receipt_null_prior_hash_target_and_ids(tmp_path, capsys):
    task = start(capsys, tmp_path)
    export(capsys, tmp_path, task)

    receipt = next(e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported")
    assert receipt["payload"]["prior_hash"] is None
    assert receipt["payload"]["target_path"] == GENERAL_TARGET
    eligible_ids = sorted(e["event_id"] for e in stream_events(tmp_path)
                          if e["event_type"] not in ("benchmark_exported",))
    assert receipt["payload"]["exported_event_ids"] == eligible_ids
    assert receipt["producer"]["id"] == "dat-kit-cli"  # no producer activation


# --- idempotency & collision --------------------------------------------------

def test_second_export_noop_no_new_bytes_no_new_receipt(tmp_path, capsys):
    task = start(capsys, tmp_path)
    export(capsys, tmp_path, task)
    before = (tmp_path / GENERAL).read_bytes()
    receipts_before = [e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported"]

    code, result = export(capsys, tmp_path, task)
    assert code == 0 and result["no_op"] is True and result["exported_event_ids"] == []
    assert (tmp_path / GENERAL).read_bytes() == before
    receipts_after = [e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported"]
    assert len(receipts_after) == len(receipts_before)


def test_same_event_id_different_bytes_fails_collision(tmp_path, capsys):
    task = start(capsys, tmp_path)
    export(capsys, tmp_path, task)

    record = general_lines(tmp_path)[0]
    record["source_class"] = "derived" if record["source_class"] != "derived" else "runtime"
    (tmp_path / GENERAL).write_bytes(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    before = (tmp_path / GENERAL).read_bytes()

    code, result = export(capsys, tmp_path, task)
    assert code == 2 and result["code"] == "TELEMETRY_EXPORT_COLLISION"
    assert (tmp_path / GENERAL).read_bytes() == before  # no mutation on collision


def test_benchmark_exported_receipt_never_copied(tmp_path, capsys):
    # A prior defect-export receipt is in the stream; the general export must not copy it.
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    export(capsys, tmp_path, task, target=DEFECT_TARGET)  # emits a benchmark_exported receipt
    receipt = next(e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported")

    export(capsys, tmp_path, task, target=GENERAL_TARGET)
    assert receipt["event_id"] not in {r["event_id"] for r in general_lines(tmp_path)}


# --- receipt only after durable append ---------------------------------------

def test_receipt_not_emitted_when_durable_append_fails(tmp_path, capsys, monkeypatch):
    task = start(capsys, tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError("append failed")

    monkeypatch.setattr(telemetry.os, "write", boom)
    with pytest.raises(OSError):
        telemetry.export_event_corpus(tmp_path, task, target_path=GENERAL_TARGET)
    assert not any(e["event_type"] == "benchmark_exported" for e in stream_events(tmp_path))


# --- disabled + redaction -----------------------------------------------------

def test_disabled_export_writes_nothing(tmp_path, capsys):
    task = start(capsys, tmp_path)
    code, result = export(capsys, tmp_path, task, env={"DAT_KIT_TELEMETRY": "off"})
    assert code == 0 and result["status"] == "disabled"
    assert not (tmp_path / GENERAL).exists()  # nothing created or appended when disabled
    assert not any(e["event_type"] == "benchmark_exported" for e in stream_events(tmp_path))


def test_rejected_target_value_is_not_echoed(tmp_path, capsys):
    task = start(capsys, tmp_path)
    secret = "benchmarks/should-not-appear.jsonl"
    code, result = invoke(capsys, tmp_path, "export", "--task-id", task, "--target", secret)
    assert code == 2
    assert secret not in json.dumps(result)


def test_cli_routes_both_targets(tmp_path, capsys):
    # --target telemetry-v3.jsonl routes to the general export; defects.jsonl still works.
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    code_g, _ = export(capsys, tmp_path, task, target=GENERAL_TARGET)
    code_d, _ = export(capsys, tmp_path, task, target=DEFECT_TARGET)
    assert code_g == 0 and code_d == 0
    assert (tmp_path / GENERAL).read_bytes() != b""
    assert (tmp_path / DEFECT).read_bytes() != b""
