import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
import contract_check as cc


def scaffold_contract(target: Path) -> None:
    shutil.copytree(ROOT / "templates/common", target, dirs_exist_ok=True)
    # templates/common also stores migration-only sources; a greenfield
    # materialization emits only scaffold_active manifest rows.
    (target / ".cursorrules").unlink(missing_ok=True)
    project_name = target.name
    for relative in (
        "AGENTS.md",
        "CONTEXT.md",
        "lessons-learned/lessons-learned.md",
    ):
        path = target / relative
        path.write_text(
            path.read_text(encoding="utf-8").replace("{{PROJECT_NAME}}", project_name),
            encoding="utf-8",
        )
    rules = target / "docs/agent-working-rules.md"
    rules.write_text("This document is part of the canonical `AGENTS.md` contract.\n", encoding="utf-8")


def scaffold_v116_contract(target: Path) -> None:
    # Frozen v1.16 project state. Since the slice-5a templates flip the live
    # templates scaffold "MeoLoom 3.0"; real 1.16 projects still carry the
    # 1.16 marker and product prose, which this fixture reconstructs
    # byte-exactly from the current templates.
    scaffold_contract(target)
    shutil.copy2(ROOT / "templates/common/.cursorrules", target / ".cursorrules")
    agents = target / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8").replace(
            "**Canonical contract revision:** MeoLoom 3.0",
            "**Canonical contract revision:** dat-kit 1.16.0",
        ).replace("MeoLoom", "dat-kit"),
        encoding="utf-8",
    )
    workflow = target / "docs/agent-workflow.md"
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace("MeoLoom", "dat-kit"),
        encoding="utf-8",
    )


def codes(report):
    return {code for code, _ in report.items}


class ChangedCtimeStat:
    def __init__(self, value, ctime_ns):
        self._value = value
        self.st_ctime_ns = ctime_ns

    def __getattr__(self, name):
        return getattr(self._value, name)


def test_empty_brownfield_is_compatible(tmp_path):
    assert not cc.check_target(tmp_path).items


def test_greenfield_scaffold_is_green_under_v2(tmp_path):
    # Slice 5a exit proof: after the atomic templates flip a fresh scaffold
    # carries the 2.0 marker and the full 2.0 pointer set — GREEN, no
    # migration gate, no conflicts.
    scaffold_contract(tmp_path)
    report = cc.check_target(tmp_path)
    assert report.revision_state == "green"
    assert "CONTRACT_MIGRATION_REQUIRED" not in codes(report)
    assert not report.items


def test_marker_inside_a_code_fence_does_not_count(tmp_path):
    # FU-1 (phase-3 evidence): a fenced example quoting the old revision
    # header is documentation ABOUT a marker, not a marker — it must not
    # make a green project read as mixed-revision.
    scaffold_contract(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8")
        + "\n## Migration example\n\n```markdown\n"
        "**Canonical contract revision:** dat-kit 1.16.0\n```\n",
        encoding="utf-8",
    )
    report = cc.check_target(tmp_path)
    assert report.revision_state == "green"
    assert "CONTRACT_PARTIAL_MIGRATION" not in codes(report)


def test_marker_in_inline_code_does_not_count(tmp_path):
    # FU-1: same rule for inline code spans. Prose mentions still count —
    # that boundary is pinned by test_mixed_markers_are_partial in
    # test_revision_states.py.
    scaffold_contract(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        agents.read_text(encoding="utf-8")
        + "\nMigrate any `dat-kit 1.16.0` project before enabling gates.\n",
        encoding="utf-8",
    )
    report = cc.check_target(tmp_path)
    assert report.revision_state == "green"
    assert "CONTRACT_PARTIAL_MIGRATION" not in codes(report)


def test_recognized_v116_is_migration_source_never_green(tmp_path):
    # Legacy state machine: recognition prevents data loss, it does
    # not certify currency — a clean 1.16 scaffold is nonzero, without
    # conflicts, and its legacy pointer gets typed RETIRE_LEGACY semantics.
    scaffold_v116_contract(tmp_path)
    report = cc.check_target(tmp_path)
    assert "CONTRACT_MIGRATION_REQUIRED" in codes(report)
    assert "CONTRACT_MIGRATION_CONFLICT" not in codes(report)
    assert report.revision_state == "migration-source"
    retire = [
        item for item in report.diagnostics if item.action == "RETIRE_LEGACY"
    ]
    assert [item.path for item in retire] == [".cursorrules"]


@pytest.mark.parametrize(
    ("relative", "content", "diagnostic"),
    [
        ("AGENTS.md", "# competing policy\n", "COMPETING_AGENTS"),
        ("CLAUDE.md", "# Build rules\n## Quality gates\n", "POINTER_MISMATCH"),
        ("CLAUDE.md.tpl", "legacy", "LEGACY_CONTRACT"),
        (".codex/config.toml", "model_provider='local'", "RUNTIME_ADAPTER_CONFLICT"),
    ],
)
def test_conflicts_are_named(tmp_path, relative, content, diagnostic):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    assert diagnostic in codes(cc.check_target(tmp_path))


def test_wrong_case_is_rejected(tmp_path):
    scaffold_contract(tmp_path)
    (tmp_path / "CLAUDE.md").rename(tmp_path / "claude.md")
    # A missing pointer is acceptable for partial adoption; a wrong-cased one is
    # found by the full inventory during mutation tests, so assert exact helper.
    report = cc.Report()
    assert cc.exact_path(tmp_path, "CLAUDE.md", report) is None
    assert "CONTRACT_WRONG_CASE" in codes(report)


def test_symlink_is_rejected(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.write_text("x", encoding="utf-8")
    try:
        (tmp_path / "CLAUDE.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert "UNSAFE_SYMLINK" in codes(cc.check_target(tmp_path))


def test_symlink_is_not_read_after_rejection(monkeypatch, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside-policy"
    outside.write_text("private policy", encoding="utf-8")
    try:
        link = tmp_path / "CLAUDE.md"
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    original = cc.normalized

    def guarded(path):
        if path == link:
            raise AssertionError("unsafe symlink was read")
        return original(path)

    monkeypatch.setattr(cc, "normalized", guarded)
    report = cc.check_target(tmp_path)
    assert [code for code, _ in report.items] == ["UNSAFE_SYMLINK"]


def test_target_root_symlink_is_rejected_without_reading(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-root-outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text("SECRET_ROOT_POLICY", encoding="utf-8")
    link = tmp_path / "target-link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    report = cc.check_target(link)
    assert [(item.code, item.path) for item in report.diagnostics] == [("UNSAFE_SYMLINK", ".")]
    assert "SECRET_ROOT_POLICY" not in json.dumps(cc.target_json(report, mode="check", plan=None))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior")
def test_windows_junction_escape_is_rejected_without_reading(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-junction-outside"
    outside.mkdir()
    (outside / "hooks.json").write_text('{"secret": "must-not-read"}', encoding="utf-8")
    junction = tmp_path / ".codex"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("junction creation unavailable")
    try:
        report = cc.check_target(tmp_path)
        assert [code for code, _ in report.items] == ["UNSAFE_SYMLINK"]
        assert all("secret" not in item.summary for item in report.diagnostics)
    finally:
        junction.rmdir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior")
def test_windows_target_root_junction_is_rejected_without_reading(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-root-junction-outside"
    outside.mkdir()
    (outside / "AGENTS.md").write_text("SECRET_ROOT_JUNCTION_POLICY", encoding="utf-8")
    junction = tmp_path / "target-junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("junction creation unavailable")
    try:
        report = cc.check_target(junction)
        assert [(item.code, item.path) for item in report.diagnostics] == [
            ("UNSAFE_SYMLINK", ".")
        ]
        assert "SECRET_ROOT_JUNCTION_POLICY" not in json.dumps(
            cc.target_json(report, mode="check", plan=None)
        )
    finally:
        junction.rmdir()


@pytest.mark.parametrize("payload", [b"\xff\xfe", None])
def test_invalid_contract_content_is_reported_without_crashing(tmp_path, payload):
    pointer = tmp_path / "CLAUDE.md"
    if payload is None:
        pointer.mkdir()
    else:
        pointer.write_bytes(payload)
    report = cc.check_target(tmp_path)
    assert "CONTRACT_CONTENT_INVALID" in codes(report)


def test_target_swap_between_lstat_and_open_is_not_read(monkeypatch, tmp_path):
    pointer = tmp_path / "CLAUDE.md"
    pointer.write_text("Read AGENTS.md.\n", encoding="utf-8")
    real_open = cc.os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == pointer and not swapped:
            swapped = True
            pointer.unlink()
            pointer.write_text("SECRET_OUTSIDE_POLICY", encoding="utf-8")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(cc.os, "open", swap_then_open)
    report = cc.check_target(tmp_path)
    assert [code for code, _ in report.items] == ["UNSAFE_SYMLINK"]
    assert all("SECRET_OUTSIDE_POLICY" not in item.summary for item in report.diagnostics)


def test_target_swap_is_rejected_when_file_identity_is_reused(monkeypatch, tmp_path):
    pointer = tmp_path / "CLAUDE.md"
    pointer.write_text("Read AGENTS.md.\n", encoding="utf-8")
    original = pointer.lstat()
    real_open = cc.os.open
    real_lstat = Path.lstat
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == pointer and not swapped:
            swapped = True
            pointer.unlink()
            pointer.write_text("X" * original.st_size, encoding="utf-8")
            os.utime(pointer, ns=(original.st_atime_ns, original.st_mtime_ns))
        return real_open(path, flags, *args, **kwargs)

    def reused_identity_lstat(path):
        result = real_lstat(path)
        if Path(path) == pointer and swapped:
            return ChangedCtimeStat(result, original.st_ctime_ns + 1)
        return result

    monkeypatch.setattr(cc.os, "open", swap_then_open)
    monkeypatch.setattr(Path, "lstat", reused_identity_lstat)
    monkeypatch.setattr(cc.os.path, "samestat", lambda _before, _after: True)
    report = cc.check_target(tmp_path)

    assert [code for code, _ in report.items] == ["UNSAFE_SYMLINK"]
    assert all("X" * original.st_size not in item.summary for item in report.diagnostics)


def test_target_root_reuse_with_changed_ctime_is_rejected(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    original = target.lstat()
    real_lstat = Path.lstat
    target_calls = 0

    def reused_root_lstat(path):
        nonlocal target_calls
        result = real_lstat(path)
        if Path(path) == target:
            target_calls += 1
            if target_calls >= 2:
                return ChangedCtimeStat(result, original.st_ctime_ns + 1)
        return result

    monkeypatch.setattr(Path, "lstat", reused_root_lstat)
    monkeypatch.setattr(cc.os.path, "samestat", lambda _before, _after: True)
    report = cc.Report()

    assert cc._target_root(target, report) is None
    assert [code for code, _ in report.items] == ["UNSAFE_SYMLINK"]


def test_metadata_reader_rejects_reused_file_identity(monkeypatch, tmp_path):
    metadata = tmp_path / "index"
    metadata.write_bytes(b"SAFE")
    original = metadata.lstat()
    real_open = cc.os.open
    real_lstat = Path.lstat
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == metadata and not swapped:
            swapped = True
            metadata.unlink()
            metadata.write_bytes(b"EVIL")
            os.utime(metadata, ns=(original.st_atime_ns, original.st_mtime_ns))
        return real_open(path, flags, *args, **kwargs)

    def reused_metadata_lstat(path):
        result = real_lstat(path)
        if Path(path) == metadata and swapped:
            return ChangedCtimeStat(result, original.st_ctime_ns + 1)
        return result

    monkeypatch.setattr(cc.os, "open", swap_then_open)
    monkeypatch.setattr(Path, "lstat", reused_metadata_lstat)
    monkeypatch.setattr(cc.os.path, "samestat", lambda _before, _after: True)

    assert cc._safe_metadata_bytes(metadata, 1024) is None


def test_parent_swap_between_inventory_and_read_is_not_followed(monkeypatch, tmp_path):
    codex = tmp_path / ".codex"
    codex.mkdir()
    (codex / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    original_read = cc._read_target
    swapped = False

    def swap_parent_then_read(inspected, relative, report):
        nonlocal swapped
        if relative == ".codex/hooks.json" and not swapped:
            swapped = True
            codex.rename(tmp_path / ".codex-original")
            codex.mkdir()
            (codex / "hooks.json").write_text(
                '{"ANTHROPIC_BASE_URL": "SECRET_OUTSIDE_ROUTE"}\n', encoding="utf-8"
            )
        return original_read(inspected, relative, report)

    monkeypatch.setattr(cc, "_read_target", swap_parent_then_read)
    report = cc.check_target(tmp_path)
    assert [code for code, _ in report.items] == ["UNSAFE_SYMLINK"]
    diagnostic = report.diagnostics[0]
    assert "routing-signal" not in diagnostic.evidence
    assert "SECRET_OUTSIDE_ROUTE" not in diagnostic.summary


def test_target_root_replacement_during_inventory_is_rejected(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "CLAUDE.md").write_text("Read AGENTS.md.\n", encoding="utf-8")
    original_target_path = cc._target_path
    swapped = False

    def swap_root(root, relative, report, root_fingerprint=None):
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(tmp_path / "original-target")
            root.mkdir()
            (root / "CLAUDE.md").write_text("SECRET_REPLACEMENT_POLICY", encoding="utf-8")
        return original_target_path(root, relative, report, root_fingerprint)

    monkeypatch.setattr(cc, "_target_path", swap_root)
    report = cc.check_target(target)
    assert [(item.code, item.path) for item in report.diagnostics] == [("UNSAFE_SYMLINK", ".")]
    assert "SECRET_REPLACEMENT_POLICY" not in json.dumps(
        cc.target_json(report, mode="check", plan=None)
    )


def test_target_root_replacement_during_establishment_is_rejected(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    original_lstat = cc.Path.lstat
    target_calls = 0

    def swap_on_revalidation(path):
        nonlocal target_calls
        if path == target:
            target_calls += 1
            if target_calls == 2:
                target.rename(tmp_path / "original-target")
                target.mkdir()
                (target / "AGENTS.md").write_text("SECRET_ROOT_REPLACEMENT", encoding="utf-8")
        return original_lstat(path)

    monkeypatch.setattr(cc.Path, "lstat", swap_on_revalidation)
    report = cc.check_target(target)
    assert [(item.code, item.path) for item in report.diagnostics] == [("UNSAFE_SYMLINK", ".")]
    assert "SECRET_ROOT_REPLACEMENT" not in json.dumps(
        cc.target_json(report, mode="check", plan=None)
    )


def test_target_ancestor_replacement_during_establishment_is_rejected(monkeypatch, tmp_path):
    ancestor = tmp_path / "ancestor"
    target = ancestor / "target"
    target.mkdir(parents=True)
    original_lstat = cc.Path.lstat
    ancestor_calls = 0

    def swap_ancestor_on_revalidation(path):
        nonlocal ancestor_calls
        if path == ancestor:
            ancestor_calls += 1
            if ancestor_calls == 2:
                ancestor.rename(tmp_path / "original-ancestor")
                target.mkdir(parents=True)
                (target / "AGENTS.md").write_text(
                    "SECRET_ANCESTOR_REPLACEMENT", encoding="utf-8"
                )
        return original_lstat(path)

    monkeypatch.setattr(cc.Path, "lstat", swap_ancestor_on_revalidation)
    report = cc.check_target(target)
    assert [(item.code, item.path) for item in report.diagnostics] == [("UNSAFE_SYMLINK", ".")]
    assert "SECRET_ANCESTOR_REPLACEMENT" not in json.dumps(
        cc.target_json(report, mode="check", plan=None)
    )


def test_working_rules_machine_marker_is_language_neutral(tmp_path):
    rules = tmp_path / "docs/agent-working-rules.md"
    rules.parent.mkdir(parents=True)
    rules.write_text("<!-- dat-kit:working-rules -->\n# Quy tắc\n", encoding="utf-8")
    assert not cc.check_target(tmp_path).items


def test_registry_separates_package_and_contract_versions():
    data = cc.registry_json()
    manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert data["package_version"] == manifest["version"]
    assert data["contract_revision"] == "MeoLoom 3.0"
    assert data["supported_contract_revisions"] == ["MeoLoom 3.0", "dat-kit 2.0", "dat-kit 1.16.0"]


def test_typed_pointer_diagnostics_preserve_legacy_items(tmp_path):
    pointer = tmp_path / "CLAUDE.md"
    pointer.write_text("Read AGENTS.md. This file MUST remain a pointer.\n", encoding="utf-8")
    report = cc.check_target(tmp_path)
    assert [code for code, _ in report.items] == ["POINTER_MISMATCH", "POINTER_POLICY"]
    assert [item.action for item in report.diagnostics] == [
        "EXTRACT_THEN_REPLACE",
        "EXTRACT_THEN_REPLACE",
    ]
    assert all(item.classification == "customized-static" for item in report.diagnostics)


@pytest.mark.parametrize(
    "content",
    [
        "# Canonical policy for another toolkit\n",
        "# Third-party policy\nDo not install dat-kit here.\n",
    ],
)
def test_third_party_canonical_agents_is_competing_not_stale(tmp_path, content):
    agents = tmp_path / "AGENTS.md"
    agents.write_text(content, encoding="utf-8")
    report = cc.check_target(tmp_path)
    diagnostic = next(item for item in report.diagnostics if item.code == "COMPETING_AGENTS")
    assert diagnostic.classification == "competing-contract"


def test_git_tracking_evidence_covers_non_git_and_unavailable(monkeypatch, tmp_path):
    assert cc.git_tracking_evidence(tmp_path, ".codex/hooks.json") == "not-a-git-repo"

    hook = tmp_path / ".codex/hooks.json"
    hook.parent.mkdir()
    hook.write_text('{"hooks": {}}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", ".codex/hooks.json"], cwd=tmp_path, check=True)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(cc.subprocess, "run", unavailable)
    assert cc.git_tracking_evidence(tmp_path, ".codex/hooks.json") == "git-unavailable"


def test_nested_repository_tracking_uses_nearest_git_root(tmp_path):
    outer = tmp_path / "outer"
    target = outer / "target"
    hook = target / ".codex/hooks.json"
    hook.parent.mkdir(parents=True)
    hook.write_text('{"hooks": {}}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    subprocess.run(["git", "add", "target/.codex/hooks.json"], cwd=outer, check=True)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "tracked"

    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "untracked"
    subprocess.run(["git", "add", ".codex/hooks.json"], cwd=target, check=True)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "tracked"


def test_git_tracking_disables_repository_fsmonitor(tmp_path):
    target = tmp_path / "target"
    hook = target / ".codex/hooks.json"
    hook.parent.mkdir(parents=True)
    hook.write_text('{"hooks": {}}\n', encoding="utf-8")
    marker = tmp_path / "fsmonitor-executed"
    monitor = tmp_path / "fsmonitor.py"
    monitor.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", ".codex/hooks.json"], cwd=target, check=True)
    subprocess.run(
        ["git", "config", "core.fsmonitor", f'{sys.executable} "{monitor}"'],
        cwd=target,
        check=True,
    )

    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "tracked"
    assert not marker.exists()


def test_git_tracking_never_selects_target_local_git(monkeypatch, tmp_path):
    target = tmp_path / "target"
    hook = target / ".codex/hooks.json"
    hook.parent.mkdir(parents=True)
    hook.write_text('{"hooks": {}}\n', encoding="utf-8")
    fake_git = target / ("git.exe" if os.name == "nt" else "git")
    fake_git.write_text("not an executable Git binary\n", encoding="utf-8")
    if os.name != "nt":
        fake_git.chmod(0o755)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", ".codex/hooks.json"], cwd=target, check=True)
    real_run = cc.subprocess.run
    commands = []

    def guarded_run(command, *args, **kwargs):
        commands.append(command)
        assert Path(command[0]).is_absolute()
        assert Path(command[0]) != fake_git
        return real_run(command, *args, **kwargs)

    monkeypatch.chdir(target)
    monkeypatch.setattr(cc.subprocess, "run", guarded_run)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "tracked"
    assert commands


def test_git_resolver_rejects_absolute_path_entry_inside_target(monkeypatch, tmp_path):
    trusted_git = cc._trusted_git_executable()
    if trusted_git is None:
        pytest.skip("trusted Git executable unavailable")
    target = tmp_path / "target"
    target.mkdir()
    fake_git = target / ("git.exe" if os.name == "nt" else "git")
    shutil.copy2(sys.executable, fake_git)
    if os.name != "nt":
        fake_git.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(target) + os.pathsep + str(Path(trusted_git).parent)
    )

    resolved = cc._trusted_git_executable(target)
    assert resolved is not None
    assert Path(resolved) != fake_git
    assert Path(resolved).is_absolute()


def test_external_gitfile_is_rejected_before_git_invocation(monkeypatch, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").write_text("gitdir: //example.invalid/share/repo\n", encoding="utf-8")

    def must_not_run(*args, **kwargs):
        raise AssertionError("unsafe gitfile reached Git")

    monkeypatch.setattr(cc, "_git_command", must_not_run)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "git-unavailable"


@pytest.mark.parametrize("payload", [b"gitdir:\n", b"gitdir: bad\x00path\n"])
def test_malformed_gitfile_fails_closed_without_crashing(monkeypatch, tmp_path, payload):
    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").write_bytes(payload)

    def must_not_run(*args, **kwargs):
        raise AssertionError("malformed gitfile reached Git")

    monkeypatch.setattr(cc, "_git_command", must_not_run)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "git-unavailable"


@pytest.mark.parametrize("section", ['include', 'includeIf "gitdir:/**"'])
def test_local_git_config_include_is_rejected_before_git_invocation(
    monkeypatch, tmp_path, section
):
    target = tmp_path / "target"
    target.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    config = target / ".git/config"
    with config.open("a", encoding="utf-8") as handle:
        handle.write(f'\n[{section}]\n\tpath = //example.invalid/share/config\n')

    def must_not_run(*args, **kwargs):
        raise AssertionError("unsafe local include reached Git")

    monkeypatch.setattr(cc, "_git_command", must_not_run)
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "git-unavailable"


def test_split_index_failure_is_git_unavailable_not_untracked(tmp_path):
    target = tmp_path / "target"
    hook = target / ".codex/hooks.json"
    hook.parent.mkdir(parents=True)
    hook.write_text('{"hooks": {}}\n', encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(["git", "add", ".codex/hooks.json"], cwd=target, check=True)
    result = subprocess.run(
        ["git", "update-index", "--split-index"], cwd=target, check=False
    )
    if result.returncode != 0:
        pytest.skip("split index unavailable")
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "git-unavailable"


def test_corrupt_index_failure_is_git_unavailable_not_untracked(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    (target / ".git/index").write_bytes(b"not-a-git-index")
    assert cc.git_tracking_evidence(target, ".codex/hooks.json") == "git-unavailable"


@pytest.mark.parametrize(
    ("relative", "content"),
    [
        (".codex/hooks.json", '{"foreign_runtime": true}\n'),
        (".codex/config.toml", 'foreign_runtime = true\n'),
    ],
)
def test_valid_but_unverified_runtime_schema_is_unknown(tmp_path, relative, content):
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    report = cc.check_target(tmp_path)
    diagnostic = next(item for item in report.diagnostics if item.path == relative)
    assert "unknown-schema" in diagnostic.evidence


def test_invalid_target_is_structured_without_absolute_json_leak(tmp_path):
    target = tmp_path / "missing"
    report = cc.check_target(target)
    assert [code for code, _ in report.items] == ["TARGET_INVALID"]
    data = cc.target_json(report, mode="check", plan=None)
    assert data["diagnostics"][0]["path"] == "."
    assert str(target) not in json.dumps(data)


def test_registry_is_the_pointer_inventory():
    flattened = {path for paths in cc.POINTERS.values() for path in paths}
    assert flattened == set(cc.POINTER_TEMPLATES)
    assert set(cc.POINTERS) <= set(cc.RUNTIMES)
    assert "cursor" in cc.RUNTIMES


def test_registry_extension_needs_only_entry_and_template(monkeypatch, tmp_path):
    template = tmp_path / "NEW_AGENT.md"
    template.write_text("Read AGENTS.md. Do not add policy here.\n", encoding="utf-8")
    pointers = {**cc.POINTERS, "synthetic": ("NEW_AGENT.md",)}
    templates = {**cc.POINTER_TEMPLATES, "NEW_AGENT.md": str(template)}
    flattened = {path for paths in pointers.values() for path in paths}
    assert flattened == set(templates)


def test_cli_registry_json():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "contract_check.py"), "--registry-json"],
        text=True, capture_output=True, check=True,
    )
    data = json.loads(result.stdout)
    assert data["runtimes"] == list(cc.RUNTIMES)
    assert data["contract_revision"] == cc.CONTRACT_REVISION
    assert data["supported_contract_revisions"] == list(cc.SUPPORTED_CONTRACT_REVISIONS)


def test_init_consumes_generated_pointer_manifest_without_host_tuple():
    script = (SCRIPTS / "init.sh").read_text(encoding="utf-8")
    manifest = (ROOT / "templates/common/.meoloom-files.tsv").read_text(encoding="utf-8")
    assert "materialize_manifest" in script
    for pointer in {path for paths in cc.POINTERS.values() for path in paths}:
        assert f"\t{pointer}\t" in manifest
        assert f'TARGET/{pointer}' not in script


def test_ci_runs_for_version_tag_pushes():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "branches: [master, main]" in workflow
    assert 'tags: ["v*"]' in workflow
