"""A working copy of this repository, for tests that must run `validate.py` end to end.

Extracted from ``test_corpus_append_only.py`` so a second module cannot re-implement it
subtly differently — ``plan-reviewer`` round 2 flagged exactly that. Not named
``test_*`` so pytest does not collect it.
"""

from __future__ import annotations

from pathlib import Path
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
