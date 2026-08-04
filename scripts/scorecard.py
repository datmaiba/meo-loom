#!/usr/bin/env python3
"""Append-only MeoLoom scorecard writer and report helper.

The scorecard skill supplies one schema-v2 record at task completion. This
module may attach Claude session totals to that *new* record when attribution
is unambiguous, then appends the record without rewriting scorecard history.
Report-time attribution is computed on an in-memory copy only.

Usage (from the project you want to report on):
    python3 /path/to/meo-loom/scripts/scorecard.py --provider claude
    python3 .../scorecard.py --provider claude --report-only
    python3 .../scorecard.py --provider claude --append-record record.json
    python3 .../scorecard.py --provider claude --append-record -  # JSON on stdin
    python3 .../scorecard.py --provider codex --append-record record.json
"""

import argparse
import copy
import json
import os
import pathlib
import re
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from contract_check import validate_scorecard


TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class _RedactingArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: invalid arguments\n")


def _configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def parse_ts(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def project_transcript_dir(projects_dir: pathlib.Path, cwd: str) -> pathlib.Path:
    return projects_dir / re.sub(r"[^A-Za-z0-9-]", "-", cwd)


def scan_sessions(tdir: pathlib.Path):
    """Yield (session_id, first_ts, last_ts, tokens_dict) per transcript.

    Claude transcript files are an internal format, so parsing is defensive:
    malformed lines are ignored and only known integer usage keys are summed.
    """
    for path in sorted(tdir.glob("*.jsonl")):
        first = last = None
        totals = dict.fromkeys(TOKEN_KEYS, 0)

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "usage" and isinstance(value, dict):
                        for token_key in TOKEN_KEYS:
                            if type(value.get(token_key)) is int and value[token_key] >= 0:
                                # Suppression reason: walk() is defined fresh each
                                # outer-loop iteration and only ever called within
                                # that same iteration (line below), so `totals` is
                                # never stale here despite closing over a loop var.
                                totals[token_key] += value[token_key]  # noqa: B023
                    else:
                        walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except (TypeError, ValueError):
                continue
            ts = parse_ts(obj.get("timestamp", "")) if isinstance(obj, dict) else None
            if ts:
                first = ts if first is None else min(first, ts)
                last = ts if last is None else max(last, ts)
            walk(obj)
        if any(totals.values()):
            yield path.stem, first, last, totals


def _normalized_ts(entry):
    ts = parse_ts(entry.get("ts", "") or "")
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _session_contains(session, ts):
    _, first, last, _ = session
    if not (ts and first and last):
        return False
    if first.tzinfo is None:
        first = first.replace(tzinfo=timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return first - timedelta(minutes=5) <= ts <= last + timedelta(hours=6)


def attribute_tokens(entry, existing_entries, sessions):
    """Return exact session totals or an explicit unknown-attribution reason."""
    ts = _normalized_ts(entry)
    if not ts:
        return None, "missing_timestamp"

    matches = [session for session in sessions if _session_contains(session, ts)]
    if not matches:
        return None, "no_matching_session"
    if len(matches) != 1:
        return None, "multiple_matching_sessions"

    session = matches[0]
    if any(_session_contains(session, _normalized_ts(other)) for other in existing_entries):
        return None, "ambiguous_multi_task_session"

    session_id, _, _, totals = session
    tokens = {**totals, "total": sum(totals.values()), "session": session_id[:8]}
    return tokens, "exact_session_total"


def _parse_entries(text, *, warn=True):
    entries = []
    for line_number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except (TypeError, ValueError):
            if warn:
                print(
                    f"warning: skipped malformed scorecard line {line_number}",
                    file=sys.stderr,
                )
            continue
        if not isinstance(entry, dict):
            if warn:
                print(
                    f"warning: skipped non-object scorecard line {line_number}",
                    file=sys.stderr,
                )
            continue
        entries.append(entry)
    return entries


def _is_link_or_reparse(path_stat):
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        reparse_flag and attributes & reparse_flag
    )


def _safe_parent_fingerprints(parent, *, create):
    """Inspect each parent component without resolving links or reparse points."""
    absolute = pathlib.Path(os.path.abspath(parent))
    current = pathlib.Path(absolute.anchor)
    fingerprints = []
    for part in absolute.parts[1:]:
        current /= part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            if not create:
                raise ValueError(f"scorecard parent does not exist: {current}") from None
            os.mkdir(current)
            current_stat = current.lstat()
        if _is_link_or_reparse(current_stat) or not stat.S_ISDIR(current_stat.st_mode):
            raise ValueError(f"unsafe scorecard parent path: {current}")
        fingerprints.append((current, current_stat))
    return absolute, tuple(fingerprints)


def _fingerprints_match(fingerprints):
    for component, expected in fingerprints:
        try:
            current = component.lstat()
        except OSError:
            return False
        if (
            _is_link_or_reparse(current)
            or not stat.S_ISDIR(current.st_mode)
            or not os.path.samestat(expected, current)
        ):
            return False
    return True


def _safe_target_stat(path):
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return None
    if (
        _is_link_or_reparse(path_stat)
        or not stat.S_ISREG(path_stat.st_mode)
        or path_stat.st_nlink != 1
    ):
        raise ValueError(f"unsafe scorecard target path: {path}")
    return path_stat


def _opened_target_is_safe(path, descriptor, parent_fingerprints, expected=None):
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
    except OSError:
        return False
    return bool(
        stat.S_ISREG(opened.st_mode)
        and opened.st_nlink == 1
        and not _is_link_or_reparse(current)
        and os.path.samestat(opened, current)
        and (expected is None or os.path.samestat(expected, opened))
        and _fingerprints_match(parent_fingerprints)
    )


def _open_scorecard(path, *, create):
    path = pathlib.Path(os.path.abspath(path))
    parent, parent_fingerprints = _safe_parent_fingerprints(path.parent, create=create)
    if path.parent != parent:
        raise ValueError("scorecard target escaped its inspected parent")

    for _attempt in range(2):
        expected = _safe_target_stat(path)
        if expected is None and not create:
            return None, parent_fingerprints
        flags = os.O_RDWR if create else os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        if create:
            flags |= os.O_APPEND
            if expected is None:
                flags |= os.O_CREAT | os.O_EXCL
        try:
            descriptor = os.open(path, flags, 0o644)
        except FileExistsError:
            if expected is None:
                continue
            raise
        if not _opened_target_is_safe(
            path,
            descriptor,
            parent_fingerprints,
            expected,
        ):
            os.close(descriptor)
            raise ValueError("scorecard path changed during no-follow open")
        return descriptor, parent_fingerprints
    raise RuntimeError("scorecard target changed during creation; retry")


def load_entries(path: pathlib.Path, *, warn=True):
    """Read valid records without normalizing history or following unsafe paths."""
    descriptor, _ = _open_scorecard(path, create=False)
    if descriptor is None:
        return []
    try:
        data = _read_locked_bytes(descriptor)
    finally:
        os.close(descriptor)
    return _parse_entries(data.decode("utf-8", errors="replace"), warn=warn)


@contextmanager
def _exclusive_file_lock(descriptor):
    """Serialize scorecard transactions on Windows and POSIX without a sidecar."""
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)


def _read_locked_bytes(descriptor):
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks = []
    while True:
        chunk = os.read(descriptor, 64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _prepare_new_record(entry, existing_entries, sessions, provider):
    record = copy.deepcopy(entry)
    if provider == "claude":
        tokens, reason = attribute_tokens(record, existing_entries, sessions)
    else:
        tokens, reason = None, "unsupported_provider"
    record["tokens"] = tokens
    record["token_attribution"] = {
        "status": "exact" if tokens is not None else "unknown",
        "reason": reason,
    }
    return record


def append_scorecard_record(path, entry, *, sessions=(), provider="claude"):
    """Validate and append exactly one record while preserving every prior byte."""
    path = pathlib.Path(os.path.abspath(path))
    descriptor, parent_fingerprints = _open_scorecard(path, create=True)
    try:
        with _exclusive_file_lock(descriptor):
            if not _opened_target_is_safe(path, descriptor, parent_fingerprints):
                raise ValueError("scorecard path changed before locked read")
            existing_bytes = _read_locked_bytes(descriptor)
            existing_entries = _parse_entries(
                existing_bytes.decode("utf-8", errors="replace")
            )
            if type(entry.get("schema_version")) is not int or entry["schema_version"] != 2:
                raise ValueError("new scorecard record must use schema_version 2")
            record = _prepare_new_record(
                entry,
                existing_entries,
                list(sessions),
                provider,
            )

            diagnostics = validate_scorecard([*existing_entries, record])
            if diagnostics:
                rendered = ", ".join(
                    f"{code} ({where})" for code, where in diagnostics
                )
                raise ValueError(f"invalid scorecard record: {rendered}")

            separator = "\n" if existing_bytes and not existing_bytes.endswith(b"\n") else ""
            payload = separator + json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
            ) + "\n"
            encoded = payload.encode("utf-8")
            original_size = len(existing_bytes)
            written = 0
            try:
                if not _opened_target_is_safe(path, descriptor, parent_fingerprints):
                    raise ValueError("scorecard path changed before append")
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise OSError(
                        f"short scorecard append: {written}/{len(encoded)} bytes"
                    )
                os.fsync(descriptor)
            except BaseException:
                current_size = os.fstat(descriptor).st_size
                if written and current_size == original_size + written:
                    os.ftruncate(descriptor, original_size)
                    os.fsync(descriptor)
                raise
    finally:
        os.close(descriptor)
    return record


def enrich_for_report(entries, sessions):
    """Return a report-only enriched copy; never persist these values."""
    enriched = copy.deepcopy(entries)
    for index, entry in enumerate(enriched):
        if entry.get("tokens") is not None:
            continue
        other_entries = [*entries[:index], *entries[index + 1 :]]
        tokens, reason = attribute_tokens(entry, other_entries, sessions)
        if tokens is not None:
            entry["tokens"] = tokens
            entry["token_attribution"] = {
                "status": "report_only",
                "reason": reason,
            }
    return enriched


def report(entries):
    if not entries:
        print("No scorecard entries yet — the scorecard skill writes benchmarks/scorecard.jsonl")
        return
    widths = (12, 34, 4, 7, 8, 10)
    print(
        f"{'date':<{widths[0]}} {'task':<{widths[1]}} {'cx':<{widths[2]}} "
        f"{'est.h':<{widths[3]}} {'wall.m':<{widths[4]}} {'tokens':<{widths[5]}}"
    )
    total_hours = total_minutes = total_tokens = complexity_sum = 0.0
    for entry in entries:
        token_data = entry.get("tokens") or {}
        tokens = token_data.get("total")
        token_label = str(tokens) if tokens is not None else "—"
        print(
            f"{entry.get('date', ''):<{widths[0]}} "
            f"{entry.get('task', '')[:widths[1]]:<{widths[1]}} "
            f"{entry.get('complexity', '?')!s:<{widths[2]}} "
            f"{entry.get('est_manual_hours', '?')!s:<{widths[3]}} "
            f"{entry.get('actual_wall_minutes', '?')!s:<{widths[4]}} "
            f"{token_label:<{widths[5]}}"
        )
        total_hours += float(entry.get("est_manual_hours") or 0)
        total_minutes += float(entry.get("actual_wall_minutes") or 0)
        total_tokens += tokens or 0
        complexity_sum += float(entry.get("complexity") or 0)
    count = len(entries)
    print("-" * 80)
    print(
        f"{count} tasks | complexity avg {complexity_sum / count:.1f} | "
        f"est. manual hours (ESTIMATE): {total_hours:.1f} | "
        f"actual: {total_minutes / 60:.1f}h | tokens: {int(total_tokens):,}"
    )
    if total_tokens and complexity_sum:
        print(
            f"tokens per complexity-point: {total_tokens / complexity_sum:,.0f} | "
            f"est. hours saved (ESTIMATE): {total_hours - total_minutes / 60:.1f}"
        )
    print(
        "Note: 'hours saved' compares an ESTIMATED manual baseline with real wall "
        "time — treat as directional, not exact."
    )


def _read_candidate(value):
    raw = sys.stdin.read() if value == "-" else pathlib.Path(value).read_text(encoding="utf-8")
    candidate = json.loads(raw)
    if not isinstance(candidate, dict):
        raise ValueError("append record must be one JSON object")
    return candidate


def main(argv=None):
    _configure_stdio()
    parser = _RedactingArgumentParser()
    parser.add_argument(
        "--provider",
        choices=("claude", "codex"),
        default="claude",
        help="transcript provider; Codex parsing is not implemented yet",
    )
    parser.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    parser.add_argument("--project", default=os.getcwd(), help="project to append/report")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument(
        "--append-record",
        metavar="JSON_FILE",
        help="append one schema-v2 record from a file, or '-' for stdin",
    )
    args = parser.parse_args(argv)

    if args.report_only and args.append_record:
        parser.error("--report-only and --append-record are mutually exclusive")

    scorecard_path = pathlib.Path(args.project) / "benchmarks" / "scorecard.jsonl"
    transcript_dir = project_transcript_dir(pathlib.Path(args.projects_dir), args.project)
    sessions = list(scan_sessions(transcript_dir)) if transcript_dir.is_dir() else []

    if args.append_record:
        try:
            candidate = _read_candidate(args.append_record)
            record = append_scorecard_record(
                scorecard_path,
                candidate,
                sessions=sessions,
                provider=args.provider,
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            parser.exit(2, f"scorecard append failed: {error}\n")
        reason = record["token_attribution"]["reason"]
        print(f"appended 1 scorecard record ({reason})\n")

    entries = load_entries(scorecard_path)
    if args.provider == "claude" and not args.report_only:
        entries = enrich_for_report(entries, sessions)
    elif args.provider == "codex" and not args.report_only and not args.append_record:
        print("(Codex transcript parsing is not verified; token attribution stays unknown.)\n")
    report(entries)


if __name__ == "__main__":
    main()
