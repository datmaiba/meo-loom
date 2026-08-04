import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import scorecard
RETIRED_AUTHORITY_FLAGS = (
    "--telemetry-task-id",
    "--root-cause-locus",
    "--root-cause-ref",
    "--lesson-candidate-ref",
)


def record(ts="2026-07-17T10:30:00+07:00", task="new task"):
    return {
        "schema_version": 2,
        "ts": ts,
        "date": "2026-07-17",
        "task": task,
        "complexity": 2,
        "notes": "focused append-only maintenance test",
        "est_manual_hours": 1,
        "actual_wall_minutes": 10,
        "gates": "pytest",
        "tokens": None,
        "model": "test",
        "agent_runtime": "codex",
        "workflow": "build-loop",
        "canonical_contract_revision": "dat-kit 1.16.0",
        "git_state": {"branch": "test", "head": "abc", "dirty": True},
    }


def session(name="session-123456", first="2026-07-17T10:00:00+07:00", last="2026-07-17T11:00:00+07:00"):
    return (
        name,
        datetime.fromisoformat(first),
        datetime.fromisoformat(last),
        {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 7,
        },
    )


def run_scorecard_cli(tmp_path, *extra_args):
    candidate = tmp_path / "record.json"
    candidate.write_text(json.dumps(record()), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "scorecard.py"),
            "--provider",
            "codex",
            "--project",
            str(tmp_path),
            "--append-record",
            str(candidate),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_exact_attribution_appends_only_new_record(tmp_path):
    path = tmp_path / "benchmarks" / "scorecard.jsonl"
    path.parent.mkdir()
    prefix = b'{"ts":"2026-01-01T00:00:00+00:00","task":"legacy"}\n'
    path.write_bytes(prefix)
    prefix_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    appended = scorecard.append_scorecard_record(path, record(), sessions=[session()])

    contents = path.read_bytes()
    assert contents.startswith(prefix)
    assert hashlib.sha256(contents[: len(prefix)]).hexdigest() == prefix_hash
    stored = json.loads(contents.splitlines()[-1])
    assert stored == appended
    assert stored["tokens"]["total"] == 130
    assert stored["token_attribution"] == {
        "status": "exact",
        "reason": "exact_session_total",
    }


def test_ambiguous_multi_task_session_keeps_tokens_unknown(tmp_path):
    path = tmp_path / "scorecard.jsonl"
    path.write_text(json.dumps(record(task="prior task")) + "\n", encoding="utf-8")

    appended = scorecard.append_scorecard_record(path, record(task="second task"), sessions=[session()])

    assert appended["tokens"] is None
    assert appended["token_attribution"]["reason"] == "ambiguous_multi_task_session"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["tokens"] is None
    assert len(lines) == 2


def test_multiple_matching_sessions_keeps_tokens_unknown(tmp_path):
    path = tmp_path / "scorecard.jsonl"

    appended = scorecard.append_scorecard_record(
        path,
        record(),
        sessions=[session("one"), session("two")],
    )

    assert appended["tokens"] is None
    assert appended["token_attribution"]["reason"] == "multiple_matching_sessions"


def test_malformed_unterminated_tail_is_preserved_before_append(tmp_path, capsys):
    path = tmp_path / "scorecard.jsonl"
    prefix = b'{"malformed":'
    path.write_bytes(prefix)

    scorecard.append_scorecard_record(path, record(), sessions=[session()])

    contents = path.read_bytes()
    assert contents.startswith(prefix + b"\n")
    assert json.loads(contents.splitlines()[-1])["tokens"]["total"] == 130
    assert "skipped malformed scorecard line 1" in capsys.readouterr().err


def test_append_failure_never_changes_existing_bytes(tmp_path, monkeypatch):
    path = tmp_path / "scorecard.jsonl"
    prefix = (json.dumps(record(task="prior")) + "\n").encode()
    path.write_bytes(prefix)

    def fail_write(_descriptor, _payload):
        raise OSError("injected concurrent append failure")

    monkeypatch.setattr(os, "write", fail_write)
    with pytest.raises(OSError, match="injected concurrent append failure"):
        scorecard.append_scorecard_record(path, record(task="new"), provider="codex")

    assert path.read_bytes() == prefix


def test_positive_short_write_is_rolled_back_under_lock(tmp_path, monkeypatch):
    path = tmp_path / "scorecard.jsonl"
    prefix = (json.dumps(record(task="prior")) + "\n").encode()
    path.write_bytes(prefix)
    real_write = os.write

    def partial_write(descriptor, payload):
        partial = payload[: max(1, len(payload) // 2)]
        real_write(descriptor, partial)
        return len(partial)

    monkeypatch.setattr(os, "write", partial_write)
    with pytest.raises(OSError, match="short scorecard append"):
        scorecard.append_scorecard_record(path, record(task="new"), provider="codex")

    assert path.read_bytes() == prefix


def test_two_writers_are_serialized_before_read_attribution_append(tmp_path, monkeypatch):
    path = tmp_path / "scorecard.jsonl"
    first_inside = threading.Event()
    release_first = threading.Event()
    calls_lock = threading.Lock()
    parse_calls = 0
    errors = []
    real_parse = scorecard._parse_entries

    def blocking_first_parse(text, *, warn=True):
        nonlocal parse_calls
        with calls_lock:
            parse_calls += 1
            call_number = parse_calls
        if call_number == 1:
            first_inside.set()
            assert release_first.wait(5), "test did not release first writer"
        return real_parse(text, warn=warn)

    def append(task):
        try:
            scorecard.append_scorecard_record(
                path,
                record(task=task),
                sessions=[session()],
            )
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(scorecard, "_parse_entries", blocking_first_parse)
    first = threading.Thread(target=append, args=("first",))
    second = threading.Thread(target=append, args=("second",))
    first.start()
    assert first_inside.wait(5)
    second.start()
    time.sleep(0.2)
    with calls_lock:
        assert parse_calls == 1, "second writer crossed the exclusive lock"
    release_first.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    stored = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    reasons = [entry["token_attribution"]["reason"] for entry in stored]
    assert reasons == ["exact_session_total", "ambiguous_multi_task_session"]


def test_report_enrichment_is_in_memory_only(tmp_path):
    path = tmp_path / "scorecard.jsonl"
    path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    before = path.read_bytes()
    entries = scorecard.load_entries(path)

    enriched = scorecard.enrich_for_report(entries, [session()])

    assert entries[0]["tokens"] is None
    assert enriched[0]["tokens"]["total"] == 130
    assert enriched[0]["token_attribution"]["status"] == "report_only"
    assert path.read_bytes() == before


def test_codex_cli_appends_compatible_unknown_attribution(tmp_path):
    result = run_scorecard_cli(tmp_path)

    assert result.returncode == 0, result.stderr
    stored = json.loads((tmp_path / "benchmarks" / "scorecard.jsonl").read_text(encoding="utf-8"))
    assert stored["tokens"] is None
    assert stored["token_attribution"] == {
        "status": "unknown",
        "reason": "unsupported_provider",
    }
    assert not (tmp_path / "telemetry" / "events.jsonl").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        [flag, "secret-canary-value"]
        for flag in RETIRED_AUTHORITY_FLAGS
    ]
    + [
        [f"{flag}=secret-canary-value"]
        for flag in RETIRED_AUTHORITY_FLAGS
    ],
)
def test_cli_rejects_removed_telemetry_authority_flags_without_mutation(
    tmp_path,
    arguments,
):
    result = run_scorecard_cli(tmp_path, *arguments)

    assert result.returncode == 2
    assert "invalid arguments" in result.stderr
    assert "secret-canary-value" not in result.stdout
    assert "secret-canary-value" not in result.stderr
    assert not (tmp_path / "benchmarks" / "scorecard.jsonl").exists()
    assert not (tmp_path / "telemetry" / "events.jsonl").exists()


def test_existing_v117_reader_ignores_new_attribution_field(capsys):
    entry = copy.deepcopy(record())
    entry["token_attribution"] = {"status": "unknown", "reason": "unsupported_provider"}

    scorecard.report([entry])

    assert "new task" in capsys.readouterr().out


@pytest.mark.parametrize("schema_version", [None, 1, 999, "2"])
def test_append_rejects_non_v2_new_records_without_changing_history(
    tmp_path,
    schema_version,
):
    path = tmp_path / "scorecard.jsonl"
    prefix = b'{"ts":"2026-01-01T00:00:00+00:00","task":"legacy"}\n'
    path.write_bytes(prefix)
    candidate = record()
    if schema_version is None:
        candidate.pop("schema_version")
    else:
        candidate["schema_version"] = schema_version

    with pytest.raises(ValueError, match="must use schema_version 2"):
        scorecard.append_scorecard_record(path, candidate, sessions=[session()])

    assert path.read_bytes() == prefix


def test_append_rejects_scorecard_file_symlink_without_touching_target(tmp_path):
    project = tmp_path / "project"
    benchmarks = project / "benchmarks"
    benchmarks.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"OUTSIDE\n")
    link = benchmarks / "scorecard.jsonl"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("file symlinks unavailable")

    with pytest.raises((OSError, ValueError), match="scorecard"):
        scorecard.append_scorecard_record(link, record(), provider="codex")

    assert outside.read_bytes() == b"OUTSIDE\n"


def test_append_rejects_parent_symlink_without_creating_outside_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    parent_link = project / "benchmarks"
    try:
        parent_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")

    with pytest.raises(ValueError, match="unsafe scorecard parent"):
        scorecard.append_scorecard_record(
            parent_link / "scorecard.jsonl",
            record(),
            provider="codex",
        )

    assert not (outside / "scorecard.jsonl").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior")
def test_append_rejects_windows_parent_junction(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = project / "benchmarks"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        pytest.skip("junction creation unavailable")
    try:
        with pytest.raises(ValueError, match="unsafe scorecard parent"):
            scorecard.append_scorecard_record(
                junction / "scorecard.jsonl",
                record(),
                provider="codex",
            )
        assert not (outside / "scorecard.jsonl").exists()
    finally:
        junction.rmdir()


def test_append_rejects_hardlinked_target_without_touching_peer(tmp_path):
    project = tmp_path / "project"
    benchmarks = project / "benchmarks"
    benchmarks.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"OUTSIDE\n")
    target = benchmarks / "scorecard.jsonl"
    try:
        os.link(outside, target)
    except OSError:
        pytest.skip("hard links unavailable")

    with pytest.raises(ValueError, match="unsafe scorecard target"):
        scorecard.append_scorecard_record(target, record(), provider="codex")

    assert outside.read_bytes() == b"OUTSIDE\n"


def test_target_swap_between_open_and_locked_read_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "benchmarks" / "scorecard.jsonl"
    path.parent.mkdir()
    prefix = (json.dumps(record(task="prior")) + "\n").encode()
    path.write_bytes(prefix)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"OUTSIDE\n")
    real_lstat = Path.lstat
    target_calls = 0

    def swapped_lstat(self):
        nonlocal target_calls
        if self == path:
            target_calls += 1
            if target_calls == 3:
                return real_lstat(outside)
        return real_lstat(self)

    monkeypatch.setattr(Path, "lstat", swapped_lstat)
    with pytest.raises(ValueError, match="changed before locked read"):
        scorecard.append_scorecard_record(path, record(task="new"), provider="codex")

    assert path.read_bytes() == prefix
    assert outside.read_bytes() == b"OUTSIDE\n"


def test_transcript_scan_rejects_bool_negative_usage_and_orders_timestamps(tmp_path):
    transcript = tmp_path / "session-123456.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-17T11:00:00+07:00",
                        "usage": {"input_tokens": True, "output_tokens": -5},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-17T10:00:00+07:00",
                        "usage": {"input_tokens": 100, "output_tokens": 20},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sessions = list(scorecard.scan_sessions(tmp_path))

    assert len(sessions) == 1
    _, first, last, totals = sessions[0]
    assert first == datetime.fromisoformat("2026-07-17T10:00:00+07:00")
    assert last == datetime.fromisoformat("2026-07-17T11:00:00+07:00")
    assert totals["input_tokens"] == 100
    assert totals["output_tokens"] == 20
