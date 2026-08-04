from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "scripts/init.sh"


def bash_executable():
    candidates = [r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")]
    return next((value for value in candidates if value and Path(value).exists()), None)


def snapshot(root: Path):
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            result[relative] = ("directory", None)
        elif path.is_file():
            result[relative] = ("file", path.read_bytes())
    return result


def run_here(target: Path):
    bash = bash_executable()
    if not bash:
        pytest.skip("bash unavailable")
    env = os.environ.copy()
    env["PATH"] = str(Path(os.sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        [bash, INIT.as_posix(), "--here", "--profile", "react"], cwd=target,
        text=True, capture_output=True, env=env, check=False,
    )


def test_hostile_brownfield_is_byte_preserved(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(b"# private policy\r\n## Quality gates\r\n")
    (tmp_path / "app.txt").write_bytes(b"user bytes\x00\xff")
    before = snapshot(tmp_path)
    result = run_here(tmp_path)
    assert result.returncode != 0
    assert "POINTER_MISMATCH" in result.stdout
    assert "--migration-plan" in result.stdout
    assert snapshot(tmp_path) == before


def test_recovery_command_uses_placeholders_not_raw_target_path(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# private policy\n", encoding="utf-8")
    result = run_here(tmp_path)
    assert result.returncode != 0
    assert (
        'python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target . --migration-plan'
        in result.stdout
    )
    planner_line = next(line for line in result.stdout.splitlines() if "--migration-plan" in line)
    assert str(tmp_path) not in planner_line


@pytest.mark.parametrize(
    ("relative", "content", "diagnostic"),
    [
        ("AGENTS.md", "# competing contract\n", "COMPETING_AGENTS"),
        (".codex/hooks.json", '{"hooks": {}}\n', "RUNTIME_ADAPTER_CONFLICT"),
        ("claude.md", "Read AGENTS.md.\n", "CONTRACT_WRONG_CASE"),
    ],
)
def test_each_manual_remediation_class_aborts_before_mutation(
    tmp_path, relative, content, diagnostic
):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    (tmp_path / "user.bin").write_bytes(b"user\x00bytes")
    before = snapshot(tmp_path)
    result = run_here(tmp_path)
    assert result.returncode != 0
    assert diagnostic in result.stdout
    assert "--migration-plan" in result.stdout
    assert snapshot(tmp_path) == before


def test_blocked_unsafe_class_aborts_before_mutation(tmp_path):
    (tmp_path / "CLAUDE.md").mkdir()
    before = snapshot(tmp_path)
    result = run_here(tmp_path)
    assert result.returncode != 0
    assert "CONTRACT_CONTENT_INVALID" in result.stdout
    assert "--migration-plan" in result.stdout
    assert snapshot(tmp_path) == before


def test_canonical_rerun_is_readonly_and_idempotent(tmp_path):
    # A fresh scaffold is the current green MeoLoom 3.0
    # revision: a rerun must succeed as a no-op (no migration gate) while
    # mutating NOTHING — the real idempotency invariant.
    first = run_here(tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    before = snapshot(tmp_path)
    second = run_here(tmp_path)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "CONTRACT_MIGRATION_REQUIRED" not in second.stdout + second.stderr
    assert snapshot(tmp_path) == before


def test_compatible_partial_gets_only_missing_files(tmp_path):
    workflow = tmp_path / "docs/agent-workflow.md"
    workflow.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "templates/common/docs/agent-workflow.md", workflow)
    preserved = workflow.read_bytes()
    result = run_here(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert workflow.read_bytes() == preserved
    assert (tmp_path / "AGENTS.md").is_file()
