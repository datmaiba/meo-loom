import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/contract_check.py"
FIXTURE = Path(__file__).parent / "fixtures/contract-drift-v1"

TOP_LEVEL_KEYS = {
    "schema_version",
    "mode",
    "target",
    "ok",
    "package_version",
    "contract_revision",
    "green_revisions",
    "migratable_source_revisions",
    "revision_state",
    "supported_contract_revisions",
    "diagnostics",
    "migration_plan",
}
DIAGNOSTIC_KEYS = {
    "code",
    "path",
    "classification",
    "summary",
    "evidence",
    "action",
    "template",
    "manual_review",
}
ACTIONS = {
    "EXTRACT_THEN_REPLACE",
    "MERGE_REQUIRED",
    "INSPECT_REMOVE",
    "RENAME_REQUIRED",
    "BLOCKED_UNSAFE",
}


def copy_fixture(target: Path) -> None:
    shutil.copytree(FIXTURE, target, dirs_exist_ok=True)


def snapshot(root: Path):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def run_cli(target: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_incident_migration_plan_is_deterministic_and_read_only(tmp_path):
    copy_fixture(tmp_path)
    before = snapshot(tmp_path)
    first = run_cli(tmp_path, "--migration-plan")
    second = run_cli(tmp_path, "--migration-plan")
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
    assert snapshot(tmp_path) == before
    assert "MIGRATION PLAN (read-only)" in first.stdout
    assert str(tmp_path) not in first.stdout
    assert "UNRESOLVED" in first.stdout


def test_incident_json_check_preserves_legacy_diagnostic_cardinality(tmp_path):
    copy_fixture(tmp_path)
    legacy = run_cli(tmp_path)
    result = run_cli(tmp_path, "--format", "json")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert set(data) == TOP_LEVEL_KEYS
    assert data["schema_version"] == 1
    assert data["mode"] == "check"
    assert data["target"] == "."
    assert data["ok"] is False
    assert data["contract_revision"] == "MeoLoom 3.0"
    assert data["supported_contract_revisions"] == ["MeoLoom 3.0", "dat-kit 2.0", "dat-kit 1.16.0"]
    assert data["migration_plan"] is None
    assert len(data["diagnostics"]) == len(legacy.stdout.splitlines())
    assert all(set(item) == DIAGNOSTIC_KEYS for item in data["diagnostics"])
    assert {item["action"] for item in data["diagnostics"]} <= ACTIONS
    assert all(len(item["summary"]) <= 240 for item in data["diagnostics"])
    assert [item["code"] for item in data["diagnostics"]] == [
        line.split(":", 1)[0] for line in legacy.stdout.splitlines()
    ]
    assert all(str(tmp_path) not in json.dumps(item) for item in data["diagnostics"])


def test_default_pointer_text_keeps_native_template_separator(tmp_path):
    copy_fixture(tmp_path)
    result = run_cli(tmp_path)
    expected = str(Path("templates/common/CLAUDE.md"))
    assert f"CLAUDE.md: differs from {expected}" in result.stdout


def test_incident_json_plan_has_seven_path_groups_and_valid_step_graph(tmp_path):
    copy_fixture(tmp_path)
    result = run_cli(tmp_path, "--migration-plan", "--format", "json")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["mode"] == "migration-plan"
    plan = data["migration_plan"]
    assert set(plan) == {"groups", "steps", "preservation", "unresolved"}
    assert all(
        set(group) == {"path", "diagnostic_codes", "action", "step_ids", "manual_review"}
        for group in plan["groups"]
    )
    assert all(
        set(step) == {"id", "instruction", "paths", "depends_on", "manual_review"}
        for step in plan["steps"]
    )
    assert all(
        set(item) == {"path", "method", "destination", "step_id"}
        for item in plan["preservation"]
    )
    assert all(
        set(item) == {"path", "reason", "step_id"} for item in plan["unresolved"]
    )
    assert len(plan["groups"]) == 7
    assert {group["path"] for group in plan["groups"]} == {
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/CLAUDE.md",
        ".cursorrules",
        "docs/agent-workflow.md",
        "docs/agent-working-rules.md",
        ".codex/hooks.json",
    }
    step_ids = {step["id"] for step in plan["steps"]}
    references = {
        ref for step in plan["steps"] for ref in step["depends_on"]
    } | {
        ref for group in plan["groups"] for ref in group["step_ids"]
    } | {item["step_id"] for item in plan["preservation"]} | {
        item["step_id"] for item in plan["unresolved"]
    }
    assert references <= step_ids
    positions = {step["id"]: index for index, step in enumerate(plan["steps"])}
    assert all(
        positions[dependency] < positions[step["id"]]
        for step in plan["steps"]
        for dependency in step["depends_on"]
    )


def test_text_plan_names_every_exact_static_template_source(tmp_path):
    copy_fixture(tmp_path)
    result = run_cli(tmp_path, "--migration-plan")
    for template in (
        "templates/common/CLAUDE.md",
        "templates/common/.claude/CLAUDE.md",
        "templates/common/docs/agent-workflow.md",
    ):
        assert f"from: {template}" in result.stdout
    # A customized retired pointer is preserved for manual merge; it must not
    # be presented as a byte-replacement from the legacy template.
    assert ".cursorrules: CONTRACT_MIGRATION_CONFLICT -> MERGE_REQUIRED" in result.stdout
    assert 'python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target .' in result.stdout


def test_line_endings_do_not_change_structured_diagnostics(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    copy_fixture(left)
    copy_fixture(right)
    for path in right.rglob("*"):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            path.write_text(text.replace("\n", "\r\n"), encoding="utf-8", newline="")
    left_data = json.loads(run_cli(left, "--format", "json").stdout)
    right_data = json.loads(run_cli(right, "--format", "json").stdout)
    assert left_data == right_data


def test_runtime_tracking_evidence_is_target_relative(tmp_path):
    copy_fixture(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    untracked = json.loads(run_cli(tmp_path, "--format", "json").stdout)
    hook = next(item for item in untracked["diagnostics"] if item["path"] == ".codex/hooks.json")
    assert "untracked" in hook["evidence"]
    subprocess.run(["git", "add", ".codex/hooks.json"], cwd=tmp_path, check=True)
    tracked = json.loads(run_cli(tmp_path, "--format", "json").stdout)
    hook = next(item for item in tracked["diagnostics"] if item["path"] == ".codex/hooks.json")
    assert "tracked" in hook["evidence"]


@pytest.mark.parametrize(
    "args",
    [
        ("--migration-plan",),
        ("--format", "json"),
    ],
)
def test_target_is_required_for_structured_modes(args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2


def test_registry_mode_is_mutually_exclusive_with_target(tmp_path):
    result = run_cli(tmp_path, "--registry-json")
    assert result.returncode == 2
