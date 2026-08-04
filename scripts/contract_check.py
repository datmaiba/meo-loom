#!/usr/bin/env python3
"""Shared MeoLoom contract checker and brownfield migration planner (stdlib only)."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from typing import Iterable

from registry import Catalog, resolve_json_pointer

ROOT = Path(__file__).resolve().parent.parent
# Fallbacks apply only when the registry itself fails to load; every load
# failure is already reported as its own diagnostic.
_FALLBACK_CANONICAL = "MeoLoom 3.0"
_FALLBACK_RECOGNIZED = ("MeoLoom 3.0", "dat-kit 2.0", "dat-kit 1.16.0")
JSON_SCHEMA_VERSION = 1
MAX_TARGET_READ_BYTES = 10 * 1024 * 1024  # brownfield DoS guard (security review, Phase 3)
WORKING_RULES_MARKERS = ("<!-- meoloom:working-rules -->", "<!-- dat-kit:working-rules -->")
WORKING_RULES_SENTINEL = "This document is part of the canonical `AGENTS.md` contract."

_CATALOG_RESULT = Catalog.load(ROOT)
_CATALOG = _CATALOG_RESULT if isinstance(_CATALOG_RESULT, Catalog) else None
_CATALOG_DIAGNOSTICS = () if _CATALOG is not None else _CATALOG_RESULT
_REVISION_MODEL = _CATALOG.revision_model() if _CATALOG is not None else None
CONTRACT_REVISION = (
    _REVISION_MODEL["canonical_revision"] if _REVISION_MODEL is not None else _FALLBACK_CANONICAL
)
GREEN_REVISIONS = tuple(
    _REVISION_MODEL["green_revisions"] if _REVISION_MODEL is not None else (_FALLBACK_CANONICAL,)
)
MIGRATABLE_REVISIONS = tuple(
    _REVISION_MODEL["migratable_source_revisions"] if _REVISION_MODEL is not None else ()
)
# Recognized = may appear in a project without making AGENTS.md a competing
# contract. Recognition is NOT green (§2 invariant 6).
SUPPORTED_CONTRACT_REVISIONS = (
    GREEN_REVISIONS + MIGRATABLE_REVISIONS if _REVISION_MODEL is not None else _FALLBACK_RECOGNIZED
)
POINTERS = _CATALOG.pointer_inventory() if _CATALOG is not None else {}
RUNTIMES = tuple(POINTERS) + ("other",)
POINTER_TEMPLATES = {
    artifact["target_relative_path"]: artifact["source_template"]
    for adapter in (_CATALOG.adapters() if _CATALOG is not None else ())
    for artifact in adapter["project_artifacts"]
    if artifact["artifact_lifecycle"] == "scaffold_active"
}
MIGRATION_POINTER_TEMPLATES = {
    artifact["target_relative_path"]: artifact["source_template"]
    for adapter in (_CATALOG.adapters() if _CATALOG is not None else ())
    for artifact in adapter["project_artifacts"]
    if artifact["artifact_lifecycle"] == "migration_ready"
}
CURRENT_MIGRATION_POINTER_TEMPLATES = {
    relative: template
    for relative, template in MIGRATION_POINTER_TEMPLATES.items()
    if relative == ".cursor/rules/meo-loom.mdc"
}
RETIRED_POINTER_TEMPLATES = {
    relative: template
    for relative, template in MIGRATION_POINTER_TEMPLATES.items()
    if relative != ".cursor/rules/meo-loom.mdc"
}
RETIRED_POINTER_TEMPLATES[".cursor/rules/dat-kit.mdc"] = (
    "templates/adapters/cursor/dat-kit.mdc"
)
INSPECTED_POINTER_TEMPLATES = {
    **POINTER_TEMPLATES,
    **CURRENT_MIGRATION_POINTER_TEMPLATES,
    **RETIRED_POINTER_TEMPLATES,
}
CANONICAL_STATIC = {
    **INSPECTED_POINTER_TEMPLATES,
    "docs/agent-workflow.md": "templates/common/docs/agent-workflow.md",
}
LOCAL_CONFIGS = (".codex/config.toml", ".codex/hooks.json")
LEGACY = ("CLAUDE.md.tpl", "rules/working.rules.md")
POLICY_TERMS = re.compile(
    r"(^##|\bMUST\b|quality gates?|build-loop|architecture rules?|plan gate)", re.I | re.M
)
ROUTING_TERMS = re.compile(r"ANTHROPIC_BASE_URL|model_provider|proxy", re.I)
ABSOLUTE_COMMAND = re.compile(r"(?:[A-Za-z]:\\|/(?:usr|opt|home)/)")
LOCAL_GIT_INCLUDE = re.compile(rb"(?im)^\s*\[\s*include(?:if)?(?:\s+\"[^\"]*\")?\s*\]")
KNOWN_CONTRACT_AGENT_MARKERS = (
    "**Canonical contract revision:** MeoLoom",
    "**Canonical contract revision:** dat-kit",
    "This is the canonical, agent-neutral contract",
    "# MeoLoom guidance",
    "# dat-kit guidance",
    "single canonical instruction entrypoint",
)

_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE = re.compile(r"`[^`\n]+`")


def _marker_scan_text(text: str) -> str:
    """Text with fenced code blocks and inline code spans removed (FU-1).

    Revision markers quoted inside a code fence or inline code span are
    documentation ABOUT a marker, not a marker: a migration guide that
    fences the old 1.16 header must not read as mixed-revision. Prose
    mentions still count (pinned by test_mixed_markers_are_partial) —
    only code regions are excluded. An unclosed fence runs to the end of
    the document, matching CommonMark and failing on the safe side.
    """
    lines: list[str] = []
    fence: str | None = None
    for line in text.split("\n"):
        if fence is None:
            match = _FENCE_OPEN.match(line)
            if match is not None:
                fence = match.group(1)
                continue
            lines.append(line)
        else:
            stripped = line.strip()
            if stripped.startswith(fence) and not stripped.strip(fence[0]):
                fence = None
    return _INLINE_CODE.sub("``", "\n".join(lines))

ACTIONS = {
    "EXTRACT_THEN_REPLACE",
    "MERGE_REQUIRED",
    "INSPECT_REMOVE",
    "RENAME_REQUIRED",
    "BLOCKED_UNSAFE",
    "MIGRATE_REPLACE",
    "RETIRE_LEGACY",
}


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    path: str
    classification: str
    summary: str
    evidence: tuple[str, ...]
    action: str
    template: str | None
    manual_review: bool

    def as_json(self) -> dict[str, object]:
        return {
            "code": self.code,
            "path": self.path,
            "classification": self.classification,
            "summary": self.summary[:240],
            "evidence": list(self.evidence),
            "action": self.action,
            "template": self.template,
            "manual_review": self.manual_review,
        }


@dataclass(frozen=True)
class InspectedTargetPath:
    path: Path
    fingerprints: tuple[tuple[Path, os.stat_result], ...]
    exists: bool


@dataclass(frozen=True)
class GitRepository:
    root: Path
    git_dir: Path


class Report:
    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []

    @property
    def items(self) -> list[tuple[str, str]]:
        """Legacy tuple projection retained for all v1 Python consumers."""
        return [(item.code, item.message) for item in self.diagnostics]

    def add(
        self,
        code: str,
        message: str,
        *,
        path: str = ".",
        classification: str = "invalid-content",
        summary: str | None = None,
        evidence: Iterable[str] = (),
        action: str = "BLOCKED_UNSAFE",
        template: str | None = None,
        manual_review: bool = True,
    ) -> None:
        if action not in ACTIONS:
            raise ValueError(f"unknown remediation action: {action}")
        self.diagnostics.append(
            Diagnostic(
                code=code,
                message=message,
                path=path,
                classification=classification,
                summary=(summary or message)[:240],
                evidence=tuple(evidence),
                action=action,
                template=template,
                manual_review=manual_review,
            )
        )

    def emit(self) -> int:
        for code, message in self.items:
            print(f"{code}: {message}")
        return 1 if self.diagnostics else 0


def normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def package_version(root: Path = ROOT) -> str:
    if root.resolve() == ROOT.resolve() and _CATALOG is not None:
        return _CATALOG.release_version
    loaded = Catalog.load(root)
    if isinstance(loaded, Catalog):
        return loaded.release_version
    raise ValueError("registry Catalog is unavailable")


def exact_path(root: Path, relative: str, report: Report) -> Path | None:
    current = root
    for part in PurePosixPath(relative).parts:
        if not current.is_dir():
            report.add("CONTRACT_MISSING", f"{relative}: parent is missing", path=relative)
            return None
        names = {child.name for child in current.iterdir()}
        if part not in names:
            folded = [name for name in names if name.casefold() == part.casefold()]
            code = "CONTRACT_WRONG_CASE" if folded else "CONTRACT_MISSING"
            report.add(code, f"{relative}: expected segment {part!r}", path=relative)
            return None
        current = current / part
    return current


def _same_stat_version(expected: os.stat_result, current: os.stat_result) -> bool:
    """Compare file identity plus metadata that changes on inode reuse/replacement."""
    if not os.path.samestat(expected, current) or expected.st_mode != current.st_mode:
        return False
    if not stat.S_ISREG(expected.st_mode):
        return True
    return bool(
        expected.st_size == current.st_size
        and expected.st_mtime_ns == current.st_mtime_ns
    )


def _same_path_version(expected: os.stat_result, current: os.stat_result) -> bool:
    """Compare two path snapshots, including replacement-sensitive ctime."""
    return _same_stat_version(expected, current) and expected.st_ctime_ns == current.st_ctime_ns


def _target_path(
    root: Path,
    relative: str,
    report: Report,
    root_fingerprint: os.stat_result | None = None,
) -> InspectedTargetPath | None:
    """Resolve a known relative path without following links or reading unsafe nodes."""
    current = root
    try:
        current_root = root.lstat()
    except OSError:
        report.add(
            "CONTRACT_CONTENT_INVALID",
            f"{relative}: target root is unreadable",
            path=relative,
            classification="invalid-content",
            summary="target root is unreadable",
            evidence=("unreadable",),
            action="BLOCKED_UNSAFE",
        )
        return None
    if root_fingerprint is not None and not _same_path_version(root_fingerprint, current_root):
        report.add(
            "UNSAFE_SYMLINK",
            ".: target root changed during inspection",
            path=".",
            classification="unsafe-path",
            summary="target root changed during inspection",
            evidence=("symlink",),
            action="BLOCKED_UNSAFE",
        )
        return None
    expected_root = root_fingerprint or current_root
    fingerprints: list[tuple[Path, os.stat_result]] = [(root, expected_root)]
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        try:
            names = {child.name for child in current.iterdir()}
        except OSError:
            report.add(
                "CONTRACT_CONTENT_INVALID",
                f"{relative}: parent is unreadable",
                path=relative,
                classification="invalid-content",
                summary="contract path parent is unreadable",
                evidence=("unreadable",),
                action="BLOCKED_UNSAFE",
            )
            return None
        if part not in names:
            folded = [name for name in names if name.casefold() == part.casefold()]
            if folded:
                report.add(
                    "CONTRACT_WRONG_CASE",
                    f"{relative}: expected segment {part!r}",
                    path=relative,
                    classification="wrong-case",
                    summary="contract path has incorrect casing",
                    evidence=("wrong-case",),
                    action="RENAME_REQUIRED",
                )
                return None
            return InspectedTargetPath(
                path=current.joinpath(*parts[index:]),
                fingerprints=tuple(fingerprints),
                exists=False,
            )
        candidate = current / part
        try:
            path_stat = candidate.lstat()
            mode = path_stat.st_mode
        except OSError:
            report.add(
                "CONTRACT_CONTENT_INVALID",
                f"{relative}: path is unreadable",
                path=relative,
                classification="invalid-content",
                summary="contract path is unreadable",
                evidence=("unreadable",),
                action="BLOCKED_UNSAFE",
            )
            return None
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        file_attributes = getattr(path_stat, "st_file_attributes", 0)
        if stat.S_ISLNK(mode) or (reparse_flag and file_attributes & reparse_flag):
            unsafe_relative = candidate.relative_to(root).as_posix()
            if not any(
                item.code == "UNSAFE_SYMLINK" and item.path == unsafe_relative
                for item in report.diagnostics
            ):
                report.add(
                    "UNSAFE_SYMLINK",
                    f"{unsafe_relative}: symlinks are not accepted during brownfield adoption",
                    path=unsafe_relative,
                    classification="unsafe-path",
                    summary="contract path is a symlink or reparse point",
                    evidence=("symlink",),
                    action="BLOCKED_UNSAFE",
                )
            return None
        if index < len(parts) - 1 and not stat.S_ISDIR(mode):
            report.add(
                "CONTRACT_CONTENT_INVALID",
                f"{relative}: parent is not a directory",
                path=relative,
                classification="invalid-content",
                summary="contract path parent is not a directory",
                evidence=("directory",),
                action="BLOCKED_UNSAFE",
            )
            return None
        fingerprints.append((candidate, path_stat))
        current = candidate
    if current.exists() and not current.is_file():
        report.add(
            "CONTRACT_CONTENT_INVALID",
            f"{relative}: expected a regular file",
            path=relative,
            classification="invalid-content",
            summary="contract path is not a regular file",
            evidence=("directory",),
            action="BLOCKED_UNSAFE",
        )
        return None
    return InspectedTargetPath(path=current, fingerprints=tuple(fingerprints), exists=True)


def _target_root(target: Path, report: Report) -> tuple[Path, os.stat_result] | None:
    """Establish the supplied root without resolving through links/reparse points."""
    absolute = Path(os.path.abspath(target))
    current = Path(absolute.anchor)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    fingerprints: list[tuple[Path, os.stat_result]] = []
    for part in absolute.parts[1:]:
        current /= part
        try:
            current_stat = current.lstat()
        except OSError as exc:
            report.add(
                "TARGET_INVALID",
                str(exc),
                classification="unsafe-path",
                summary="target is invalid",
                evidence=("invalid-target",),
                action="BLOCKED_UNSAFE",
            )
            return None
        file_attributes = getattr(current_stat, "st_file_attributes", 0)
        if stat.S_ISLNK(current_stat.st_mode) or (
            reparse_flag and file_attributes & reparse_flag
        ):
            report.add(
                "UNSAFE_SYMLINK",
                ".: target root contains a symlink or reparse point",
                path=".",
                classification="unsafe-path",
                summary="target root contains a symlink or reparse point",
                evidence=("symlink",),
                action="BLOCKED_UNSAFE",
            )
            return None
        fingerprints.append((current, current_stat))
    if not fingerprints:
        try:
            fingerprints.append((absolute, absolute.lstat()))
        except OSError as exc:
            report.add(
                "TARGET_INVALID",
                str(exc),
                classification="unsafe-path",
                summary="target is invalid",
                evidence=("invalid-target",),
                action="BLOCKED_UNSAFE",
            )
            return None

    for component, expected in fingerprints:
        try:
            current_stat = component.lstat()
        except OSError:
            current_stat = None
        file_attributes = getattr(current_stat, "st_file_attributes", 0)
        if (
            current_stat is None
            or stat.S_ISLNK(current_stat.st_mode)
            or (reparse_flag and file_attributes & reparse_flag)
            or not _same_path_version(expected, current_stat)
        ):
            report.add(
                "UNSAFE_SYMLINK",
                ".: target root changed during establishment",
                path=".",
                classification="unsafe-path",
                summary="target root changed during establishment",
                evidence=("symlink",),
                action="BLOCKED_UNSAFE",
            )
            return None
    root_stat = fingerprints[-1][1]
    if not stat.S_ISDIR(root_stat.st_mode):
        report.add(
            "TARGET_INVALID",
            f"{absolute} is not a directory",
            classification="unsafe-path",
            summary="target is not a directory",
            evidence=("invalid-target",),
            action="BLOCKED_UNSAFE",
        )
        return None
    return absolute, root_stat


def _fingerprints_match(inspected: InspectedTargetPath) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for component, expected in inspected.fingerprints:
        try:
            current = component.lstat()
        except OSError:
            return False
        file_attributes = getattr(current, "st_file_attributes", 0)
        if stat.S_ISLNK(current.st_mode) or (reparse_flag and file_attributes & reparse_flag):
            return False
        if not _same_path_version(expected, current):
            return False
    return True


def _read_target(inspected: InspectedTargetPath, relative: str, report: Report) -> str | None:
    path = inspected.path
    descriptor: int | None = None
    try:
        if not _fingerprints_match(inspected):
            report.add(
                "UNSAFE_SYMLINK",
                f"{relative}: parent path changed during no-follow inspection",
                path=relative,
                classification="unsafe-path",
                summary="contract parent path changed during inspection",
                evidence=("symlink",),
                action="BLOCKED_UNSAFE",
            )
            return None
        before = inspected.fingerprints[-1][1]
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if opened.st_size > MAX_TARGET_READ_BYTES:
            os.close(descriptor)
            descriptor = None
            report.add(
                "CONTRACT_CONTENT_INVALID",
                f"{relative}: file exceeds the {MAX_TARGET_READ_BYTES // (1024 * 1024)} MiB inspection limit",
                path=relative,
                classification="unsafe-path",
                summary="target file too large to inspect safely",
                evidence=("oversize",),
                action="BLOCKED_UNSAFE",
            )
            return None
        after = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_stat_version(before, opened)
            or not _same_stat_version(opened, after)
            or not _same_path_version(before, after)
            or not _fingerprints_match(inspected)
        ):
            os.close(descriptor)
            descriptor = None
            report.add(
                "UNSAFE_SYMLINK",
                f"{relative}: changed during no-follow inspection",
                path=relative,
                classification="unsafe-path",
                summary="contract path changed during inspection",
                evidence=("symlink",),
                action="BLOCKED_UNSAFE",
            )
            return None
        with os.fdopen(descriptor, "r", encoding="utf-8", newline=None) as handle:
            descriptor = None
            text = handle.read()
            return text.replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        report.add(
            "CONTRACT_CONTENT_INVALID",
            f"{relative}: content is not UTF-8",
            path=relative,
            classification="invalid-content",
            summary="contract content is not UTF-8",
            evidence=("non-utf8",),
            action="BLOCKED_UNSAFE",
        )
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            report.add(
                "UNSAFE_SYMLINK",
                f"{relative}: symlinks are not accepted during brownfield adoption",
                path=relative,
                classification="unsafe-path",
                summary="contract path became a symlink during inspection",
                evidence=("symlink",),
                action="BLOCKED_UNSAFE",
            )
            return None
        report.add(
            "CONTRACT_CONTENT_INVALID",
            f"{relative}: content is unreadable",
            path=relative,
            classification="invalid-content",
            summary="contract content is unreadable",
            evidence=("unreadable",),
            action="BLOCKED_UNSAFE",
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return None


def wrong_case_if_present(root: Path, relative: str, report: Report) -> None:
    _target_path(root, relative, report)


def is_tracked(path: str) -> bool:
    result = _git_command(
        "-C",
        str(ROOT),
        "--literal-pathspecs",
        "ls-files",
        "--error-unmatch",
        "--",
        path,
        forbidden_root=ROOT,
    )
    return result is not None and result.returncode == 0


def _git_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "NoDefaultCurrentDirectoryInExePath": "1",
        }
    )
    return environment


def _trusted_git_executable(forbidden_root: Path | None = None) -> str | None:
    """Find Git only in absolute PATH entries; never search the target/CWD."""
    names = ("git.exe", "git.com") if os.name == "nt" else ("git",)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    forbidden = Path(os.path.abspath(forbidden_root)) if forbidden_root is not None else None
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = Path(raw_entry.strip('"')) if raw_entry else None
        if entry is None or not entry.is_absolute():
            continue
        for name in names:
            candidate = Path(os.path.abspath(entry / name))
            if forbidden is not None:
                try:
                    if os.path.commonpath((forbidden, candidate)) == str(forbidden):
                        continue
                except ValueError:
                    continue
            try:
                candidate_stat = candidate.lstat()
            except (OSError, ValueError):
                continue
            file_attributes = getattr(candidate_stat, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(candidate_stat.st_mode)
                or stat.S_ISLNK(candidate_stat.st_mode)
                or (reparse_flag and file_attributes & reparse_flag)
                or not os.access(candidate, os.X_OK)
                or _safe_metadata_fingerprints(candidate) is None
            ):
                continue
            return str(candidate)
    return None


def _git_command(
    *arguments: str,
    capture_output: bool = False,
    forbidden_root: Path | None = None,
) -> subprocess.CompletedProcess[str] | None:
    executable = _trusted_git_executable(forbidden_root)
    if executable is None:
        return None
    command = [
        executable,
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.preloadIndex=false",
        *arguments,
    ]
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            check=False,
            env=_git_environment(),
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _safe_metadata_fingerprints(path: Path) -> tuple[tuple[Path, os.stat_result], ...] | None:
    try:
        absolute = Path(os.path.abspath(path))
    except (OSError, TypeError, ValueError):
        return None
    current = Path(absolute.anchor)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    fingerprints: list[tuple[Path, os.stat_result]] = []
    for part in absolute.parts[1:]:
        current /= part
        try:
            current_stat = current.lstat()
        except (OSError, ValueError):
            return None
        file_attributes = getattr(current_stat, "st_file_attributes", 0)
        if stat.S_ISLNK(current_stat.st_mode) or (
            reparse_flag and file_attributes & reparse_flag
        ):
            return None
        fingerprints.append((current, current_stat))
    for component, expected in fingerprints:
        try:
            current_stat = component.lstat()
        except (OSError, ValueError):
            return None
        file_attributes = getattr(current_stat, "st_file_attributes", 0)
        if (
            stat.S_ISLNK(current_stat.st_mode)
            or (reparse_flag and file_attributes & reparse_flag)
            or not _same_path_version(expected, current_stat)
        ):
            return None
    return tuple(fingerprints)


def _metadata_fingerprints_match(
    fingerprints: tuple[tuple[Path, os.stat_result], ...],
) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    for component, expected in fingerprints:
        try:
            current = component.lstat()
        except OSError:
            return False
        file_attributes = getattr(current, "st_file_attributes", 0)
        if (
            stat.S_ISLNK(current.st_mode)
            or (reparse_flag and file_attributes & reparse_flag)
            or not _same_path_version(expected, current)
        ):
            return False
    return True


def _safe_metadata_bytes(path: Path, maximum: int) -> bytes | None:
    fingerprints = _safe_metadata_fingerprints(path)
    if not fingerprints or not stat.S_ISREG(fingerprints[-1][1].st_mode):
        return None
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            opened.st_size > maximum
            or not _same_stat_version(fingerprints[-1][1], opened)
            or not _metadata_fingerprints_match(fingerprints)
        ):
            return None
        data = os.read(descriptor, maximum + 1)
        return data if len(data) <= maximum else None
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _discover_git_repository(root: Path) -> tuple[str, GitRepository | None]:
    candidate = Path(os.path.abspath(root))
    while True:
        marker = candidate / ".git"
        try:
            marker_stat = marker.lstat()
        except FileNotFoundError:
            marker_stat = None
        except (OSError, ValueError):
            return "git-unavailable", None
        if marker_stat is not None:
            marker_attributes = getattr(marker_stat, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if stat.S_ISLNK(marker_stat.st_mode) or (
                reparse_flag and marker_attributes & reparse_flag
            ):
                return "git-unavailable", None
            if stat.S_ISDIR(marker_stat.st_mode):
                git_dir = marker
                fingerprints = _safe_metadata_fingerprints(git_dir)
                if not fingerprints or not stat.S_ISDIR(fingerprints[-1][1].st_mode):
                    return "git-unavailable", None
            elif stat.S_ISREG(marker_stat.st_mode):
                gitfile = _safe_metadata_bytes(marker, 4096)
                if gitfile is None:
                    return "git-unavailable", None
                try:
                    line = gitfile.decode("utf-8").strip()
                except UnicodeDecodeError:
                    return "git-unavailable", None
                if not line.lower().startswith("gitdir:"):
                    return "git-unavailable", None
                gitdir_value = line.split(":", 1)[1].strip()
                if not gitdir_value or "\x00" in gitdir_value:
                    return "git-unavailable", None
                try:
                    git_dir = Path(os.path.abspath(candidate / gitdir_value))
                except (OSError, TypeError, ValueError):
                    return "git-unavailable", None
                try:
                    if os.path.commonpath((candidate, git_dir)) != str(candidate):
                        return "git-unavailable", None
                except ValueError:
                    return "git-unavailable", None
                fingerprints = _safe_metadata_fingerprints(git_dir)
                if not fingerprints or not stat.S_ISDIR(fingerprints[-1][1].st_mode):
                    return "git-unavailable", None
            else:
                return "git-unavailable", None

            config = git_dir / "config"
            try:
                config.lstat()
            except FileNotFoundError:
                config_data = b""
            except (OSError, ValueError):
                return "git-unavailable", None
            else:
                config_data = _safe_metadata_bytes(config, 1024 * 1024)
                if config_data is None:
                    return "git-unavailable", None
            if LOCAL_GIT_INCLUDE.search(config_data):
                return "git-unavailable", None
            return "repository", GitRepository(candidate, git_dir)
        parent = candidate.parent
        if parent == candidate:
            return "not-a-git-repo", None
        candidate = parent


def git_tracking_evidence(root: Path, relative: str) -> str:
    status, repository = _discover_git_repository(root)
    if repository is None:
        return status
    index = repository.git_dir / "index"
    try:
        index.lstat()
    except FileNotFoundError:
        return "untracked"
    except (OSError, ValueError):
        return "git-unavailable"
    index_data = _safe_metadata_bytes(index, 128 * 1024 * 1024)
    if index_data is None:
        return "git-unavailable"
    try:
        target_relative = Path(os.path.abspath(root)).relative_to(repository.root)
    except ValueError:
        return "not-a-git-repo"
    candidate = (target_relative / PurePosixPath(relative)).as_posix()
    with tempfile.TemporaryDirectory(prefix="meoloom-git-") as temporary:
        isolated_git_dir = Path(temporary) / "repo.git"
        (isolated_git_dir / "objects").mkdir(parents=True)
        (isolated_git_dir / "refs").mkdir()
        (isolated_git_dir / "HEAD").write_text(
            "ref: refs/heads/meoloom-sandbox", encoding="ascii"
        )
        (isolated_git_dir / "index").write_bytes(index_data)
        tracked = _git_command(
            f"--git-dir={isolated_git_dir}",
            f"--work-tree={repository.root}",
            "--literal-pathspecs",
            "ls-files",
            "--error-unmatch",
            "--",
            candidate,
            forbidden_root=repository.root,
        )
    if tracked is None:
        return "git-unavailable"
    if tracked.returncode == 0:
        return "tracked"
    return "untracked" if tracked.returncode == 1 else "git-unavailable"


def check_pointer(path: Path, template: Path, label: str, report: Report) -> None:
    """Maintainer/template check; target checks use the typed variant below."""
    text = normalized(path)
    if text != normalized(template):
        report.add("POINTER_MISMATCH", f"{label}: differs from {template.relative_to(ROOT)}", path=label)
    if "AGENTS.md" not in text or POLICY_TERMS.search(text):
        report.add("POINTER_POLICY", f"{label}: must be a policy-free AGENTS.md pointer", path=label)


def manifest_versions(report: Report) -> None:
    if _CATALOG is None:
        for item in _CATALOG_DIAGNOSTICS:
            report.add(item.code, f"{item.path}: {item.message}")
        return
    for target in _CATALOG.version_targets():
        try:
            document = json.loads((ROOT / target.path).read_text(encoding="utf-8"))
            value = resolve_json_pointer(document, target.locator)
        except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
            report.add("MANIFEST_INVALID", f"{target.path}: {exc}")
            continue
        if value != target.expected_version:
            report.add(
                "CONTRACT_REVISION_MISMATCH",
                f"{target.path}: {value!r}, expected {target.expected_version!r}",
            )


def check_repo(root: Path = ROOT) -> Report:
    report = Report()
    required = (
        "AGENTS.md",
        "docs/agent-workflow.md",
        "docs/agent-working-rules.md",
        "templates/common/AGENTS.md",
        "templates/common/docs/agent-workflow.md",
        "templates/common/docs/agent-working-rules.md.tpl",
    )
    for rel in required:
        exact_path(root, rel, report)
    for _pointer, template in INSPECTED_POINTER_TEMPLATES.items():
        source = exact_path(root, template, report)
        if source:
            check_pointer(source, source, template, report)
    for legacy in ("templates/common/CLAUDE.md.tpl", "templates/common/rules/working.rules.md"):
        if (root / legacy).exists():
            report.add("LEGACY_CONTRACT", f"{legacy}: migrate manually; see docs/codex.md", path=legacy)
    for local in LOCAL_CONFIGS:
        if (root / local).exists() and is_tracked(local):
            report.add(
                "TRACKED_RUNTIME_CONFIG",
                f"{local}: machine-local runtime config must not be tracked",
                path=local,
            )
    bootstrap = root / "templates/session-bootstrap.txt"
    if not bootstrap.exists():
        report.add("ADAPTER_MISSING", "templates/session-bootstrap.txt is missing")
    else:
        text = normalized(bootstrap)
        if "AGENTS.md" not in text or POLICY_TERMS.search(text) or len(text.splitlines()) > 3:
            report.add(
                "ADAPTER_POLICY",
                "session bootstrap must only locate AGENTS.md and provide the adoption fallback",
            )
    try:
        hook_text = normalized(root / "hooks.json")
        hook = json.loads(hook_text)
        if any(term in hook_text for term in ("ANTHROPIC_BASE_URL", "build-loop", "quality gate")):
            report.add("ADAPTER_POLICY", "hooks.json contains shared policy or machine-local routing")
        if "SessionStart" not in hook.get("hooks", {}):
            report.add("ADAPTER_INVALID", "hooks.json has no SessionStart adapter")
    except (OSError, ValueError) as exc:
        report.add("ADAPTER_INVALID", f"hooks.json: {exc}")
    agents = root / "templates/common/AGENTS.md"
    if agents.exists() and not any(
        revision in normalized(agents) for revision in SUPPORTED_CONTRACT_REVISIONS
    ):
        # Templates must implement a recognized revision. They flip from the
        # migratable source to the canonical revision at the Phase 4 cutover.
        report.add("CONTRACT_REVISION_MISMATCH", "templates/common/AGENTS.md revision is stale")
    manifest_versions(report)
    return report


def contained(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
        return True
    except (OSError, ValueError):
        return False


def _inventory() -> set[str]:
    inventory = {"AGENTS.md", "docs/agent-workflow.md", "docs/agent-working-rules.md"}
    inventory.update(INSPECTED_POINTER_TEMPLATES)
    inventory.update(LOCAL_CONFIGS)
    inventory.update(LEGACY)
    for source in (ROOT / "templates/common").rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(ROOT / "templates/common").as_posix()
        if relative == "docs/agent-working-rules.md.tpl":
            relative = "docs/agent-working-rules.md"
        inventory.add(relative)
    return inventory


def _add_pointer_findings(
    text: str, template_text: str, relative: str, template_relative: str, report: Report
) -> None:
    policy_match = bool("AGENTS.md" not in text or POLICY_TERMS.search(text))
    evidence = ["template-mismatch"]
    if policy_match:
        evidence.append("policy-keyword")
    if text != template_text:
        template_display = str(Path(template_relative))
        report.add(
            "POINTER_MISMATCH",
            f"{relative}: differs from {template_display}",
            path=relative,
            classification="customized-static",
            summary="static pointer differs from the current template",
            evidence=evidence,
            action="EXTRACT_THEN_REPLACE",
            template=template_relative,
        )
    if policy_match:
        report.add(
            "POINTER_POLICY",
            f"{relative}: must be a policy-free AGENTS.md pointer",
            path=relative,
            classification="customized-static",
            summary="legacy pointer policy heuristic matched",
            evidence=evidence,
            action="EXTRACT_THEN_REPLACE",
            template=template_relative,
        )


def _runtime_evidence(root: Path, relative: str, text: str) -> tuple[str, ...]:
    evidence = [git_tracking_evidence(root, relative)]
    if POLICY_TERMS.search(text):
        evidence.append("policy-keyword")
    if ROUTING_TERMS.search(text):
        evidence.append("routing-signal")
    if ABSOLUTE_COMMAND.search(text):
        evidence.append("absolute-command-signal")
    # MeoLoom intentionally does not claim a verified Codex runtime schema.
    # Valid JSON/TOML syntax therefore remains unknown until a host contract is
    # proven; the content is still inspected only for bounded risk signals.
    if relative in LOCAL_CONFIGS:
        evidence.append("unknown-schema")
    return tuple(evidence)


def _hash_normalized(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_static_target(relative: str, text: str, project_name: str | None) -> str:
    """Hash a rendered static file in its descriptor-owned template form."""
    if relative == "AGENTS.md" and project_name is not None:
        rendered_title = f"# Agent contract — {project_name}\n"
        if text.startswith(rendered_title):
            text = "# Agent contract — {{PROJECT_NAME}}\n" + text[len(rendered_title):]
    return _hash_normalized(text)


def _classify_target_revision(paths: dict[str, "InspectedTargetPath | None"], report: Report) -> str:
    """Project-contract revision state machine (registry contract R8).

    Returns one of: green | migration-source | partial | unsupported |
    unclassified. Recognition never certifies currency; only a green revision
    produces no revision diagnostic. Read-only: never mutates the target.
    """
    if _REVISION_MODEL is None:
        return "unclassified"  # registry load failure already reported
    text_cache: dict[str, str | None] = {}

    def read(relative: str) -> str | None:
        if relative not in text_cache:
            inspected = paths.get(relative)
            if inspected is None or not inspected.exists:
                text_cache[relative] = None
            else:
                text_cache[relative] = _read_target(inspected, relative, report)
        return text_cache[relative]

    matched: dict[str, dict[str, object]] = {}
    scan_cache: dict[str, str | None] = {}

    def scan(relative: str) -> str | None:
        # FU-1: marker matching is fence/inline-code-aware.
        if relative not in scan_cache:
            text = read(relative)
            scan_cache[relative] = None if text is None else _marker_scan_text(text)
        return scan_cache[relative]

    for descriptor in _REVISION_MODEL["revision_descriptors"]:
        rules = descriptor["marker_rules"]
        texts = [scan(rule["path"]) for rule in rules]
        if texts and all(
            text is not None and rule["required_text"] in text
            for rule, text in zip(rules, texts, strict=True)
        ):
            matched[descriptor["revision"]] = descriptor

    green = [revision for revision in matched if revision in GREEN_REVISIONS]
    sources = [revision for revision in matched if revision in MIGRATABLE_REVISIONS]

    if green and sources:
        report.add(
            "CONTRACT_PARTIAL_MIGRATION",
            f"AGENTS.md carries mixed revision markers: {', '.join(sorted(matched))}",
            path="AGENTS.md",
            classification="mixed-revision",
            summary="disk state mixes contract revisions",
            evidence=tuple(sorted(matched)),
            action="MERGE_REQUIRED",
        )
        return "partial"

    if green:
        descriptor = matched[green[0]]
        missing = [
            relative
            for relative in descriptor["required_pointer_paths"]
            if paths.get(relative) is None or not paths[relative].exists
        ]
        if missing:
            report.add(
                "CONTRACT_PARTIAL_MIGRATION",
                f"green marker present but required pointers missing: {', '.join(missing)}",
                path=missing[0],
                classification="partial-install",
                summary="green revision with an incomplete pointer set",
                evidence=tuple(missing),
                action="MERGE_REQUIRED",
            )
            return "partial"
        return "green"

    if len(sources) > 1:
        report.add(
            "CONTRACT_PARTIAL_MIGRATION",
            f"AGENTS.md carries multiple legacy revision markers: {', '.join(sorted(sources))}",
            path="AGENTS.md",
            classification="mixed-revision",
            summary="disk state mixes legacy contract revisions",
            evidence=tuple(sorted(sources)),
            action="MERGE_REQUIRED",
        )
        return "partial"

    if sources:
        revision = sources[0]
        descriptor = matched[revision]
        customized: list[str] = []
        untouched: list[str] = []
        agents_text = read("AGENTS.md") or ""
        agents_title = re.match(r"\A# Agent contract — ([^\n]+)\n", agents_text)
        project_name = agents_title.group(1) if agents_title is not None else None
        target_root_name = paths["AGENTS.md"].path.parent.name if paths.get("AGENTS.md") else None
        if project_name != target_root_name:
            project_name = None
        # Descriptor hashes own the pristine bytes. Rendered fields are
        # neutralized only when they match independent target metadata; every
        # other divergence is user customization and fails closed to merge.
        for relative, expected in sorted(descriptor["static_template_hashes"].items()):
            text = read(relative)
            if text is None:
                continue
            target_hash = _hash_static_target(relative, text, project_name)
            (untouched if target_hash == expected else customized).append(relative)
        agents_action = "MERGE_REQUIRED" if "AGENTS.md" in customized else "MIGRATE_REPLACE"
        report.add(
            "CONTRACT_MIGRATION_REQUIRED",
            f"recognized migration source {revision}: run the migration plan; "
            "recognition prevents data loss, it does not certify currency",
            path="AGENTS.md",
            classification="migration-source",
            summary=f"project is on migratable revision {revision}",
            evidence=tuple(f"untouched:{item}" for item in untouched),
            action=agents_action,
        )
        for relative in customized:
            report.add(
                "CONTRACT_MIGRATION_CONFLICT",
                f"{relative}: customized since {revision}; preserved — approved "
                "migration must merge, never overwrite",
                path=relative,
                classification="customized-source",
                summary="customized file conflicts with migration",
                evidence=("hash-mismatch",),
                action="MERGE_REQUIRED",
            )
        return "migration-source"

    agents_text = scan("AGENTS.md")
    if agents_text is not None and any(
        marker in agents_text for marker in KNOWN_CONTRACT_AGENT_MARKERS
    ):
        version_like = re.search(r"(?:dat-kit|MeoLoom) \d+[\w.\-]*", agents_text)
        if version_like:
            report.add(
                "CONTRACT_UNSUPPORTED_REVISION",
                f"unrecognized revision {version_like.group(0)!r}: unsupported-with-"
                "guidance; migrate manually, no automatic mutation",
                path="AGENTS.md",
                classification="unsupported-revision",
                summary="unknown MeoLoom/dat-kit revision",
                evidence=(version_like.group(0),),
                action="MERGE_REQUIRED",
            )
            return "unsupported"
        report.add(
            "CONTRACT_PARTIAL_MIGRATION",
            "recognizable MeoLoom/dat-kit contract without a revision marker: ambiguous; "
            "no automatic mutation",
            path="AGENTS.md",
            classification="ambiguous-no-marker",
            summary="MeoLoom/dat-kit files present without a revision marker",
            evidence=("marker-missing",),
            action="MERGE_REQUIRED",
        )
        return "partial"

    if any(
        (inspected := paths.get(legacy)) is not None and inspected.exists for legacy in LEGACY
    ):
        report.add(
            "CONTRACT_UNSUPPORTED_REVISION",
            "pre-marker dat-kit install recognized: unsupported-with-guidance; "
            "see docs/codex.md, no automatic mutation",
            path=LEGACY[0],
            classification="pre-marker",
            summary="pre-marker dat-kit generation detected",
            evidence=("legacy-artifact",),
            action="MERGE_REQUIRED",
        )
        return "unsupported"

    return "unclassified"


def check_target(target: Path) -> Report:
    report = Report()
    established = _target_root(target, report)
    if established is None:
        return report
    root, root_fingerprint = established

    paths: dict[str, InspectedTargetPath | None] = {}
    for relative in sorted(_inventory()):
        try:
            current_root = root.lstat()
        except OSError:
            current_root = None
        if current_root is None or not _same_path_version(root_fingerprint, current_root):
            if not any(item.code == "UNSAFE_SYMLINK" for item in report.diagnostics):
                report.add(
                    "UNSAFE_SYMLINK",
                    ".: target root changed during inspection",
                    path=".",
                    classification="unsafe-path",
                    summary="target root changed during inspection",
                    evidence=("symlink",),
                    action="BLOCKED_UNSAFE",
                )
            break
        paths[relative] = _target_path(root, relative, report, root_fingerprint)

    for legacy in LEGACY:
        inspected = paths.get(legacy)
        if inspected is not None and inspected.exists:
            report.add(
                "LEGACY_CONTRACT",
                f"{legacy}: migrate manually; see docs/codex.md",
                path=legacy,
                classification="stale-dat-kit-contract",
                summary="legacy dat-kit contract artifact is present",
                evidence=("legacy-artifact",),
                action="MERGE_REQUIRED",
            )

    agents = paths.get("AGENTS.md")
    if agents is not None and agents.exists:
        text = _read_target(agents, "AGENTS.md", report)
        scanned = None if text is None else _marker_scan_text(text)  # FU-1
        if scanned is not None and (
            "single canonical instruction entrypoint" not in scanned
            or not any(revision in scanned for revision in SUPPORTED_CONTRACT_REVISIONS)
        ):
            recognizable = any(marker in scanned for marker in KNOWN_CONTRACT_AGENT_MARKERS)
            report.add(
                "COMPETING_AGENTS",
                "AGENTS.md is not the current canonical contract",
                path="AGENTS.md",
                classification=("stale-dat-kit-contract" if recognizable else "competing-contract"),
                summary="AGENTS.md requires canonical contract reconciliation",
                evidence=(("canonical-marker",) if recognizable else ()),
                action="MERGE_REQUIRED",
            )

    report.revision_state = _classify_target_revision(paths, report)

    for relative, template_relative in CANONICAL_STATIC.items():
        inspected = paths.get(relative)
        if inspected is None or not inspected.exists:
            continue
        text = _read_target(inspected, relative, report)
        if text is None:
            continue
        template_text = normalized(ROOT / template_relative)
        if relative in RETIRED_POINTER_TEMPLATES:
            if text == template_text:
                report.add(
                    "CONTRACT_MIGRATION_REQUIRED",
                    f"{relative} is a retired-generation pointer: replace with "
                    ".cursor/rules/meo-loom.mdc only inside an approved migration plan",
                    path=relative,
                    classification="retire-legacy",
                    summary="typed RETIRE_LEGACY pointer recognized",
                    evidence=("hash-match",),
                    action="RETIRE_LEGACY",
                    template=template_relative,
                )
            elif not any(item.path == relative for item in report.diagnostics):
                report.add(
                    "CONTRACT_MIGRATION_CONFLICT",
                    f"{relative}: customized legacy pointer; preserve and review manually",
                    path=relative,
                    classification="customized-source",
                    summary="customized legacy pointer conflicts with migration",
                    evidence=("hash-mismatch",),
                    action="MERGE_REQUIRED",
                    template=template_relative,
                )
        elif relative in INSPECTED_POINTER_TEMPLATES:
            _add_pointer_findings(text, template_text, relative, template_relative, report)
        elif text != template_text:
            report.add(
                "PARTIAL_INSTALL_MISMATCH",
                f"{relative}: existing canonical file differs from current template",
                path=relative,
                classification="customized-static",
                summary="static workflow differs from the current template",
                evidence=("template-mismatch",),
                action="EXTRACT_THEN_REPLACE",
                template=template_relative,
            )

    rules_relative = "docs/agent-working-rules.md"
    rules = paths.get(rules_relative)
    if rules is not None and rules.exists:
        text = _read_target(rules, rules_relative, report)
        if text is not None and not any(marker in text for marker in WORKING_RULES_MARKERS) and WORKING_RULES_SENTINEL not in text:
            report.add(
                "PARTIAL_INSTALL_MISMATCH",
                "docs/agent-working-rules.md is not a MeoLoom canonical file",
                path=rules_relative,
                classification="project-owned-policy",
                summary="working rules require canonical marker reconciliation",
                evidence=(),
                action="MERGE_REQUIRED",
            )

    for relative in LOCAL_CONFIGS:
        inspected = paths.get(relative)
        if inspected is None or not inspected.exists:
            continue
        text = _read_target(inspected, relative, report)
        if text is None:
            continue
        report.add(
            "RUNTIME_ADAPTER_CONFLICT",
            f"{relative}: inspect and remove policy or machine-local activation manually",
            path=relative,
            classification="runtime-adapter",
            summary="runtime adapter requires manual inspection",
            evidence=_runtime_evidence(root, relative, text),
            action="INSPECT_REMOVE",
        )
    try:
        final_root = root.lstat()
    except OSError:
        final_root = None
    if final_root is None or not _same_path_version(root_fingerprint, final_root):
        if not any(item.code == "UNSAFE_SYMLINK" for item in report.diagnostics):
            report.add(
                "UNSAFE_SYMLINK",
                ".: target root changed during inspection",
                path=".",
                classification="unsafe-path",
                summary="target root changed during inspection",
                evidence=("symlink",),
                action="BLOCKED_UNSAFE",
            )
    if report.revision_state == "green" and report.diagnostics:
        report.revision_state = "partial"
    return report


def registry_json() -> dict[str, object]:
    return {
        "contract_revision": CONTRACT_REVISION,
        "package_version": package_version(),
        "pointers": {name: list(paths) for name, paths in POINTERS.items()},
        "runtimes": list(RUNTIMES),
        "supported_contract_revisions": list(SUPPORTED_CONTRACT_REVISIONS),
        "templates": POINTER_TEMPLATES,
    }


def _action_instruction(action: str) -> str:
    return {
        "EXTRACT_THEN_REPLACE": "EXTRACT_PROJECT_POLICY",
        "MERGE_REQUIRED": "MERGE_CANONICAL_POLICY",
        "INSPECT_REMOVE": "INSPECT_RUNTIME_ADAPTER",
        "RENAME_REQUIRED": "RENAME_PATH",
        "BLOCKED_UNSAFE": "RESOLVE_UNSAFE_PATH",
        "MIGRATE_REPLACE": "MIGRATE_FROM_SOURCE_REVISION",
        "RETIRE_LEGACY": "REMOVE_LEGACY_POINTER",
    }[action]


def migration_plan(report: Report) -> dict[str, object]:
    grouped: dict[str, list[Diagnostic]] = {}
    for item in report.diagnostics:
        grouped.setdefault(item.path, []).append(item)

    steps: list[dict[str, object]] = []
    next_id = 1

    def add_step(instruction: str, paths: list[str], depends_on: list[str], manual: bool) -> str:
        nonlocal next_id
        step_id = f"S{next_id:03d}"
        next_id += 1
        steps.append(
            {
                "id": step_id,
                "instruction": instruction,
                "paths": paths,
                "depends_on": depends_on,
                "manual_review": manual,
            }
        )
        return step_id

    affected_paths = list(grouped)
    inventory_id = add_step("INVENTORY_POLICY", affected_paths, [], True)
    groups: list[dict[str, object]] = []
    preservation: list[dict[str, object]] = []
    unresolved: list[dict[str, object]] = []
    terminal_ids: list[str] = []
    retire_terminals: list[str] = []

    for path, diagnostics in grouped.items():
        action = diagnostics[0].action
        first = add_step(_action_instruction(action), [path], [inventory_id], True)
        step_ids = [first]
        terminal = first
        if action == "EXTRACT_THEN_REPLACE":
            terminal = add_step("REPLACE_FROM_TEMPLATE", [path], [first], True)
            step_ids.append(terminal)
        elif action == "RETIRE_LEGACY":
            retire_terminals.append(first)
        terminal_ids.append(terminal)
        groups.append(
            {
                "path": path,
                "diagnostic_codes": [item.code for item in diagnostics],
                "action": action,
                "step_ids": step_ids,
                "manual_review": True,
            }
        )
        if action in {"MIGRATE_REPLACE", "RETIRE_LEGACY"}:
            method = "BYTE_SNAPSHOT"
            destination = None
            reason = "SOURCE_REVISION" if action == "MIGRATE_REPLACE" else "LEGACY_POINTER"
        elif action in {"EXTRACT_THEN_REPLACE", "MERGE_REQUIRED"}:
            method = "POLICY_INVENTORY"
            destination = "docs/agent-working-rules.md"
            reason = "POLICY_DESTINATION" if diagnostics[0].classification != "competing-contract" else "UNKNOWN_CONTENT"
        elif action == "INSPECT_REMOVE":
            method = "MANUAL_INSPECTION"
            destination = None
            reason = "RUNTIME_DEPENDENCY"
        else:
            method = "BYTE_SNAPSHOT"
            destination = None
            reason = "UNSAFE_PATH"
        preservation.append(
            {"path": path, "method": method, "destination": destination, "step_id": first}
        )
        unresolved.append({"path": path, "reason": reason, "step_id": first})

    if retire_terminals:
        # Add the current pointer once, after every legacy pointer has an
        # approved removal step. Greenfield scaffolding never emits this row.
        add_pointer = add_step(
            "ADD_RULES_POINTER",
            [".cursor/rules/meo-loom.mdc"],
            retire_terminals,
            True,
        )
        terminal_ids = [item for item in terminal_ids if item not in retire_terminals]
        terminal_ids.append(add_pointer)
        for group in groups:
            if group["action"] == "RETIRE_LEGACY":
                group["step_ids"].append(add_pointer)

    add_step("VERIFY_CONTRACT", ["."], terminal_ids or [inventory_id], False)
    return {
        "groups": groups,
        "steps": steps,
        "preservation": preservation,
        "unresolved": unresolved,
    }


def target_json(report: Report, *, mode: str, plan: dict[str, object] | None) -> dict[str, object]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "mode": mode,
        "target": ".",
        "ok": not report.diagnostics,
        "package_version": package_version(),
        "contract_revision": CONTRACT_REVISION,
        "green_revisions": list(GREEN_REVISIONS),
        "migratable_source_revisions": list(MIGRATABLE_REVISIONS),
        "revision_state": getattr(report, "revision_state", "unclassified"),
        "supported_contract_revisions": list(SUPPORTED_CONTRACT_REVISIONS),
        "diagnostics": [item.as_json() for item in report.diagnostics],
        "migration_plan": plan,
    }


def emit_migration_text(report: Report, plan: dict[str, object]) -> int:
    template_by_path = {
        item.path: item.template for item in report.diagnostics if item.template is not None
    }
    print("MIGRATION PLAN (read-only)")
    print("BASELINE")
    print('  python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target .')
    print("DIAGNOSTICS")
    for group in plan["groups"]:
        codes = ", ".join(group["diagnostic_codes"])
        print(f"  {group['path']}: {codes} -> {group['action']}")
    print("PRESERVATION")
    for item in plan["preservation"]:
        destination = item["destination"] or "manual review"
        print(f"  {item['path']}: {item['method']} -> {destination}")
    print("STEPS")
    for step in plan["steps"]:
        paths = ", ".join(step["paths"])
        dependencies = ", ".join(step["depends_on"]) or "none"
        source = ""
        if step["instruction"] == "REPLACE_FROM_TEMPLATE":
            template = template_by_path.get(step["paths"][0])
            source = f" from: {template}" if template else ""
        print(
            f"  {step['id']} {step['instruction']}: {paths}{source} "
            f"(after: {dependencies})"
        )
    print("UNRESOLVED")
    for item in plan["unresolved"]:
        print(f"  {item['path']}: {item['reason']} ({item['step_id']})")
    print("VERIFY")
    print(
        '  python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target . '
        "# expected exit 0 after approved migration"
    )
    return 1 if report.diagnostics else 0


def validate_scorecard(entries: Iterable[dict[str, object]]) -> list[tuple[str, str]]:
    """Validate the append-only v1/v2 boundary and strict v2 evidence shape."""
    result: list[tuple[str, str]] = []
    seen_v2 = False
    for index, entry in enumerate(entries, 1):
        if "schema_version" not in entry:
            if seen_v2:
                result.append(("SCORECARD_V1_AFTER_V2", f"line {index}"))
            continue
        seen_v2 = True
        if not isinstance(entry.get("schema_version"), int) or entry.get("schema_version", 0) < 2:
            result.append(("SCORECARD_SCHEMA_VERSION", f"line {index}"))
        if entry.get("agent_runtime") not in RUNTIMES:
            result.append(("SCORECARD_AGENT_RUNTIME", f"line {index}"))
        for field in ("workflow", "canonical_contract_revision"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                result.append((f"SCORECARD_{field.upper()}", f"line {index}"))
        state = entry.get("git_state")
        if not isinstance(state, dict):
            result.append(("SCORECARD_GIT_STATE", f"line {index}"))
            continue
        for field in ("branch", "head"):
            if state.get(field) is not None and not isinstance(state.get(field), str):
                result.append((f"SCORECARD_GIT_{field.upper()}", f"line {index}"))
        if state.get("dirty") is not None and not isinstance(state.get("dirty"), bool):
            result.append(("SCORECARD_GIT_DIRTY", f"line {index}"))
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, help="read-only brownfield preflight")
    parser.add_argument("--registry-json", action="store_true")
    parser.add_argument("--migration-plan", action="store_true")
    parser.add_argument("--format", choices=("text", "json"))
    args = parser.parse_args(argv)

    if args.registry_json:
        if args.target is not None or args.migration_plan or args.format is not None:
            parser.error("--registry-json is mutually exclusive with target and output modes")
        print(json.dumps(registry_json(), sort_keys=True))
        return 0
    if args.migration_plan and args.target is None:
        parser.error("--migration-plan requires --target")
    if args.format == "json" and args.target is None:
        parser.error("--format json requires --target")

    if args.target is None:
        return check_repo().emit()

    report = check_target(args.target)
    if args.migration_plan:
        plan = migration_plan(report)
        if args.format == "json":
            print(json.dumps(target_json(report, mode="migration-plan", plan=plan), sort_keys=True))
            return 1 if report.diagnostics else 0
        return emit_migration_text(report, plan)
    if args.format == "json":
        print(json.dumps(target_json(report, mode="check", plan=None), sort_keys=True))
        return 1 if report.diagnostics else 0
    return report.emit()


if __name__ == "__main__":
    sys.exit(main())
