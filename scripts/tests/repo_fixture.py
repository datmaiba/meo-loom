"""A working copy of this repository, for tests that must run `validate.py` end to end.

Extracted from ``test_corpus_append_only.py`` so a second module cannot re-implement it
subtly differently — ``plan-reviewer`` round 2 flagged exactly that. Not named
``test_*`` so pytest does not collect it.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True, check=True)


def is_git_checkout(root: Path) -> bool:
    return (root / ".git").exists()


def repo_copy(tmp_path: Path, *, clear_handoffs: bool = False) -> Path:
    """Copy the repo, give it its OWN git dir, and optionally empty ``handoffs/``.

    The .git directory is deliberately NOT copied and a fresh one is initialised
    instead. Copying it is unsafe in a linked worktree, where .git is a *file* holding an
    absolute ``gitdir:`` - ``git rev-parse --git-dir`` still succeeds inside the copy, so
    git resolves to the ORIGINAL repository and ``git add -f`` would stage into the
    developer's real index. This repo's own workflow provisions worktrees.
    Reported by code-reviewer round 4, 2026-07-25.

    ``clear_handoffs`` exists because a copy carries the real handoffs/ contents, so a
    test that builds its own handoff fixture on top of them is not testing what it
    claims - and "no handoffs at all" is unreachable by adding files.
    """
    dest = tmp_path / "copy"
    shutil.copytree(
        ROOT, dest, symlinks=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ruff_cache"),
    )
    if clear_handoffs:
        handoffs = dest / "handoffs"
        if handoffs.is_dir():
            for item in handoffs.iterdir():
                if item.is_file():
                    item.unlink()
    git("init", "-q", ".", cwd=dest)
    git("config", "user.email", "test@example.invalid", cwd=dest)
    git("config", "user.name", "test", cwd=dest)
    return dest


def run_validate(root: Path) -> tuple[int, str]:
    result = subprocess.run(
        (sys.executable, "scripts/validate.py"),
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def assert_validate_completed(code: int, out: str) -> None:
    """Require a complete validator verdict before asserting a scoped property.

    Exit 1 may contain unrelated findings from the copied working tree. It is
    accepted only with the validator's complete finding summary, never a crash
    or an empty/truncated result. Whole-repository tests must still require 0.
    """
    assert code in (0, 1), f"unexpected validator exit {code}: {out[-400:]}"
    assert "Traceback (most recent call last):" not in out, out[-400:]
    if code == 0:
        assert out.strip().splitlines() == ["✓ all checks green"], out[-400:]
        return
    assert out.endswith("\n"), f"unterminated validator verdict: {out[-400:]}"
    lines = out.splitlines()
    summary = re.fullmatch(r"❌ ([1-9][0-9]*) finding\(s\):", lines[0]) if lines else None
    assert summary is not None, f"missing validator finding summary: {out[-400:]}"
    finding_count = 0
    for index, line in enumerate(lines[1:], 1):
        if line.startswith(" - "):
            assert line[3:].strip(), out[-400:]
            finding_count += 1
        else:
            assert finding_count, out[-400:]
            assert line.strip() or any(rest.strip() for rest in lines[index + 1:]), out[-400:]
    assert finding_count == int(summary.group(1)), out[-400:]


UNRELATED_FINDING = (
    "EVOLUTION_ORPHAN_PATH: docs/QA-UNRELATED.md: matched 0 component classes"
)


def seed_unrelated_finding(root: Path) -> None:
    """Add an unclassified document only to a disposable repository fixture."""
    assert root.resolve() != ROOT.resolve(), "never seed the working repository"
    path = root / "docs" / "QA-UNRELATED.md"
    assert not path.exists(), "the unrelated fixture must start absent"
    path.write_text("# Synthetic unrelated validation finding\n", encoding="utf-8")
