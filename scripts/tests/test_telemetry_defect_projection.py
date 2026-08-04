"""B3 subset #2 — diagnosing-bugs defect projection (telemetry-v3 T3.10.2).

Covers the defect_recorded -> benchmarks/defects.jsonl projection: the closed
13-field record, idempotency by event_id, collision on tampered bytes, the
receipt-after-append ordering, first-append null prior_hash, path-safety on the
committed target, disabled behavior, rejected-value redaction, the consuming
validator's append-only correction chain, and the guarantee that projecting a
defect does NOT activate the producer (receipt producer.id stays dat-kit-cli).

Correction events cannot be minted through the CLI (they require the separate
correction channel + evidence resolver), so the correction-chain semantics are
exercised at the projection/parser layer, which is the durable artifact this
subset owns.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import telemetry


PROJECTION = telemetry.DEFECT_PROJECTION_PATH
TARGET = telemetry.DEFECT_PROJECTION_TARGET


def test_contract_target_is_posix_literal_not_os_path():
    # The receipt target_path and CLI --target are matched against the contract's
    # forward-slash enum; str(Path(...)) would use backslashes on Windows and
    # self-reject the benchmark_exported receipt.
    assert telemetry.DEFECT_PROJECTION_TARGET == "benchmarks/defects.jsonl"
    assert "\\" not in telemetry.DEFECT_PROJECTION_TARGET

EXPECTED_FIELDS = {
    "schema_version", "event_id", "task_id", "parent_task_id", "delegation_id",
    "correction_of", "correction_evidence_ref", "occurred_at", "defect_id",
    "introduced_task", "approving_reviewers", "gate_that_should_have_caught_it",
    "evidence_ref",
}


def invoke(capsys, root: Path, *args: str, env=None):
    code = telemetry.main(
        ["--repository-root", str(root), *args],
        environ={} if env is None else env,
    )
    captured = capsys.readouterr()
    stream = captured.out if captured.out else captured.err
    return code, json.loads(stream)


def start(capsys, root: Path, workflow="other") -> str:
    code, result = invoke(capsys, root, "start", "--workflow", workflow)
    assert code == 0 and result["status"] == "ok"
    return result["task_id"]


def append_defect(capsys, root: Path, task_id: str, defect_id: str) -> tuple[int, dict]:
    payload = {
        "defect_id": defect_id,
        "introduced_task": None,
        "approving_reviewers": ["reviewer:code"],
        "gate_that_should_have_caught_it": "gate:pytest",
        "evidence_ref": f"evidence:{defect_id}",
    }
    return invoke(
        capsys, root, "append",
        "--task-id", task_id,
        "--event", "defect_recorded",
        "--payload-json", json.dumps(payload, separators=(",", ":")),
    )


def export(capsys, root: Path, task_id: str, target: str = TARGET, env=None):
    return invoke(capsys, root, "export", "--task-id", task_id, "--target", target, env=env)


def projection_lines(root: Path) -> list[dict]:
    raw = (root / PROJECTION).read_bytes()
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def stream_events(root: Path) -> list[dict]:
    return telemetry.validate_lifecycle_events(root)


def defect_event(root: Path) -> dict:
    return next(e for e in stream_events(root) if e["event_type"] == "defect_recorded")


# --- happy path -----------------------------------------------------------

def test_export_writes_closed_13_field_record_matching_source(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    code, result = export(capsys, tmp_path, task)
    assert code == 0 and result["status"] == "ok" and result["no_op"] is False

    lines = projection_lines(tmp_path)
    assert len(lines) == 1
    record = lines[0]
    assert set(record) == EXPECTED_FIELDS  # exactly 13, none missing, none extra

    source = defect_event(tmp_path)
    assert record["schema_version"] == 3
    assert record["event_id"] == source["event_id"]
    assert record["task_id"] == source["task_id"]
    assert record["defect_id"] == "defect:alpha"
    assert record["evidence_ref"] == "evidence:defect:alpha"
    assert record["gate_that_should_have_caught_it"] == "gate:pytest"
    assert record["approving_reviewers"] == ["reviewer:code"]
    assert record["correction_of"] is None and record["correction_evidence_ref"] is None


def test_first_append_receipt_has_null_prior_hash_and_stays_dat_kit_cli(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    code, result = export(capsys, tmp_path, task)
    assert code == 0

    receipt = next(e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported")
    assert receipt["payload"]["prior_hash"] is None          # first append into empty file
    assert receipt["payload"]["target_path"] == TARGET
    assert receipt["payload"]["exported_event_ids"] == [defect_event(tmp_path)["event_id"]]
    # No activation-authority creep: the receipt is the generic CLI producer,
    # never the diagnosing-bugs producer identity.
    assert receipt["producer"]["id"] == "dat-kit-cli"


# --- idempotency & collision ---------------------------------------------

def test_second_export_is_noop_with_no_new_bytes_and_no_new_receipt(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    export(capsys, tmp_path, task)
    before = (tmp_path / PROJECTION).read_bytes()
    receipts_before = [e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported"]

    code, result = export(capsys, tmp_path, task)
    assert code == 0 and result["no_op"] is True and result["exported_event_ids"] == []
    assert (tmp_path / PROJECTION).read_bytes() == before
    receipts_after = [e for e in stream_events(tmp_path) if e["event_type"] == "benchmark_exported"]
    assert len(receipts_after) == len(receipts_before)  # no-op emits no receipt


def test_same_event_id_different_bytes_fails_collision(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    export(capsys, tmp_path, task)

    # Tamper: keep the event_id, change a payload-derived field so the source
    # event would now produce different canonical bytes than what is stored.
    record = projection_lines(tmp_path)[0]
    record["defect_id"] = "defect:tampered"
    (tmp_path / PROJECTION).write_bytes(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    )
    before = (tmp_path / PROJECTION).read_bytes()

    code, result = export(capsys, tmp_path, task)
    assert code == 2 and result["code"] == "TELEMETRY_EXPORT_COLLISION"
    assert (tmp_path / PROJECTION).read_bytes() == before  # no mutation on collision


# --- receipt ordering (receipt only after durable append) ----------------

def test_receipt_not_emitted_when_durable_append_fails(tmp_path, capsys, monkeypatch):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")

    def boom(*_args, **_kwargs):
        raise OSError("append failed")

    monkeypatch.setattr(telemetry.os, "write", boom)
    with pytest.raises(OSError):
        telemetry.export_defect_projection(tmp_path, task, target_path=TARGET)

    # Durable append never completed -> no receipt in the stream.
    assert not any(e["event_type"] == "benchmark_exported" for e in stream_events(tmp_path))


# --- path safety on the committed target ---------------------------------

def test_symlinked_target_fails_closed(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    (tmp_path / "benchmarks").mkdir(exist_ok=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    link = tmp_path / PROJECTION
    if link.exists():
        link.unlink()
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.export_defect_projection(tmp_path, task, target_path=TARGET)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"


# --- disabled -------------------------------------------------------------

def test_disabled_export_writes_nothing(tmp_path, capsys):
    task = start(capsys, tmp_path)
    append_defect(capsys, tmp_path, task, "defect:alpha")
    code, result = export(capsys, tmp_path, task, env={"DAT_KIT_TELEMETRY": "off"})
    assert code == 0 and result["status"] == "disabled"
    assert not (tmp_path / PROJECTION).exists()
    assert not any(e["event_type"] == "benchmark_exported" for e in stream_events(tmp_path))


# --- rejected-value redaction --------------------------------------------

def test_rejected_target_value_is_not_echoed(tmp_path, capsys):
    task = start(capsys, tmp_path)
    secret = "benchmarks/should-not-appear.jsonl"
    code, result = invoke(capsys, tmp_path, "export", "--task-id", task, "--target", secret)
    assert code == 2
    assert secret not in json.dumps(result)


def test_rejected_target_flag_equals_form_is_not_echoed(tmp_path, capsys):
    task = start(capsys, tmp_path)
    secret = "benchmarks/should-not-appear.jsonl"
    code, result = invoke(capsys, tmp_path, "export", "--task-id", task, f"--target={secret}")
    assert code == 2
    assert secret not in json.dumps(result)


# --- consuming validator: closed shape + append-only correction chain -----

def _record(**overrides) -> dict:
    base = {
        "schema_version": 3,
        "event_id": "11111111-1111-4111-8111-111111111111",
        "task_id": "22222222-2222-4222-8222-222222222222",
        "parent_task_id": None,
        "delegation_id": None,
        "correction_of": None,
        "correction_evidence_ref": None,
        "occurred_at": "2026-07-23T00:00:00.000Z",
        "defect_id": "defect:alpha",
        "introduced_task": None,
        "approving_reviewers": ["reviewer:code"],
        "gate_that_should_have_caught_it": "gate:pytest",
        "evidence_ref": "evidence:alpha",
    }
    base.update(overrides)
    return base


def _write_projection(root: Path, records: list[dict]) -> None:
    (root / "benchmarks").mkdir(exist_ok=True)
    blob = "".join(
        json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records
    )
    (root / PROJECTION).write_bytes(blob.encode("utf-8"))


def test_validator_accepts_a_valid_correction_chain(tmp_path):
    original = _record()
    correction = _record(
        event_id="33333333-3333-4333-8333-333333333333",
        correction_of=original["event_id"],
        correction_evidence_ref="correction:alpha",
        defect_id="defect:alpha-fixed",
    )
    _write_projection(tmp_path, [original, correction])
    records = telemetry.validate_defect_projection(tmp_path)
    assert [r["event_id"] for r in records] == [original["event_id"], correction["event_id"]]


def test_validator_rejects_correction_without_earlier_target(tmp_path):
    orphan = _record(
        event_id="33333333-3333-4333-8333-333333333333",
        correction_of="99999999-9999-4999-8999-999999999999",
        correction_evidence_ref="correction:orphan",
    )
    _write_projection(tmp_path, [orphan])
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.validate_defect_projection(tmp_path)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"


def test_validator_rejects_duplicate_event_id(tmp_path):
    _write_projection(tmp_path, [_record(), _record()])
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.validate_defect_projection(tmp_path)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"


def test_validator_rejects_extra_field(tmp_path):
    _write_projection(tmp_path, [{**_record(), "unexpected": True}])
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.validate_defect_projection(tmp_path)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"


def test_validator_rejects_wrong_schema_version(tmp_path):
    _write_projection(tmp_path, [_record(schema_version=2)])
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.validate_defect_projection(tmp_path)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"


def test_validator_rejects_interrupted_trailing_record(tmp_path):
    (tmp_path / "benchmarks").mkdir(exist_ok=True)
    good = json.dumps(_record(), sort_keys=True, separators=(",", ":")) + "\n"
    (tmp_path / PROJECTION).write_bytes((good + '{"partial":').encode("utf-8"))
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.validate_defect_projection(tmp_path)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"
