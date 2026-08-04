"""Tests for scripts/review_summary.py — R1 slice of the receipt-gate plan.

Covers the negative/edge cases a producer-only script must get right: missing
inputs marked not_run (not silently dropped), malformed XML detected instead
of crashing, correct pass/fail counting, and the required-gate-set exit code.
Written observed-red-before-green per docs/agent-working-rules.md: run these
against review_summary.py with a deliberately broken junit parser first to
confirm they fail, then restore.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import review_summary as rs  # noqa: E402


JUNIT_PASS = """<?xml version="1.0"?>
<testsuite name="pytest" tests="10" failures="0" errors="0" skipped="1"></testsuite>
"""

JUNIT_FAIL = """<?xml version="1.0"?>
<testsuite name="pytest" tests="10" failures="2" errors="0" skipped="0"></testsuite>
"""

JUNIT_MALFORMED = "<testsuite this is not valid xml"


def test_junit_counts_missing_file_is_not_run(tmp_path):
    result = rs._junit_counts(str(tmp_path / "nope.xml"))
    assert result["outcome"] == "not_run"
    assert result["collected"] is None


def test_junit_counts_pass(tmp_path):
    p = tmp_path / "junit.xml"
    p.write_text(JUNIT_PASS, encoding="utf-8")
    result = rs._junit_counts(str(p))
    assert result == {"outcome": "pass", "collected": 10, "passed": 9, "failed": 0, "skipped": 1}


def test_junit_counts_fail(tmp_path):
    p = tmp_path / "junit.xml"
    p.write_text(JUNIT_FAIL, encoding="utf-8")
    result = rs._junit_counts(str(p))
    assert result["outcome"] == "fail"
    assert result["failed"] == 2
    assert result["passed"] == 8


def test_junit_counts_malformed_does_not_raise(tmp_path):
    p = tmp_path / "junit.xml"
    p.write_text(JUNIT_MALFORMED, encoding="utf-8")
    result = rs._junit_counts(str(p))
    assert result["outcome"] == "malformed"


def test_ruff_findings_counts_list_length(tmp_path):
    p = tmp_path / "ruff.json"
    p.write_text(json.dumps([{"code": "F401"}, {"code": "S101"}]), encoding="utf-8")
    result = rs._ruff_findings(str(p), exit_code=1)
    assert result["finding_count"] == 2
    assert result["outcome"] == "fail"
    assert result["required"] is True


def test_ruff_findings_missing_report_still_records_exit_code(tmp_path):
    result = rs._ruff_findings(str(tmp_path / "missing.json"), exit_code=0)
    assert result["outcome"] == "pass"
    assert result["finding_count"] is None


def test_mypy_is_never_required():
    # No log path AND no exit code == the job genuinely didn't run.
    result = rs._mypy_findings(None, exit_code=None)
    assert result["required"] is False
    assert result["outcome"] == "not_run"


def test_mypy_ran_but_report_missing_is_still_report_only():
    # exit_code present (mypy executed) but no log file -> report_only with
    # an unknown finding_count, distinct from "didn't run at all".
    result = rs._mypy_findings(None, exit_code=1)
    assert result["outcome"] == "report_only"
    assert result["finding_count"] is None
    assert result["required"] is False


def test_mypy_report_only_outcome(tmp_path):
    p = tmp_path / "mypy.log"
    p.write_text("scripts/foo.py:1: error: bad type\n", encoding="utf-8")
    result = rs._mypy_findings(str(p), exit_code=1)
    assert result["outcome"] == "report_only"
    assert result["finding_count"] == 1
    assert result["required"] is False


def test_build_summary_required_gates_pass_returns_exit_0(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT_PASS, encoding="utf-8")
    import argparse

    args = argparse.Namespace(
        junit=str(junit), ruff_json=None, ruff_exit_code=0,
        mypy_log=None, mypy_exit_code=None,
        validate_exit_code=0, shellcheck_exit_code=0, bash_syntax_exit_code=0, diff_check_exit_code=0,
        os="ubuntu-latest", out=str(tmp_path / "summary.json"),
    )
    summary = rs.build_summary(args)
    assert summary["gates"]["validate"]["outcome"] == "pass"
    assert summary["gates"]["pytest"]["outcome"] == "pass"
    assert summary["required_gate_set"] == ["validate", "pytest", "ruff", "shellcheck", "bash_syntax", "diff_check"]


def test_build_summary_required_gate_failure_is_visible(tmp_path):
    import argparse

    args = argparse.Namespace(
        junit=None, ruff_json=None, ruff_exit_code=1,  # ruff failed
        mypy_log=None, mypy_exit_code=None,
        validate_exit_code=0, shellcheck_exit_code=0, bash_syntax_exit_code=0, diff_check_exit_code=0,
        os="ubuntu-latest", out=str(tmp_path / "summary.json"),
    )
    summary = rs.build_summary(args)
    assert summary["gates"]["ruff"]["outcome"] == "fail"


def test_main_writes_file_and_exit_code_reflects_required_gates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT_PASS, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_summary.py",
            "--junit", str(junit),
            "--ruff-exit-code", "0",
            "--validate-exit-code", "0",
            "--shellcheck-exit-code", "0",
            "--bash-syntax-exit-code", "0",
            "--diff-check-exit-code", "0",
            "--out", str(tmp_path / "reports" / "summary.json"),
        ],
    )
    exit_code = rs.main()
    assert exit_code == 0
    assert (tmp_path / "reports" / "summary.json").exists()


def test_main_nonzero_exit_when_required_gate_failed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_summary.py",
            "--ruff-exit-code", "1",  # required gate failed
            "--validate-exit-code", "0",
            "--shellcheck-exit-code", "0",
            "--bash-syntax-exit-code", "0",
            "--diff-check-exit-code", "0",
            "--out", str(tmp_path / "reports" / "summary.json"),
        ],
    )
    exit_code = rs.main()
    assert exit_code == 1


def test_ci_summary_distinguishes_pr_source_head_from_tested_merge_commit(tmp_path):
    import argparse

    source = "a" * 40
    tested = "b" * 40
    base = "c" * 40
    args = argparse.Namespace(
        mode="ci", repository="owner/repo", event_name="pull_request", pull_request_number=123,
        run_id="456", run_attempt=2, source_head_sha=source, tested_commit_sha=tested, base_sha=base,
        junit=None, ruff_json=None, ruff_exit_code=0, mypy_log=None, mypy_exit_code=None,
        validate_exit_code=0, shellcheck_exit_code=0, bash_syntax_exit_code=0, diff_check_exit_code=0,
        os="ubuntu-latest", out=str(tmp_path / "summary.json"),
    )
    summary = rs.build_summary(args)
    assert summary["source_head_sha"] == source
    assert summary["tested_commit_sha"] == tested
    assert summary["candidate_commit"] == tested
    assert summary["artifact_name"] == f"review-evidence-{tested}-attempt-2"


def test_push_summary_uses_head_for_source_and_tested_commit(tmp_path):
    import argparse

    head = "a" * 40
    args = argparse.Namespace(
        mode="ci", repository="owner/repo", event_name="push", pull_request_number=0,
        run_id="456", run_attempt=1, source_head_sha=head, tested_commit_sha=head, base_sha=None,
        junit=None, ruff_json=None, ruff_exit_code=0, mypy_log=None, mypy_exit_code=None,
        validate_exit_code=0, shellcheck_exit_code=0, bash_syntax_exit_code=0, diff_check_exit_code=0,
        os="ubuntu-latest", out=str(tmp_path / "summary.json"),
    )
    summary = rs.build_summary(args)
    assert summary["source_head_sha"] == head
    assert summary["tested_commit_sha"] == head
    assert summary["base_sha"] is None


def test_push_zero_before_sha_normalizes_base_to_null(tmp_path):
    import argparse

    args = argparse.Namespace(
        mode="ci", repository="owner/repo", event_name="push", pull_request_number=0,
        run_id="456", run_attempt=1, source_head_sha="a" * 40, tested_commit_sha="a" * 40,
        base_sha="0" * 40, junit=None, ruff_json=None, ruff_exit_code=0,
        mypy_log=None, mypy_exit_code=None, validate_exit_code=0, shellcheck_exit_code=0,
        bash_syntax_exit_code=0, diff_check_exit_code=0, os="ubuntu-latest",
        out=str(tmp_path / "summary.json"),
    )
    assert rs.build_summary(args)["base_sha"] is None


def test_ci_summary_rejects_missing_provenance(tmp_path):
    import argparse

    args = argparse.Namespace(
        mode="ci", repository=None, event_name="push", pull_request_number=0,
        run_id="456", run_attempt=1, source_head_sha="a" * 40, tested_commit_sha="a" * 40, base_sha=None,
        junit=None, ruff_json=None, ruff_exit_code=0, mypy_log=None, mypy_exit_code=None,
        validate_exit_code=0, shellcheck_exit_code=0, bash_syntax_exit_code=0, diff_check_exit_code=0,
        os="ubuntu-latest", out=str(tmp_path / "summary.json"),
    )
    try:
        rs.build_summary(args)
    except ValueError as error:
        assert "repository" in str(error)
    else:
        raise AssertionError("CI provenance must fail closed")


def test_ci_summary_rejects_nonpositive_run_attempt(tmp_path):
    import argparse

    args = argparse.Namespace(
        mode="ci", repository="owner/repo", event_name="push", pull_request_number=0,
        run_id="456", run_attempt=0, source_head_sha="a" * 40, tested_commit_sha="a" * 40, base_sha=None,
        junit=None, ruff_json=None, ruff_exit_code=0, mypy_log=None, mypy_exit_code=None,
        validate_exit_code=0, shellcheck_exit_code=0, bash_syntax_exit_code=0, diff_check_exit_code=0,
        os="ubuntu-latest", out=str(tmp_path / "summary.json"),
    )
    try:
        rs.build_summary(args)
    except ValueError as error:
        assert "positive integers" in str(error)
    else:
        raise AssertionError("non-positive run attempt must fail closed")


def test_ci_summary_requires_positive_pr_number_for_pull_request(tmp_path):
    import argparse

    args = argparse.Namespace(
        mode="ci", repository="owner/repo", event_name="pull_request", pull_request_number=0,
        run_id="456", run_attempt=1, source_head_sha="a" * 40, tested_commit_sha="b" * 40,
        base_sha="c" * 40, junit=None, ruff_json=None, ruff_exit_code=0,
        mypy_log=None, mypy_exit_code=None, validate_exit_code=0, shellcheck_exit_code=0,
        bash_syntax_exit_code=0, diff_check_exit_code=0, os="ubuntu-latest",
        out=str(tmp_path / "summary.json"),
    )
    try:
        rs.build_summary(args)
    except ValueError as error:
        assert "pull_request_number" in str(error)
    else:
        raise AssertionError("PR evidence must fail closed without a PR number")


def test_ci_workflow_supplies_exact_provenance_and_attempt_bound_artifact_name():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    for argument in (
        "--mode ci", "--repository", "--event-name", "--pull-request-number", "--run-id",
        "--run-attempt", "--source-head-sha", "--tested-commit-sha", "--base-sha",
    ):
        assert argument in workflow
    assert '--source-head-sha "${{ github.event.pull_request.head.sha || github.sha }}"' in workflow
    assert '--tested-commit-sha "${{ github.sha }}"' in workflow
    assert '--base-sha "${{ github.event.pull_request.base.sha || github.event.before || \'\' }}"' in workflow
    assert "review-evidence-${{ github.sha }}-attempt-${{ github.run_attempt }}" in workflow
