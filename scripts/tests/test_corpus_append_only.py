"""Cross-commit append-only enforcement for the three committed corpora.

``docs/contracts/telemetry-v3.md`` T3.2 declares three surfaces "committed,
append-only": ``benchmarks/telemetry-v3.jsonl``, ``benchmarks/defects.jsonl``
and ``benchmarks/scorecard.jsonl``. The runtime already protects them *at write
time* and *within a single snapshot* — ``_split_history`` /
``_validate_existing_corpus`` reject duplicate event IDs and malformed
correction chains, ``strict_tail`` refuses to append after a partial line, and
``corpus_check`` re-validates under the write lock. All of that binds only a
writer that goes through the runtime.

Nothing detected an out-of-band mutation of an already-committed corpus: a hand
edit, a rewrite by another tool, or a truncation. This module closes that gap by
walking git history and requiring, for every commit that touches one of the
three paths, that the parent's blob is a byte *prefix* of the child's blob.

Design notes, each one load-bearing:

* ``--full-history`` is mandatory. Default history simplification is TREESAME
  and would prune a tampering commit that lives on a merged side branch.
* The base case is **derived**, never pinned to a SHA. A squash or rebase erases
  whichever commit first added a path, which would make a pinned base
  permanently unsatisfiable.
* A merge commit must be a prefix-extension of **every** parent that holds the
  path. The weaker "at least one parent" rule permits an interleaving that
  reorders lines while still extending one side.
* A shallow clone **fails**; it must never skip. Grafted history cannot prove
  the invariant, and silently passing would make the gate decorative.
* Outside a git checkout the module degrades explicitly, matching the
  established fallback in ``scripts/registry.py`` for the same situation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]

# The three surfaces docs/contracts/telemetry-v3.md T3.2 declares append-only.
APPEND_ONLY_CORPORA = (
    "benchmarks/telemetry-v3.jsonl",
    "benchmarks/defects.jsonl",
    "benchmarks/scorecard.jsonl",
)


# The public repository begins with empty corpora at one audited root. It
# inherits no exception from the private maintenance archive. Any future entry
# requires a public owner decision and a corresponding register update.
KNOWN_HISTORICAL_EXCEPTIONS: dict[tuple[str, str], str] = {}


def _git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _is_git_checkout(root: Path) -> bool:
    try:
        _git("rev-parse", "--git-dir", cwd=root)
    except (RuntimeError, FileNotFoundError, NotADirectoryError):
        return False
    return True


def _is_shallow(root: Path) -> bool:
    return _git("rev-parse", "--is-shallow-repository", cwd=root).strip() == "true"


def _is_partial(root: Path) -> bool:
    """A blob-filtered clone has full history but no blobs - and is not shallow."""
    # --get-regexp, not --get on remote.origin.*: `git remote rename origin upstream`
    # made a genuine blob-filtered clone read as complete. qa-agent regression
    # 2026-07-25. extensions.partialclone is not set by git 2.34, so the regexp over
    # every remote is the portable form.
    return bool(
        _git(
            "config", "--get-regexp", r"remote\..*\.(promisor|partialclonefilter)",
            cwd=root, check=False,
        ).strip()
    )


def _commits_touching(path: str, root: Path = ROOT) -> list[str]:
    """Every commit that touched ``path``, oldest first, with no history simplification."""
    out = _git("log", "--full-history", "--reverse", "--format=%H", "--", path, cwd=root)
    return out.split()


def _parents(commit: str, root: Path = ROOT) -> list[str]:
    return _git("rev-parse", f"{commit}^@", cwd=root).split()


class UnreadableBlob(RuntimeError):
    """The path exists at this commit but its content is not available locally."""


def _blob(commit: str, path: str, root: Path = ROOT) -> bytes | None:
    """Bytes of ``path`` at ``commit``; None only when the path is genuinely ABSENT.

    An earlier version returned None on any non-zero ``git show``, conflating
    "absent here" with "blob unreadable". qa-agent (2026-07-25) showed the
    consequence: in a blob-filtered partial clone - which is NOT shallow, so the
    shallow guard passes - every parent blob was unreadable, ``holders`` came out
    empty, every commit took the base-case amnesty and all three corpus params went
    VACUOUSLY GREEN. That is the "decorative gate" this module's own docstring
    forbids. Absence is now decided by the tree, and an unreadable blob raises.

    A non-regular tree entry also raises: ``git show`` on a mode-120000 entry yields
    the symlink TARGET TEXT, so the walk would have compared link targets while the
    real bytes were rewritten underneath (also qa-agent).
    """
    entry = _git("ls-tree", "-z", commit, "--", path, cwd=root)
    if not entry.strip("\0").strip():
        return None  # genuinely absent at this commit
    meta = entry.strip("\0").split("\t", 1)[0].split()
    mode, kind = meta[0], meta[1]
    if kind != "blob" or mode not in {"100644", "100755"}:
        raise UnreadableBlob(
            f"{path} at {commit[:9]} is a {kind} with mode {mode}; an append-only "
            "corpus must be a regular file, and git show would compare link targets"
        )
    result = subprocess.run(
        ("git", "cat-file", "blob", f"{commit}:{path}"),
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise UnreadableBlob(
            f"{path} at {commit[:9]} is present in the tree but its blob is not "
            "available locally (partial clone?); append-only cannot be verified"
        )
    return result.stdout


def _is_known_exception(path: str, commit: str) -> bool:
    return any(
        path == exc_path and commit.startswith(exc_sha)
        for exc_path, exc_sha in KNOWN_HISTORICAL_EXCEPTIONS
    )


def append_only_violations(path: str, root: Path = ROOT, *, allow_known: bool = False) -> list[str]:
    """Return a human-readable violation per commit that did not purely append.

    A commit is conformant when, for every parent that holds ``path``, the
    parent's blob is a byte prefix of the commit's blob. A commit that creates
    the path (no parent holds it) is the derived base case and is conformant by
    definition.
    """
    if not _is_git_checkout(root):
        # Explicit degradation, matching scripts/registry.py's rglob fallback: a
        # vendored or tarball copy has no history to walk, and crashing is worse
        # than reporting that the invariant is unverifiable here.
        #
        # Stated precisely, because an earlier draft of this comment overclaimed:
        # outside a checkout the repo-level tests SKIP (they are decorated
        # skipif not _is_git_checkout), they do not fail. Skipping is correct for
        # a vendored copy - there is nothing to verify - and CI always has a
        # checkout, where the shallow test and the exception guards do fail
        # loudly. A re-initialised repo that looks like a checkout but has no
        # history remains indistinguishable to this walk; protected publication
        # policy and independent provenance review cover that repository-level
        # boundary.
        return []
    violations: list[str] = []
    for commit in _commits_touching(path, root):
        if allow_known and _is_known_exception(path, commit):
            continue
        child = _blob(commit, path, root)
        parent_blobs = {
            parent: _blob(parent, path, root)
            for parent in _parents(commit, root)
        }
        holders = {p: b for p, b in parent_blobs.items() if b is not None}

        if not holders:
            # Derived base case: this commit introduced the path.
            continue

        if child is None:
            violations.append(f"{path}: {commit[:9]} deleted a committed append-only corpus")
            continue

        for parent, blob in holders.items():
            if not child.startswith(blob):
                violations.append(
                    f"{path}: {commit[:9]} is not a byte-prefix extension of parent {parent[:9]} "
                    f"(parent {len(blob)} bytes, child {len(child)} bytes)"
                )
    return violations


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="not a git checkout; history cannot be walked")
def test_repository_history_is_not_shallow():
    """A shallow clone must fail, never skip - grafted history cannot prove the invariant."""
    assert not _is_shallow(ROOT), (
        "history is shallow, so append-only cannot be verified; "
        "fetch full history (actions/checkout fetch-depth: 0)"
    )
    assert not _is_partial(ROOT), (
        "this is a blob-filtered partial clone: history is complete but blobs are "
        "not, so append-only cannot be verified. It is NOT shallow, which is why "
        "this needs its own assertion"
    )


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="not a git checkout; history cannot be walked")
@pytest.mark.parametrize("path", APPEND_ONLY_CORPORA)
def test_committed_corpus_history_is_append_only(path):
    assert not _is_shallow(ROOT), "shallow history: run test_repository_history_is_not_shallow"
    assert not _is_partial(ROOT), "partial clone: run test_repository_history_is_not_shallow"
    violations = append_only_violations(path, allow_known=True)
    assert violations == [], "append-only violation(s):\n" + "\n".join(violations)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="not a git checkout; history cannot be walked")
def test_exception_list_is_bounded():
    """The clean public root starts with no inherited exception."""
    assert KNOWN_HISTORICAL_EXCEPTIONS == {}, (
        "a public append-only exception requires an owner decision and register update"
    )


def test_degrades_explicitly_outside_a_git_checkout(tmp_path):
    """Outside a checkout the walk reports absence rather than raising.

    Mirrors the fallback scripts/registry.py already uses when git is
    unavailable: report the condition, do not crash the gate. An earlier draft
    asserted only the predicate, so it would have stayed green if
    append_only_violations crashed - the thing it claimed to cover.
    """
    assert _is_git_checkout(tmp_path) is False
    assert append_only_violations("benchmarks/defects.jsonl", root=tmp_path) == []


def test_a_recreated_history_is_not_silently_conformant(tmp_path):
    """Document the boundary: a history walk cannot detect repository replacement.

    A commit where no parent holds the path is conformant by definition. A new
    one-root repository that contains truncated bytes therefore passes this
    local walk. Publication provenance, branch protection, and independent
    review must prevent replacement of the approved public root.
    """
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n{"b":2}\n{"c":3}\n')
    assert append_only_violations("benchmarks/defects.jsonl", root=repo) == []
    # A fresh history holding only a truncated version is indistinguishable to
    # the walk alone; this test keeps that trust boundary explicit.
    other = _make_repo(tmp_path / "rewritten")
    _commit_corpus(other, b'{"a":1}\n')
    assert append_only_violations("benchmarks/defects.jsonl", root=other) == []


def test_prefix_extension_is_accepted(tmp_path):
    """Green path: a real append across two commits passes."""
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n')
    _commit_corpus(repo, b'{"a":1}\n{"b":2}\n')
    assert append_only_violations("benchmarks/defects.jsonl", root=repo) == []


def test_mutated_line_is_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n{"b":2}\n')
    _commit_corpus(repo, b'{"a":1}\n{"b":99}\n')
    violations = append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert len(violations) == 1
    assert "not a byte-prefix extension" in violations[0]


def test_deleted_line_is_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n{"b":2}\n')
    _commit_corpus(repo, b'{"a":1}\n')
    violations = append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert len(violations) == 1


def test_mid_file_insertion_is_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n{"b":2}\n')
    _commit_corpus(repo, b'{"a":1}\n{"x":0}\n{"b":2}\n')
    violations = append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert len(violations) == 1


def test_whole_file_deletion_is_detected(tmp_path):
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n')
    _git("rm", "-q", "benchmarks/defects.jsonl", cwd=repo)
    _git("commit", "-q", "-m", "remove corpus", cwd=repo)
    violations = append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert len(violations) == 1
    assert "deleted a committed append-only corpus" in violations[0]


def test_merge_that_extends_only_one_parent_is_detected(tmp_path):
    """The all-parents rule: extending one side while reordering the other is a violation."""
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"base":1}\n')
    _git("checkout", "-q", "-b", "side", cwd=repo)
    _commit_corpus(repo, b'{"base":1}\n{"side":1}\n')
    _git("checkout", "-q", "-", cwd=repo)
    _commit_corpus(repo, b'{"base":1}\n{"main":1}\n')
    # Resolve the merge so the result extends the main parent but reorders side's line.
    # git merge exits non-zero on conflict, which is the expected path here.
    _git("merge", "--no-commit", "--no-ff", "side", cwd=repo, check=False)
    (repo / "benchmarks" / "defects.jsonl").write_bytes(b'{"base":1}\n{"main":1}\n{"side":1}\n')
    _git("add", "benchmarks/defects.jsonl", cwd=repo)
    _git("commit", "-q", "-m", "merge side", cwd=repo)
    violations = append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert len(violations) == 1, violations
    assert "not a byte-prefix extension" in violations[0]


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "benchmarks").mkdir(parents=True)
    _git("init", "-q", ".", cwd=repo)
    _git("config", "user.email", "test@example.invalid", cwd=repo)
    _git("config", "user.name", "test", cwd=repo)
    _git("config", "commit.gpgsign", "false", cwd=repo)
    return repo


def _commit_corpus(repo: Path, content: bytes) -> None:
    target = repo / "benchmarks" / "defects.jsonl"
    target.write_bytes(content)
    _git("add", "benchmarks/defects.jsonl", cwd=repo)
    _git("commit", "-q", "-m", f"corpus -> {len(content)} bytes", cwd=repo)


# --- qa-agent findings, 2026-07-25 -------------------------------------------


def test_a_symlinked_corpus_is_refused_not_silently_compared(tmp_path):
    """qa-agent F7: `git show` on a mode-120000 entry yields the LINK TARGET text, so
    the walk compared link targets while the real bytes were rewritten underneath."""
    import os

    repo = _make_repo(tmp_path)
    (repo / "real.jsonl").write_bytes(b'{"a":1}\n{"b":2}\n{"c":3}\n')
    try:
        os.symlink("../real.jsonl", repo / "benchmarks" / "defects.jsonl")
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "symlinked corpus", cwd=repo)
    (repo / "real.jsonl").write_bytes(b'{"a":1}\n')
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "truncate behind the link", cwd=repo)

    with pytest.raises(UnreadableBlob) as excinfo:
        append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert "mode 120000" in str(excinfo.value)


def test_an_unreadable_blob_raises_instead_of_reading_as_absent(tmp_path):
    """qa-agent F4: conflating "unreadable" with "absent" made a blob-filtered partial
    clone go vacuously green - and a partial clone is NOT shallow, so the shallow
    guard passed. Two layers now stop it: _is_partial, and this."""
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n')
    _commit_corpus(repo, b'{"a":1}\n{"b":2}\n')
    assert append_only_violations("benchmarks/defects.jsonl", root=repo) == []

    head = _git("rev-parse", "HEAD", cwd=repo).strip()
    blob_sha = _git("rev-parse", f"{head}:benchmarks/defects.jsonl", cwd=repo).strip()
    # Delete the blob object so the tree still lists it but the content is gone.
    blob = repo / ".git" / "objects" / blob_sha[:2] / blob_sha[2:]
    try:
        blob.unlink()
    except PermissionError as error:
        pytest.skip(f"cannot remove a temporary Git object on this host: {error}")
    with pytest.raises(UnreadableBlob) as excinfo:
        append_only_violations("benchmarks/defects.jsonl", root=repo)
    assert "not available locally" in str(excinfo.value)


def test_partial_clone_detection_exists_and_is_separate_from_shallow():
    """The guard must be its own assertion: a blob-filtered clone has full history."""
    assert _is_partial(ROOT) is False
    assert _is_shallow(ROOT) is False


# --- qa-agent regression 2026-07-25: F2/F3/F10 had shipped with NO red-green ---
# The commit that fixed them claimed "red-green for every fix" and that was false:
# reverting the git-oracle block, or the three lifecycle codes, left the suite fully
# green. F2/F3 guard a DISCLOSURE gate, so an undetectable revert is the worst kind.
# These tests exist so that can never happen silently again.


# The repo-copy fixture and the validate runner live in repo_fixture.py so this module
# and test_load_instrumentation.py cannot drift apart on the linked-worktree .git hazard
# documented there. plan-reviewer round 2.
from repo_fixture import repo_copy as _repo_copy, run_validate as _validate  # noqa: E402


# Synthetic public test data: it intentionally identifies no person, company,
# project, domain, or private source.
_CANARY_TOKEN = "synthetic-local-token-7f31"
CANARY = '{"note":"reach me at %s@example.invalid"}\n' % _CANARY_TOKEN
_PERSONAL_INFO_TOKEN_FILE = ".personal-info-tokens.local"
_SYNTHETIC_TEST_TOKENS = (_CANARY_TOKEN,)


def _write_personal_info_tokens(root: Path) -> None:
    (root / _PERSONAL_INFO_TOKEN_FILE).write_text(
        _CANARY_TOKEN + "\n", encoding="utf-8"
    )


def _remove_personal_info_tokens(root: Path) -> None:
    (root / _PERSONAL_INFO_TOKEN_FILE).unlink(missing_ok=True)


def _assert_the_gate_flagged_the_canary_file(out: str) -> list[str]:
    """Assert the SPECIFIC evidence, never the generic failure string.

    ``_repo_copy`` copies the whole working tree including untracked files, so any
    ambient local finding satisfies a bare ``"PERSONAL INFO LEAK" in out`` - the two
    tests below would then pin nothing and stay green with the skip reverted to
    unconditional, which is the "passes for the wrong reason" class this module
    exists to close. security-reviewer round 2 F3.
    """
    findings = [
        line for line in out.replace("\\", "/").splitlines()
        if "PERSONAL INFO LEAK" in line
    ]
    matches = [line for line in findings if "telemetry/events.jsonl:1" in line]
    assert matches, "the finding does not name the canary file and line: %s" % out[-400:]
    return matches


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_scans_the_local_stream_when_git_does_not_ignore_it(tmp_path):
    """qa-agent F2: the old whitespace check passed on `# events.jsonl` while git did
    NOT ignore the file — a false green on exactly the condition it guards."""
    root = _repo_copy(tmp_path)
    _write_personal_info_tokens(root)
    (root / "telemetry" / ".gitignore").write_text("# events.jsonl\n", encoding="utf-8")
    (root / "telemetry" / "events.jsonl").write_text(CANARY, encoding="utf-8")
    code, out = _validate(root)
    assert code != 0, out[-400:]
    _assert_the_gate_flagged_the_canary_file(out)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_scans_the_local_stream_when_it_is_tracked(tmp_path):
    """qa-agent F3: `git add -f` made it committable and it was still skipped."""
    root = _repo_copy(tmp_path)
    _write_personal_info_tokens(root)
    (root / "telemetry" / ".gitignore").write_text("events.jsonl\n", encoding="utf-8")
    (root / "telemetry" / "events.jsonl").write_text(CANARY, encoding="utf-8")
    _git("add", "-f", "telemetry/events.jsonl", cwd=root)
    code, out = _validate(root)
    assert code != 0, out[-400:]
    _assert_the_gate_flagged_the_canary_file(out)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_reports_location_without_echoing_matched_content(tmp_path):
    """A public finding identifies the canary file but never repeats its content."""
    root = _repo_copy(tmp_path)
    _write_personal_info_tokens(root)
    (root / "telemetry" / ".gitignore").write_text("# events.jsonl\n", encoding="utf-8")
    (root / "telemetry" / "events.jsonl").write_text(CANARY, encoding="utf-8")
    code, out = _validate(root)
    assert code != 0, out[-400:]
    findings = _assert_the_gate_flagged_the_canary_file(out)
    assert all(_CANARY_TOKEN not in finding for finding in findings), (
        "the finding echoed the banned canary content"
    )


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_still_skips_a_genuinely_private_local_stream(tmp_path):
    """The disclosure fix must survive the two tests above: an ignored, untracked
    stream is NOT scanned, so the gate cannot echo local-private telemetry."""
    root = _repo_copy(tmp_path)
    _write_personal_info_tokens(root)
    (root / "telemetry" / ".gitignore").write_text("events.jsonl\n", encoding="utf-8")
    (root / "telemetry" / "events.jsonl").write_text(CANARY, encoding="utf-8")
    code, out = _validate(root)
    # Assert the PROPERTY, not that every unrelated check is green on a copy of the
    # working tree - any local finding would otherwise red this test for the wrong
    # reason (code-reviewer round 4).
    assert "telemetry/events.jsonl" not in out
    assert _CANARY_TOKEN not in out, "the gate echoed the local-private stream"


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_requires_the_local_token_file(tmp_path):
    """The local loader, rather than a tracked denylist, enables detection."""
    root = _repo_copy(tmp_path)
    _remove_personal_info_tokens(root)
    (root / "telemetry" / ".gitignore").write_text("# events.jsonl\n", encoding="utf-8")
    (root / "telemetry" / "events.jsonl").write_text(CANARY, encoding="utf-8")

    absent_code, absent_out = _validate(root)
    assert absent_code == 0, absent_out[-400:]
    assert "telemetry/events.jsonl" not in absent_out.replace("\\", "/")

    _write_personal_info_tokens(root)
    present_code, present_out = _validate(root)
    assert present_code != 0, present_out[-400:]
    _assert_the_gate_flagged_the_canary_file(present_out)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_loader_ignores_comments_blanks_and_regex_metacharacters(tmp_path):
    root = _repo_copy(tmp_path)
    token = "literal." + "with." + "dot"
    comment = "# local " + "patterns"
    (root / _PERSONAL_INFO_TOKEN_FILE).write_text(
        comment + "\n\n" + token + "\n", encoding="utf-8"
    )
    (root / "telemetry" / ".gitignore").write_text("# events.jsonl\n", encoding="utf-8")
    target = root / "telemetry" / "events.jsonl"
    target.write_text(comment + "\n" + token.replace(".", "X") + "\n", encoding="utf-8")

    near_miss_code, near_miss_out = _validate(root)
    assert near_miss_code == 0, near_miss_out[-400:]

    target.write_text(token + "\n", encoding="utf-8")
    exact_code, exact_out = _validate(root)
    assert exact_code != 0, exact_out[-400:]
    _assert_the_gate_flagged_the_canary_file(exact_out)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_loader_accepts_utf8_bom_on_the_first_token(tmp_path):
    root = _repo_copy(tmp_path)
    token = "first." + "local." + "token"
    (root / _PERSONAL_INFO_TOKEN_FILE).write_text(
        token + "\n", encoding="utf-8-sig"
    )
    (root / "telemetry" / ".gitignore").write_text("# events.jsonl\n", encoding="utf-8")
    (root / "telemetry" / "events.jsonl").write_text(token + "\n", encoding="utf-8")

    code, out = _validate(root)
    assert code != 0, out[-400:]
    _assert_the_gate_flagged_the_canary_file(out)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_scans_its_own_validator(tmp_path):
    root = _repo_copy(tmp_path)
    _write_personal_info_tokens(root)
    validator = root / "scripts" / "validate.py"
    with validator.open("a", encoding="utf-8") as stream:
        stream.write("\n# " + CANARY)

    code, out = _validate(root)
    assert code != 0, out[-400:]
    findings = [
        line for line in out.replace("\\", "/").splitlines()
        if "PERSONAL INFO LEAK" in line and "scripts/validate.py:" in line
    ]
    assert findings, "the validator's self-scan did not name its own file"
    assert all(_CANARY_TOKEN not in finding for finding in findings)


@pytest.mark.skipif(not _is_git_checkout(ROOT), reason="needs a git checkout to copy")
def test_personal_info_gate_does_not_exempt_a_symlink_alias(tmp_path):
    root = _repo_copy(tmp_path)
    _write_personal_info_tokens(root)
    alias = root / "personal-info-alias.py"
    try:
        alias.symlink_to(_PERSONAL_INFO_TOKEN_FILE)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    code, out = _validate(root)
    assert code != 0, out[-400:]
    findings = [
        line for line in out.replace("\\", "/").splitlines()
        if "PERSONAL INFO LEAK" in line and "personal-info-alias.py:1" in line
    ]
    assert findings, "a symlink alias inherited the local file's exemption"
    assert all(_CANARY_TOKEN not in finding for finding in findings)


def test_tracked_validator_contains_no_synthetic_canary_literal():
    """The gate's local inputs must not be embedded in its tracked source."""
    tracked = _git("ls-files", "--error-unmatch", "scripts/validate.py").strip()
    assert tracked == "scripts/validate.py"
    source = (ROOT / tracked).read_text(encoding="utf-8", errors="replace").casefold()
    assert not any(token.casefold() in source for token in _SYNTHETIC_TEST_TOKENS), (
        "tracked validator contains a synthetic local token literal"
    )


def test_is_partial_sees_a_promisor_on_a_renamed_remote(tmp_path):
    """qa-agent NEW-2: `--get remote.origin.*` missed a real blob-filtered clone after
    `git remote rename origin upstream`. Every other assertion in this module is
    `_is_partial(...) is False`, so reverting to --get was undetectable - which is the
    defect class NEW-1 exists to close (code-reviewer round 4)."""
    repo = _make_repo(tmp_path)
    _commit_corpus(repo, b'{"a":1}\n')
    assert _is_partial(repo) is False
    _git("config", "remote.upstream.promisor", "true", cwd=repo)
    _git("config", "remote.upstream.partialclonefilter", "blob:none", cwd=repo)
    assert _is_partial(repo) is True, "a promisor on a non-origin remote must be seen"
