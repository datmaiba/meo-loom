#!/usr/bin/env python3
"""MeoLoom registry Catalog (format revision 1, Python standard library only)."""

from __future__ import annotations

import argparse
import copy
from dataclasses import asdict, dataclass
import hashlib
from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping
import unicodedata


BOOTSTRAP = "registry/platform.json"
SUPPORTED_FORMAT_REVISIONS = (1,)
HEX64 = re.compile(r"[0-9a-f]{64}")
STABLE_ID = re.compile(r"[a-z][a-z0-9-]*(?:/[0-9]+)?")
SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
MATERIALIZATION_ACTIONS = {"copy", "render-pointer", "preserve", "RETIRE_LEGACY"}
PRECONDITIONS = {
    "target-absent",
    "target-exact-expected-hash",
    "target-user-owned-preserve",
    "approved-backup-and-exact-hash",
}
LIFECYCLES = {"repo_only", "migration_ready", "scaffold_active", "retired"}
DOMAIN_LIFECYCLES = {"legacy", "active", "retired"}
GOVERNANCE_CLASSES = {"A", "B", "C"}
SLOT_PATHS = (
    "workflow.md",
    "ground-truth.md",
    "gates.md",
    "reviewers.md",
    "deliverables",
    "loop-profile.md",
)


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class FilePlanEntry:
    source_template: str
    target_relative_path: str
    ownership_class: str
    materialization_action: str
    artifact_lifecycle: str
    project_contract_revision: str
    expected_content_hash: str | None
    precondition: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FilePlanEntry":
        return cls(**{field: value[field] for field in cls.__dataclass_fields__})

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FilePlan:
    mode: str
    entries: tuple[FilePlanEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "entries": [entry.as_dict() for entry in self.entries]}


@dataclass(frozen=True)
class VersionTarget:
    path: str
    kind: str
    locator: str
    expected_version: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class CatalogLoadError(RuntimeError):
    def __init__(self, diagnostics: Iterable[Diagnostic]):
        self.diagnostics = tuple(diagnostics)
        super().__init__("; ".join(f"{item.code} {item.path}: {item.message}" for item in self.diagnostics))


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"refusing to follow symlink {path.name!r}")


def _load_json(path: Path) -> Any:
    _reject_symlink(path)
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)


def canonical_relative_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("must be a non-empty POSIX relative path")
    if raw != unicodedata.normalize("NFC", raw):
        raise ValueError("must already be NFC-normalized")
    if any(unicodedata.category(char) == "Cc" for char in raw):
        raise ValueError("contains a Unicode control")
    if any(char in raw for char in '<>:"|?*'):
        raise ValueError("contains a portable-illegal path character")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("contains an empty, dot, or traversal segment")
    for part in parts:
        if part.endswith((" ", ".")):
            raise ValueError("contains a trailing-space/dot alias")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED:
            raise ValueError("contains a Windows reserved device basename")
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or posix.as_posix() != raw:
        raise ValueError("must be canonical and repository-relative")
    return raw


def portable_path_key(raw: Any) -> str:
    return "/".join(part.casefold() for part in canonical_relative_path(raw).split("/"))


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def canonical_file_hash(path: Path) -> str:
    _reject_symlink(path)
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _decode_pointer_token(raw: str) -> str:
    if re.search(r"~(?![01])", raw):
        raise ValueError("malformed RFC 6901 escape")
    return raw.replace("~1", "/").replace("~0", "~")


def resolve_json_pointer(document: Any, pointer: Any) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("locator must be a non-empty RFC 6901 pointer")
    current = document
    for raw in pointer.split("/")[1:]:
        token = _decode_pointer_token(raw)
        if isinstance(current, list):
            if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                raise ValueError("array pointer token must use the RFC 6901 ASCII index grammar")
            index = int(token)
            if index >= len(current):
                raise ValueError("array pointer index is out of range")
            current = current[index]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError("pointer traverses a missing key or scalar")
    return current


def _validate_glob(pattern: Any) -> str:
    if not isinstance(pattern, str) or not pattern or "\\" in pattern or pattern.startswith("/"):
        raise ValueError("glob must be a non-empty relative POSIX pattern")
    if any(unicodedata.category(char) == "Cc" for char in pattern):
        raise ValueError("glob contains a Unicode control")
    parts = pattern.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("glob contains an empty, dot, or traversal segment")
    for index, part in enumerate(parts):
        if part == "**":
            if index != len(parts) - 1:
                raise ValueError("** is allowed only as the terminal segment")
        elif "**" in part or any(char in part for char in "?[]{}") or re.fullmatch(r"[A-Za-z0-9._*-]+", part) is None:
            raise ValueError("glob uses unsupported syntax")
    return pattern


def _glob_matches(pattern: str, path: str) -> bool:
    pattern_parts = _validate_glob(pattern).split("/")
    path_parts = canonical_relative_path(path).split("/")
    if pattern_parts[-1] == "**":
        prefix = pattern_parts[:-1]
        return len(path_parts) >= len(prefix) and all(
            fnmatchcase(path_part, pattern_part)
            # path_parts is intentionally longer than prefix here (the "**" tail
            # matches anything past it) — strict=False documents that on purpose.
            for path_part, pattern_part in zip(path_parts, prefix, strict=False)
        )
    return len(path_parts) == len(pattern_parts) and all(
        fnmatchcase(path_part, pattern_part)
        for path_part, pattern_part in zip(path_parts, pattern_parts, strict=True)
    )


class _Builder:
    BOOTSTRAP_KEYS = {
        "format_revision", "registry_revision", "release_version", "version_targets", "children",
        "canonical_revision", "green_revisions", "migratable_source_revisions", "unsupported_revisions",
        "revision_descriptors", "migration_edges",
    }
    CHILD_KEYS = {"format_revision", "registry_revision", "contract_revision"}
    DOMAIN_KEYS = {
        "domain_id", "contract_revision", "lifecycle", "pack_location", "trigger",
        "required_engine_revision", "gate_authority_ref", "loop_ceiling", "evolution_profile_ref",
    }
    ADAPTER_KEYS = {
        "adapter_id", "aliases", "contract_revision", "host", "lifecycle", "official_facts",
        "plugin_root_rules", "repository_artifact_paths", "project_artifacts", "pointer_semantics",
        "policy_prohibition", "capability_assumptions", "conformance_fixtures", "smoke_command",
        "migration_fixture_refs", "rollback",
    }
    FILE_ENTRY_KEYS = set(FilePlanEntry.__dataclass_fields__)

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.diagnostics: list[Diagnostic] = []

    def add(self, code: str, path: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, path, message))

    def closed(self, value: Any, keys: set[str], path: str) -> bool:
        if not isinstance(value, dict):
            self.add("REGISTRY_TYPE_INVALID", path, "must be an object")
            return False
        for key in sorted(set(value) - keys):
            self.add("REGISTRY_UNKNOWN_FIELD", f"{path}/{key}", "unknown field")
        for key in sorted(keys - set(value)):
            self.add("REGISTRY_REQUIRED_FIELD_MISSING", f"{path}/{key}", "required field is missing")
        return set(value) == keys

    def path(self, value: Any, path: str) -> str | None:
        try:
            return canonical_relative_path(value)
        except ValueError as exc:
            self.add("REGISTRY_PATH_INVALID", path, str(exc))
            return None

    def unique_paths(self, values: Iterable[str], path: str) -> None:
        seen: dict[str, str] = {}
        for value in values:
            try:
                key = portable_path_key(value)
            except ValueError:
                continue
            if key in seen:
                self.add("REGISTRY_PATH_COLLISION", path, f"{value!r} collides with {seen[key]!r}")
            else:
                seen[key] = value

    def load(self) -> "Catalog | tuple[Diagnostic, ...]":
        bootstrap_path = self.root / BOOTSTRAP
        if not bootstrap_path.is_file():
            return (Diagnostic("REGISTRY_BOOTSTRAP_MISSING", BOOTSTRAP, "bootstrap file is missing"),)
        try:
            platform = _load_json(bootstrap_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            return (Diagnostic("REGISTRY_BOOTSTRAP_MALFORMED", BOOTSTRAP, str(exc)),)
        if not isinstance(platform, dict):
            return (Diagnostic("REGISTRY_BOOTSTRAP_MALFORMED", BOOTSTRAP, "root must be an object"),)
        actual_format = platform.get("format_revision")
        if actual_format not in SUPPORTED_FORMAT_REVISIONS:
            return (
                Diagnostic(
                    "REGISTRY_FORMAT_UNSUPPORTED",
                    f"{BOOTSTRAP}#/format_revision",
                    f"actual={actual_format!r} supported={SUPPORTED_FORMAT_REVISIONS}",
                ),
            )
        self._validate_platform(platform)
        if not isinstance(platform.get("children"), list) or not platform["children"]:
            # Fail closed with a guaranteed non-empty diagnostic tuple (never
            # "no Catalog and no diagnostics").
            self.add(
                "REGISTRY_BOOTSTRAP_MALFORMED",
                f"{BOOTSTRAP}#/children",
                "children must be a non-empty array of child references",
            )
            return tuple(self.diagnostics)

        children: dict[str, dict[str, Any]] = {}
        child_paths: dict[str, str] = {}
        for index, reference in enumerate(platform["children"]):
            ref_path = f"{BOOTSTRAP}#/children/{index}"
            if not self.closed(reference, {"kind", "path", "revision"}, ref_path):
                continue
            kind = reference.get("kind")
            relative = self.path(reference.get("path"), f"{ref_path}/path")
            if kind not in {"domains", "adapters", "evolution"}:
                self.add("REGISTRY_CHILD_KIND_INVALID", f"{ref_path}/kind", f"unsupported kind {kind!r}")
                continue
            if relative is None or not relative.startswith("registry/"):
                self.add("REGISTRY_CHILD_PATH_INVALID", f"{ref_path}/path", "child must be below registry/")
                continue
            if kind in children:
                self.add("REGISTRY_CHILD_DUPLICATE", f"{ref_path}/kind", f"duplicate child kind {kind!r}")
                continue
            child_file = self.root / relative
            if not child_file.is_file():
                self.add("REGISTRY_CHILD_MISSING", relative, f"referenced {kind} child is missing")
                continue
            try:
                child = _load_json(child_file)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                self.add("REGISTRY_CHILD_MALFORMED", relative, str(exc))
                continue
            if not isinstance(child, dict):
                self.add("REGISTRY_CHILD_MALFORMED", relative, "root must be an object")
                continue
            if child.get("format_revision") != actual_format:
                self.add(
                    "REGISTRY_ATOMIC_UPGRADE_REQUIRED",
                    f"{relative}#/format_revision",
                    f"bootstrap={actual_format!r} child={child.get('format_revision')!r}",
                )
                continue
            if child.get("registry_revision") != reference.get("revision"):
                self.add(
                    "REGISTRY_CHILD_REVISION_MISMATCH",
                    f"{relative}#/registry_revision",
                    f"expected {reference.get('revision')!r}, got {child.get('registry_revision')!r}",
                )
            children[kind] = child
            child_paths[kind] = relative
        if set(children) != {"domains", "adapters", "evolution"}:
            for kind in sorted({"domains", "adapters", "evolution"} - set(children)):
                self.add("REGISTRY_CHILD_MISSING", f"{BOOTSTRAP}#/children", f"no valid {kind} child loaded")
            return tuple(self.diagnostics)

        snapshots = self._validate_snapshots(platform)
        self._validate_domains(children["domains"], child_paths["domains"])
        self._validate_adapters(children["adapters"], child_paths["adapters"])
        self._validate_evolution(children["evolution"], child_paths["evolution"], children["domains"])
        self._validate_cross_references(platform, children)
        if self.diagnostics:
            return tuple(self.diagnostics)
        # Governed-inventory sweep is intentionally NOT part of load: a stray
        # untracked file must not brick every Catalog consumer. Validation
        # entry points call validate_governed_inventory() explicitly.
        return Catalog(self.root, platform, children, snapshots)

    def _validate_platform(self, value: dict[str, Any]) -> None:
        self.closed(value, self.BOOTSTRAP_KEYS, BOOTSTRAP)
        if not isinstance(value.get("registry_revision"), str) or STABLE_ID.fullmatch(value["registry_revision"]) is None:
            self.add("REGISTRY_REVISION_INVALID", f"{BOOTSTRAP}#/registry_revision", "invalid stable revision")
        if not isinstance(value.get("release_version"), str) or SEMVER.fullmatch(value["release_version"]) is None:
            self.add("REGISTRY_RELEASE_VERSION_INVALID", f"{BOOTSTRAP}#/release_version", "must be SemVer")
        expected = {
            "canonical_revision": "MeoLoom 3.0",
            "green_revisions": ["MeoLoom 3.0"],
            "migratable_source_revisions": ["dat-kit 2.0", "dat-kit 1.16.0"],
        }
        for field, required in expected.items():
            if value.get(field) != required:
                self.add("REGISTRY_PROJECT_REVISION_INVALID", f"{BOOTSTRAP}#/{field}", f"expected {required!r}")
        for field in ("unsupported_revisions", "revision_descriptors", "migration_edges", "version_targets"):
            if not isinstance(value.get(field), list):
                self.add("REGISTRY_TYPE_INVALID", f"{BOOTSTRAP}#/{field}", "must be an array")
        if isinstance(value.get("unsupported_revisions"), list):
            for index, item in enumerate(value["unsupported_revisions"]):
                if not isinstance(item, str) or not item.strip():
                    self.add("REGISTRY_INVALID_VALUE", f"{BOOTSTRAP}#/unsupported_revisions/{index}", "must be a non-empty string")
        if isinstance(value.get("migration_edges"), list):
            edge_ids: set[str] = set()
            for index, edge in enumerate(value["migration_edges"]):
                edge_path = f"{BOOTSTRAP}#/migration_edges/{index}"
                if not self.closed(edge, {"migration_id", "source_revision", "target_revision", "status"}, edge_path):
                    continue
                if edge["status"] not in {"planned", "available", "retired"}:
                    self.add("REGISTRY_INVALID_VALUE", f"{edge_path}/status", f"unknown status {edge['status']!r}")
                if not all(isinstance(edge[key], str) and edge[key].strip() for key in ("migration_id", "source_revision", "target_revision")):
                    self.add("REGISTRY_INVALID_VALUE", edge_path, "edge fields must be non-empty strings")
                elif edge["migration_id"] in edge_ids:
                    self.add("REGISTRY_INVALID_VALUE", f"{edge_path}/migration_id", "duplicate migration_id")
                else:
                    edge_ids.add(edge["migration_id"])
        version_paths: list[str] = []
        if isinstance(value.get("version_targets"), list):
            for index, target in enumerate(value["version_targets"]):
                path = f"{BOOTSTRAP}#/version_targets/{index}"
                if not self.closed(target, {"path", "kind", "locator"}, path):
                    continue
                relative = self.path(target["path"], f"{path}/path")
                if relative is not None:
                    version_paths.append(relative)
                if target["kind"] != "json-pointer":
                    self.add("REGISTRY_VERSION_KIND_INVALID", f"{path}/kind", "format 1 supports json-pointer only")
                if relative is None:
                    continue  # never read a path that failed validation
                try:
                    document = _load_json(self.root / relative)
                    actual = resolve_json_pointer(document, target["locator"])
                    if actual != value.get("release_version"):
                        self.add(
                            "REGISTRY_VERSION_MISMATCH", path,
                            f"target has {actual!r}, expected {value.get('release_version')!r}",
                        )
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    self.add("REGISTRY_VERSION_TARGET_INVALID", path, str(exc))
        self.unique_paths(version_paths, f"{BOOTSTRAP}#/version_targets")
        if isinstance(value.get("revision_descriptors"), list):
            revisions: set[str] = set()
            keys = {
                "revision", "marker_rules", "required_pointer_paths", "static_template_hashes",
                "snapshot_provenance", "support_removal_not_before",
            }
            for index, descriptor in enumerate(value["revision_descriptors"]):
                path = f"{BOOTSTRAP}#/revision_descriptors/{index}"
                if not self.closed(descriptor, keys, path):
                    continue
                revision = descriptor["revision"]
                if revision in revisions:
                    self.add("REGISTRY_REVISION_DUPLICATE", f"{path}/revision", f"duplicate {revision!r}")
                revisions.add(revision)
                marker_rules = descriptor.get("marker_rules")
                if not isinstance(marker_rules, list) or not marker_rules:
                    self.add("REGISTRY_TYPE_INVALID", f"{path}/marker_rules", "must be a non-empty array")
                else:
                    for rule_index, rule in enumerate(marker_rules):
                        rule_path = f"{path}/marker_rules/{rule_index}"
                        if self.closed(rule, {"path", "required_text"}, rule_path):
                            self.path(rule["path"], f"{rule_path}/path")
                            if not isinstance(rule["required_text"], str) or not rule["required_text"].strip():
                                self.add("REGISTRY_INVALID_VALUE", f"{rule_path}/required_text", "must be a non-empty string")
                provenance = descriptor.get("snapshot_provenance")
                if provenance is not None and (
                    not isinstance(provenance, str)
                    or not (provenance.endswith(".json") or "#/" in provenance)
                ):
                    self.add(
                        "REGISTRY_TYPE_INVALID",
                        f"{path}/snapshot_provenance",
                        "must be a snapshot .json path, a #/ fragment reference, or null",
                    )
                pointer_paths = descriptor.get("required_pointer_paths", [])
                if isinstance(pointer_paths, list):
                    for item_index, relative in enumerate(pointer_paths):
                        self.path(relative, f"{path}/required_pointer_paths/{item_index}")
                    self.unique_paths(pointer_paths, f"{path}/required_pointer_paths")
                hashes = descriptor.get("static_template_hashes", {})
                if not isinstance(hashes, dict):
                    self.add("REGISTRY_TYPE_INVALID", f"{path}/static_template_hashes", "must be an object")
                else:
                    for relative, digest in hashes.items():
                        self.path(relative, f"{path}/static_template_hashes/{relative}")
                        if not isinstance(digest, str) or HEX64.fullmatch(digest) is None:
                            self.add("REGISTRY_HASH_INVALID", f"{path}/static_template_hashes/{relative}", "invalid SHA-256")

    def _validate_snapshots(self, platform: dict[str, Any]) -> dict[str, dict[str, Any]]:
        snapshots: dict[str, dict[str, Any]] = {}
        for index, descriptor in enumerate(platform.get("revision_descriptors", [])):
            provenance = descriptor.get("snapshot_provenance")
            if not isinstance(provenance, str) or not provenance.endswith(".json"):
                continue
            path = f"{BOOTSTRAP}#/revision_descriptors/{index}/snapshot_provenance"
            relative = self.path(provenance, path)
            if relative is None:
                continue
            snapshot_path = self.root / relative
            try:
                snapshot = _load_json(snapshot_path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                self.add("REGISTRY_SNAPSHOT_INVALID", relative, str(exc))
                continue
            keys = {"format_revision", "snapshot_revision", "project_contract_revision", "files"}
            if not self.closed(snapshot, keys, relative):
                continue
            if snapshot["format_revision"] != platform["format_revision"]:
                self.add("REGISTRY_ATOMIC_UPGRADE_REQUIRED", f"{relative}#/format_revision", "snapshot format differs")
            if snapshot["project_contract_revision"] != descriptor["revision"]:
                self.add("REGISTRY_SNAPSHOT_REVISION_MISMATCH", f"{relative}#/project_contract_revision", "descriptor differs")
            files = snapshot.get("files")
            if not isinstance(files, list):
                self.add("REGISTRY_TYPE_INVALID", f"{relative}#/files", "must be an array")
                continue
            targets: list[str] = []
            hashes = descriptor.get("static_template_hashes", {})
            # Canonical snapshot rule: only the current revision's
            # snapshot is a scaffold source, so only it verifies against
            # live template bytes. Historical snapshots are immutable
            # records of what already-scaffolded projects have on disk;
            # they verify descriptor<->snapshot consistency instead —
            # live templates move on, the record must not.
            is_canonical = descriptor["revision"] == platform.get("canonical_revision")
            for file_index, entry in enumerate(files):
                entry_path = f"{relative}#/files/{file_index}"
                if not self._validate_file_entry(entry, entry_path):
                    continue
                targets.append(entry["target_relative_path"])
                if not is_canonical:
                    if hashes.get(entry["target_relative_path"]) != entry["expected_content_hash"]:
                        self.add("REGISTRY_SNAPSHOT_HASH_MISMATCH", f"{path.rsplit('/', 1)[0]}/static_template_hashes", entry["target_relative_path"])
                    continue
                source = self.root / entry["source_template"]
                if not source.is_file():
                    self.add("REGISTRY_SOURCE_MISSING", f"{entry_path}/source_template", entry["source_template"])
                    continue
                try:
                    actual_hash = canonical_file_hash(source)
                except (OSError, ValueError) as exc:
                    self.add("REGISTRY_SNAPSHOT_INVALID", f"{entry_path}/source_template", str(exc))
                    continue
                if entry["expected_content_hash"] != actual_hash:
                    self.add("REGISTRY_SNAPSHOT_HASH_MISMATCH", f"{entry_path}/expected_content_hash", source.as_posix())
                if hashes.get(entry["target_relative_path"]) != actual_hash:
                    self.add("REGISTRY_SNAPSHOT_HASH_MISMATCH", f"{path.rsplit('/', 1)[0]}/static_template_hashes", entry["target_relative_path"])
            self.unique_paths(targets, f"{relative}#/files")
            snapshots[descriptor["revision"]] = snapshot
        return snapshots

    def _validate_file_entry(self, entry: Any, path: str) -> bool:
        if not self.closed(entry, self.FILE_ENTRY_KEYS, path):
            return False
        self.path(entry["source_template"], f"{path}/source_template")
        self.path(entry["target_relative_path"], f"{path}/target_relative_path")
        if entry["ownership_class"] not in {"dat-kit", "adapter", "user"}:
            self.add("REGISTRY_FILEPLAN_INVALID", f"{path}/ownership_class", "unknown ownership")
        if entry["materialization_action"] not in MATERIALIZATION_ACTIONS:
            self.add("REGISTRY_FILEPLAN_INVALID", f"{path}/materialization_action", "unknown action")
        if entry["artifact_lifecycle"] not in LIFECYCLES:
            self.add("REGISTRY_FILEPLAN_INVALID", f"{path}/artifact_lifecycle", "unknown lifecycle")
        if entry["precondition"] not in PRECONDITIONS:
            self.add("REGISTRY_FILEPLAN_INVALID", f"{path}/precondition", "unknown precondition")
        digest = entry["expected_content_hash"]
        if digest is not None and (not isinstance(digest, str) or HEX64.fullmatch(digest) is None):
            self.add("REGISTRY_HASH_INVALID", f"{path}/expected_content_hash", "invalid SHA-256")
        if entry["materialization_action"] in {"copy", "RETIRE_LEGACY"} and digest is None:
            self.add("REGISTRY_FILEPLAN_INVALID", f"{path}/expected_content_hash", "action requires a hash")
        if entry["precondition"] == "target-absent" and entry["materialization_action"] in {"preserve", "RETIRE_LEGACY"}:
            self.add("REGISTRY_FILEPLAN_INVALID", f"{path}/precondition", "action/precondition mismatch")
        return True

    def _validate_domains(self, value: dict[str, Any], relative: str) -> None:
        self.closed(value, self.CHILD_KEYS | {"domains"}, relative)
        domains = value.get("domains")
        if not isinstance(domains, list):
            self.add("REGISTRY_TYPE_INVALID", f"{relative}#/domains", "must be an array")
            return
        ids: set[str] = set()
        aliases: dict[str, str] = {}
        destinations: dict[str, str] = {}
        for index, descriptor in enumerate(domains):
            path = f"{relative}#/domains/{index}"
            if not self.closed(descriptor, self.DOMAIN_KEYS, path):
                continue
            domain_id = descriptor["domain_id"]
            if not isinstance(domain_id, str) or STABLE_ID.fullmatch(domain_id) is None:
                self.add("REGISTRY_DOMAIN_ID_INVALID", f"{path}/domain_id", "invalid stable ID")
            elif domain_id in ids:
                self.add("REGISTRY_DOMAIN_ID_DUPLICATE", f"{path}/domain_id", domain_id)
            ids.add(domain_id)
            if descriptor["lifecycle"] not in DOMAIN_LIFECYCLES:
                self.add("REGISTRY_DOMAIN_LIFECYCLE_INVALID", f"{path}/lifecycle", descriptor["lifecycle"])
            pack = self.path(descriptor["pack_location"], f"{path}/pack_location")
            trigger = descriptor.get("trigger")
            if not self.closed(trigger, {"name", "description", "aliases"}, f"{path}/trigger"):
                continue
            name = trigger["name"]
            if not isinstance(name, str) or STABLE_ID.fullmatch(name) is None or "/" in name:
                self.add("REGISTRY_TRIGGER_INVALID", f"{path}/trigger/name", "must be one stable path segment")
                continue  # never raise from load: an invalid name cannot form a destination key
            destination = f"skills/{name}/SKILL.md"
            destination_key = portable_path_key(destination)
            if destination_key in destinations:
                self.add("PROJECTION_DESTINATION_COLLISION", f"{path}/trigger/name", destinations[destination_key])
            destinations[destination_key] = domain_id
            trigger_aliases = trigger.get("aliases", [])
            if not isinstance(trigger_aliases, list):
                self.add("REGISTRY_TYPE_INVALID", f"{path}/trigger/aliases", "must be an array")
                trigger_aliases = []
            for alias in [name, *trigger_aliases]:
                if not isinstance(alias, str) or not alias.strip():
                    self.add("REGISTRY_TRIGGER_INVALID", f"{path}/trigger/aliases", "alias must be non-empty")
                    continue
                key = alias.strip().casefold()
                if key in aliases:
                    self.add("REGISTRY_TRIGGER_ALIAS_COLLISION", f"{path}/trigger/aliases", aliases[key])
                aliases[key] = domain_id
            if descriptor["lifecycle"] == "active" and pack is not None:
                pack_root = self.root / pack
                for slot in SLOT_PATHS:
                    slot_path = pack_root / slot
                    if slot == "deliverables":
                        exists = slot_path.is_dir() and any(slot_path.iterdir())
                    else:
                        exists = slot_path.is_file()
                    if not exists:
                        self.add("DOMAIN_SLOT_MISSING", f"{path}/pack_location", f"{pack}/{slot}")

    def _validate_adapters(self, value: dict[str, Any], relative: str) -> None:
        self.closed(value, self.CHILD_KEYS | {"adapters"}, relative)
        adapters = value.get("adapters")
        if not isinstance(adapters, list):
            self.add("REGISTRY_TYPE_INVALID", f"{relative}#/adapters", "must be an array")
            return
        ids: set[str] = set()
        aliases: dict[str, str] = {}
        all_targets: list[str] = []
        for index, descriptor in enumerate(adapters):
            path = f"{relative}#/adapters/{index}"
            if not self.closed(descriptor, self.ADAPTER_KEYS, path):
                continue
            adapter_id = descriptor["adapter_id"]
            if not isinstance(adapter_id, str) or STABLE_ID.fullmatch(adapter_id) is None:
                self.add("REGISTRY_ADAPTER_ID_INVALID", f"{path}/adapter_id", "invalid stable ID")
            elif adapter_id in ids:
                self.add("REGISTRY_ADAPTER_ID_DUPLICATE", f"{path}/adapter_id", adapter_id)
            ids.add(adapter_id)
            if descriptor["lifecycle"] not in LIFECYCLES:
                self.add("REGISTRY_ADAPTER_LIFECYCLE_INVALID", f"{path}/lifecycle", descriptor["lifecycle"])
            adapter_aliases = descriptor.get("aliases", [])
            if not isinstance(adapter_aliases, list):
                self.add("REGISTRY_TYPE_INVALID", f"{path}/aliases", "must be an array")
                adapter_aliases = []
            for alias in [adapter_id, *adapter_aliases]:
                if not isinstance(alias, str) or not alias.strip():
                    self.add("REGISTRY_ADAPTER_ALIAS_INVALID", f"{path}/aliases", "alias must be non-empty")
                    continue
                key = alias.strip().casefold()
                if key in aliases:
                    self.add("REGISTRY_ADAPTER_ALIAS_COLLISION", f"{path}/aliases", aliases[key])
                aliases[key] = adapter_id
            nested = {
                "plugin_root_rules": {"manifest_paths", "skill_roots", "containment_root", "fresh_session_required"},
                "pointer_semantics": {"canonical_target", "mechanism", "missing_target_behavior"},
                "policy_prohibition": {"canonical_owner", "forbidden_categories"},
                "rollback": {"owned_repository_paths", "owned_project_paths", "removal_precondition", "verification_commands"},
            }
            for field, keys in nested.items():
                self.closed(descriptor.get(field), keys, f"{path}/{field}")
            repo_paths = descriptor.get("repository_artifact_paths", [])
            if isinstance(repo_paths, list):
                for item_index, artifact_path in enumerate(repo_paths):
                    relative_path = self.path(artifact_path, f"{path}/repository_artifact_paths/{item_index}")
                    if relative_path and not (self.root / relative_path).is_file():
                        self.add("REGISTRY_SOURCE_MISSING", f"{path}/repository_artifact_paths/{item_index}", relative_path)
                self.unique_paths(repo_paths, f"{path}/repository_artifact_paths")
            project_artifacts = descriptor.get("project_artifacts", [])
            if not isinstance(project_artifacts, list):
                self.add("REGISTRY_TYPE_INVALID", f"{path}/project_artifacts", "must be an array")
                continue
            artifact_lifecycles: list[str] = []
            for item_index, entry in enumerate(project_artifacts):
                entry_path = f"{path}/project_artifacts/{item_index}"
                if not self._validate_file_entry(entry, entry_path):
                    continue
                artifact_lifecycles.append(entry["artifact_lifecycle"])
                all_targets.append(entry["target_relative_path"])
                source = self.root / entry["source_template"]
                if not source.is_file():
                    self.add("REGISTRY_SOURCE_MISSING", f"{entry_path}/source_template", entry["source_template"])
                elif entry["expected_content_hash"] is not None:
                    try:
                        if canonical_file_hash(source) != entry["expected_content_hash"]:
                            self.add("REGISTRY_SOURCE_HASH_MISMATCH", f"{entry_path}/expected_content_hash", entry["source_template"])
                    except (OSError, ValueError) as exc:
                        self.add("REGISTRY_SOURCE_HASH_MISMATCH", f"{entry_path}/source_template", str(exc))
            if artifact_lifecycles:
                order = {"repo_only": 0, "migration_ready": 1, "scaffold_active": 2, "retired": 3}
                minimum = min(artifact_lifecycles, key=order.__getitem__)
                if descriptor["lifecycle"] != minimum:
                    self.add("REGISTRY_ADAPTER_LIFECYCLE_INVALID", f"{path}/lifecycle", f"expected {minimum!r}")
            facts = descriptor.get("official_facts", [])
            fact_ids: set[str] = set()
            if isinstance(facts, list):
                for fact_index, fact in enumerate(facts):
                    fact_path = f"{path}/official_facts/{fact_index}"
                    if self.closed(fact, {"fact_id", "verified_on", "source_url", "claim", "scope", "reverify_before"}, fact_path):
                        if fact["fact_id"] in fact_ids:
                            self.add("REGISTRY_FACT_ID_DUPLICATE", f"{fact_path}/fact_id", fact["fact_id"])
                        fact_ids.add(fact["fact_id"])
                        if not all(isinstance(fact[field], str) and fact[field].strip() for field in fact):
                            self.add("REGISTRY_FACT_INVALID", fact_path, "fact fields must be non-empty strings")
                        if not fact["source_url"].startswith("https://"):
                            self.add("REGISTRY_FACT_INVALID", f"{fact_path}/source_url", "must use HTTPS")
            for assumption_index, assumption in enumerate(descriptor.get("capability_assumptions", [])):
                assumption_path = f"{path}/capability_assumptions/{assumption_index}"
                if self.closed(assumption, {"assumption_id", "claim", "fact_ref", "required_for"}, assumption_path):
                    if assumption["fact_ref"] not in fact_ids:
                        self.add("REGISTRY_FACT_REF_MISSING", f"{assumption_path}/fact_ref", assumption["fact_ref"])
        self.unique_paths(all_targets, f"{relative}#/adapters/*/project_artifacts")

    def _validate_evolution(self, value: dict[str, Any], relative: str, domains: dict[str, Any]) -> None:
        keys = self.CHILD_KEYS | {
            "governed_roots", "explicit_exclusions", "component_classes", "signals", "authorities", "policies",
        }
        self.closed(value, keys, relative)
        record_shapes = {
            "governed_roots": {"path", "owner"},
            "explicit_exclusions": {"path", "reason", "owner"},
            "component_classes": {"component_id", "path_globs", "owner", "governance_class", "policy_ref"},
            "signals": {"signal_id", "status", "producer", "artifact_or_schema_revision", "quality_limitations", "retention"},
            "authorities": {"authority_id", "role_type", "allowed_decision_classes", "allowed_closer", "appointments", "succession_rule", "approval_evidence_contract", "revocation_rule"},
            "policies": {"policy_id", "revision", "owner", "allowed_classes", "required_signals", "required_gates", "required_reviewers", "closer_authority_ref", "rollback_evidence"},
        }
        for field, shape in record_shapes.items():
            records = value.get(field)
            if not isinstance(records, list):
                self.add("REGISTRY_TYPE_INVALID", f"{relative}#/{field}", "must be an array")
                continue
            for index, record in enumerate(records):
                record_path = f"{relative}#/{field}/{index}"
                if not self.closed(record, shape, record_path):
                    continue
                if field == "authorities":
                    appointments = record.get("appointments")
                    if not isinstance(appointments, list):
                        self.add("REGISTRY_TYPE_INVALID", f"{record_path}/appointments", "must be an array")
                        continue
                    appointment_keys = {
                        "appointment_id", "identity", "role", "effective_from",
                        "revoked_at", "successor_of", "evidence_ref", "evidence_hash",
                    }
                    for item_index, appointment in enumerate(appointments):
                        self.closed(appointment, appointment_keys, f"{record_path}/appointments/{item_index}")
        for field in ("governed_roots", "explicit_exclusions"):
            paths = []
            for index, record in enumerate(value.get(field, [])):
                if isinstance(record, dict) and "path" in record:
                    candidate = self.path(record["path"], f"{relative}#/{field}/{index}/path")
                    if candidate:
                        paths.append(candidate)
            self.unique_paths(paths, f"{relative}#/{field}")
        for index, component in enumerate(value.get("component_classes", [])):
            if not isinstance(component, dict):
                continue
            if component.get("governance_class") not in GOVERNANCE_CLASSES:
                self.add("EVOLUTION_CLASS_INVALID", f"{relative}#/component_classes/{index}/governance_class", "unknown class")
            for glob_index, pattern in enumerate(component.get("path_globs", [])):
                try:
                    _validate_glob(pattern)
                except ValueError as exc:
                    self.add("EVOLUTION_GLOB_INVALID", f"{relative}#/component_classes/{index}/path_globs/{glob_index}", str(exc))

    def _validate_cross_references(self, platform: dict[str, Any], children: dict[str, dict[str, Any]]) -> None:
        evolution = children["evolution"]
        signals = {item.get("signal_id"): item for item in evolution.get("signals", []) if isinstance(item, dict)}
        authorities = {item.get("authority_id"): item for item in evolution.get("authorities", []) if isinstance(item, dict)}
        policies = {item.get("policy_id"): item for item in evolution.get("policies", []) if isinstance(item, dict)}
        for policy in policies.values():
            path = f"registry/evolution.json#/policies/{policy.get('policy_id')}"
            if policy.get("closer_authority_ref") not in authorities:
                self.add("EVOLUTION_AUTHORITY_REQUIRED", f"{path}/closer_authority_ref", "authority is missing")
            for signal_id in policy.get("required_signals", []):
                signal = signals.get(signal_id)
                if signal is None or signal.get("status") == "planned":
                    self.add("EVOLUTION_SIGNAL_UNAVAILABLE", f"{path}/required_signals", str(signal_id))
        for component in evolution.get("component_classes", []):
            policy = policies.get(component.get("policy_ref"))
            if policy is None or policy.get("owner") != component.get("owner"):
                self.add("EVOLUTION_POLICY_MISSING", "registry/evolution.json#/component_classes", str(component.get("component_id")))
        for domain in children["domains"].get("domains", []):
            if domain.get("gate_authority_ref") not in authorities:
                self.add("EVOLUTION_AUTHORITY_REQUIRED", "registry/domains.json#/domains", str(domain.get("domain_id")))
            if domain.get("evolution_profile_ref") not in policies:
                self.add("EVOLUTION_POLICY_MISSING", "registry/domains.json#/domains", str(domain.get("domain_id")))


class Catalog:
    """Immutable-by-copy public registry boundary."""

    def __init__(
        self,
        root: Path,
        platform: dict[str, Any],
        children: dict[str, dict[str, Any]],
        snapshots: dict[str, dict[str, Any]],
    ):
        self.repo_root = root
        self._platform = copy.deepcopy(platform)
        self._children = copy.deepcopy(children)
        self._snapshots = copy.deepcopy(snapshots)

    @classmethod
    def load(cls, repo_root: Path | str) -> "Catalog | tuple[Diagnostic, ...]":
        return _Builder(Path(repo_root)).load()

    @classmethod
    def load_or_raise(cls, repo_root: Path | str) -> "Catalog":
        result = cls.load(repo_root)
        if isinstance(result, tuple):
            raise CatalogLoadError(result)
        return result

    @property
    def registry_revision(self) -> str:
        return self._platform["registry_revision"]

    @property
    def release_version(self) -> str:
        return self._platform["release_version"]

    @property
    def domain_registry_revision(self) -> str:
        return self._children["domains"]["registry_revision"]

    def domains(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(sorted(self._children["domains"]["domains"], key=lambda item: item["domain_id"])))

    def adapters(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(sorted(self._children["adapters"]["adapters"], key=lambda item: item["adapter_id"])))

    def evolution_policy(self) -> dict[str, Any]:
        return copy.deepcopy(self._children["evolution"])

    def version_targets(self) -> tuple[VersionTarget, ...]:
        return tuple(
            VersionTarget(
                path=item["path"], kind=item["kind"], locator=item["locator"], expected_version=self.release_version
            )
            for item in sorted(self._platform["version_targets"], key=lambda target: target["path"])
        )

    def governed_paths(self) -> dict[str, tuple[dict[str, Any], ...]]:
        evolution = self._children["evolution"]
        return {
            "roots": tuple(copy.deepcopy(evolution["governed_roots"])),
            "exclusions": tuple(copy.deepcopy(evolution["explicit_exclusions"])),
            "components": tuple(copy.deepcopy(evolution["component_classes"])),
        }

    def explain_path(self, raw: str) -> dict[str, Any] | Diagnostic:
        try:
            path = canonical_relative_path(raw)
        except ValueError as exc:
            return Diagnostic("REGISTRY_PATH_INVALID", raw, str(exc))
        evolution = self._children["evolution"]
        exclusions = [
            item for item in evolution["explicit_exclusions"]
            if path == item["path"] or path.startswith(item["path"] + "/")
        ]
        if len(exclusions) > 1:
            return Diagnostic("EVOLUTION_EXCLUSION_AMBIGUOUS", path, "multiple exclusions match")
        if exclusions:
            return {"path": path, "classification": "excluded", **copy.deepcopy(exclusions[0])}
        roots = [
            item for item in evolution["governed_roots"]
            if path == item["path"] or path.startswith(item["path"] + "/")
        ]
        if len(roots) != 1:
            code = "EVOLUTION_ORPHAN_PATH" if not roots else "EVOLUTION_OWNERSHIP_AMBIGUOUS"
            return Diagnostic(code, path, f"matched {len(roots)} governed roots")
        components = [
            item for item in evolution["component_classes"]
            if any(_glob_matches(pattern, path) for pattern in item["path_globs"])
        ]
        if len(components) != 1:
            code = "EVOLUTION_ORPHAN_PATH" if not components else "EVOLUTION_OWNERSHIP_AMBIGUOUS"
            return Diagnostic(code, path, f"matched {len(components)} component classes")
        component = components[0]
        policies = {item["policy_id"]: item for item in evolution["policies"]}
        policy = policies[component["policy_ref"]]
        return {
            "path": path,
            "classification": "governed",
            "matched_root": copy.deepcopy(roots[0]),
            "component_id": component["component_id"],
            "owner": component["owner"],
            "governance_class": component["governance_class"],
            "policy_revision": policy["revision"],
            "required_signals": copy.deepcopy(policy["required_signals"]),
            "required_gates": copy.deepcopy(policy["required_gates"]),
            "required_reviewers": copy.deepcopy(policy["required_reviewers"]),
            "closer_authority_ref": policy["closer_authority_ref"],
            "rollback_evidence": policy["rollback_evidence"],
        }

    def _inventory_paths(self) -> tuple[str, ...]:
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_root), "ls-files", "--cached", "--others", "--exclude-standard"],
                text=True, capture_output=True, check=False, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            return tuple(sorted(line for line in result.stdout.splitlines() if line))
        paths = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file() or any(part in {".git", "__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            paths.append(path.relative_to(self.repo_root).as_posix())
        return tuple(sorted(paths))

    def validate_governed_inventory(self) -> tuple[Diagnostic, ...]:
        diagnostics = []
        for path in self._inventory_paths():
            explanation = self.explain_path(path)
            if isinstance(explanation, Diagnostic):
                diagnostics.append(explanation)
        return tuple(diagnostics)

    def scaffold_file_plan(self, mode: str) -> FilePlan:
        if mode not in {"greenfield", "add-missing", "inspect-brownfield", "migrate-approved"}:
            raise ValueError(f"unknown FilePlan mode {mode!r}")
        entries: list[FilePlanEntry] = []
        # Canonical snapshot rule: scaffold rows come only from the
        # canonical revision's snapshot. Historical snapshots stay loaded
        # for migration recognition but never scaffold — flattening every
        # snapshot here made two contract revisions collide on one target.
        canonical_snapshot = self._snapshots.get(self._platform["canonical_revision"])
        if canonical_snapshot is not None:
            entries.extend(FilePlanEntry.from_mapping(item) for item in canonical_snapshot["files"])
        for adapter in self._children["adapters"]["adapters"]:
            entries.extend(FilePlanEntry.from_mapping(item) for item in adapter["project_artifacts"])
        entries.sort(key=lambda item: item.target_relative_path)
        keys = [portable_path_key(item.target_relative_path) for item in entries]
        if len(keys) != len(set(keys)):
            raise CatalogLoadError((Diagnostic("REGISTRY_PATH_COLLISION", "FilePlan", "duplicate target"),))
        if mode == "greenfield":
            entries = [
                item for item in entries
                if item.artifact_lifecycle == "scaffold_active"
                and item.precondition == "target-absent"
                and item.materialization_action in {"copy", "render-pointer"}
            ]
        elif mode == "add-missing":
            entries = [
                item for item in entries
                if item.artifact_lifecycle == "scaffold_active" and item.precondition == "target-absent"
            ]
        return FilePlan(mode, tuple(entries))

    def revision_model(self) -> dict[str, Any]:
        """Project-contract state machine (contract R4): defensive copy."""
        return copy.deepcopy(
            {
                "canonical_revision": self._platform["canonical_revision"],
                "green_revisions": self._platform["green_revisions"],
                "migratable_source_revisions": self._platform["migratable_source_revisions"],
                "unsupported_revisions": self._platform["unsupported_revisions"],
                "revision_descriptors": self._platform["revision_descriptors"],
                "migration_edges": self._platform["migration_edges"],
                "snapshots": self._snapshots,
            }
        )

    def pointer_inventory(self) -> dict[str, tuple[str, ...]]:
        return {
            adapter["adapter_id"]: tuple(
                item["target_relative_path"]
                for item in adapter["project_artifacts"]
                if item["artifact_lifecycle"] == "scaffold_active"
            )
            for adapter in self.adapters()
        }


def _emit_diagnostics(diagnostics: Iterable[Diagnostic], *, json_output: bool) -> int:
    items = tuple(diagnostics)
    if json_output:
        print(json.dumps([item.as_dict() for item in items], ensure_ascii=False, sort_keys=True))
    else:
        for item in items:
            print(f"{item.code}: {item.path}: {item.message}")
    return 1 if items else 0


def main(argv: list[str] | None = None) -> int:
    # cp1252 trap (paid-for lesson): registry data is legitimately non-ASCII;
    # a Windows console must not turn a green result into a UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("kind", choices=("domains", "adapters", "versions"))
    explain_parser = subparsers.add_parser("explain-evolution")
    explain_parser.add_argument("path")
    plan_parser = subparsers.add_parser("file-plan")
    plan_parser.add_argument("mode", choices=("greenfield", "add-missing", "inspect-brownfield", "migrate-approved"))
    args = parser.parse_args(argv)
    loaded = Catalog.load(args.root)
    if isinstance(loaded, tuple):
        return _emit_diagnostics(loaded, json_output=args.json)
    if args.command == "validate":
        # The governed-inventory sweep runs here (validation entry point),
        # not inside Catalog.load — see docs/contracts/registry.md R4.
        return _emit_diagnostics(loaded.validate_governed_inventory(), json_output=args.json)
    if args.command == "list":
        values: Any = {
            "domains": loaded.domains(),
            "adapters": loaded.adapters(),
            "versions": tuple(item.as_dict() for item in loaded.version_targets()),
        }[args.kind]
    elif args.command == "explain-evolution":
        values = loaded.explain_path(args.path)
        if isinstance(values, Diagnostic):
            return _emit_diagnostics((values,), json_output=args.json)
    else:
        values = loaded.scaffold_file_plan(args.mode).as_dict()
    print(json.dumps(values, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
