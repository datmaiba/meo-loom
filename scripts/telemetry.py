#!/usr/bin/env python3
"""Telemetry v3 validation, lifecycle, and local single-writer CLI."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import threading
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
import uuid


EVENT_TYPES = (
    "task_started",
    "task_finished",
    "handoff_created",
    "task_resumed",
    "delegation_started",
    "gate_result",
    "review_result",
    "defect_recorded",
    "rework_recorded",
    "lesson_candidate_recorded",
    "fact_check_recorded",
    "scorecard_imported",
    "benchmark_exported",
)
EVENT_PATH = Path("telemetry/events.jsonl")
MAX_RECORD_BYTES = 65_536

# The generic lifecycle CLI channel. Named so the identity and the revision are
# declared once rather than repeated as literals wherever they are compared.
CLI_PRODUCER_ID = "dat-kit-cli"
CLI_REVISION = "telemetry-cli/1"

STABLE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
STABLE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,511}\Z")
LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?Z\Z"
)
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

TOP_LEVEL_FIELDS = {
    "schema_version",
    "event_id",
    "task_id",
    "event_type",
    "occurred_at",
    "producer",
    "revisions",
    "lineage",
    "source_class",
    "privacy_class",
    "coverage",
    "tokens",
    "elapsed",
    "payload",
}
REVISION_FIELDS = {"domain", "engine", "adapter", "canonical_contract", "profile"}
LINEAGE_FIELDS = {
    "parent_task_id",
    "delegation_id",
    "correction_of",
    "correction_evidence_ref",
}

_WRITE_LOCK = threading.Lock()


class TelemetryError(ValueError):
    """A fail-closed Telemetry v3 diagnostic without rejected-value leakage."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        path: str | None = None,
        event_id: str | None = None,
        line: int | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.path = path
        self.event_id = event_id
        self.line = line
        locations = []
        if path is not None:
            locations.append(f"path={path}")
        if event_id is not None:
            locations.append(f"event_id={event_id}")
        if line is not None:
            locations.append(f"line={line}")
        suffix = f" ({', '.join(locations)})" if locations else ""
        super().__init__(f"{code}: {detail}{suffix}")


CorrectionResolver = Callable[[str, Mapping[str, str]], bool]


class ProducerPolicy:
    """Immutable channel policy for provenance and producer-owned metadata."""

    __slots__ = (
        "correction_resolver",
        "source_classes",
        "verdict_sources",
        "metadata_rules",
        "event_types",
        "_frozen",
    )

    def __init__(
        self,
        *,
        correction_resolver: CorrectionResolver | None = None,
        source_classes: Sequence[str],
        verdict_sources: Sequence[str],
        metadata_rules: Mapping[str, Sequence[str]],
        event_types: Sequence[str] | None = None,
    ) -> None:
        if correction_resolver is not None and not callable(correction_resolver):
            raise TypeError("correction_resolver must be callable or null")
        sources = frozenset(source_classes)
        verdicts = frozenset(verdict_sources)
        if not sources or not sources <= {"runtime", "repository", "human", "legacy_import", "derived"}:
            raise ValueError("source_classes must be a non-empty closed subset")
        if not verdicts <= {"human", "agent", "automation"}:
            raise ValueError("verdict_sources must use the closed verdict-source enum")
        copied_rules: dict[str, tuple[str, ...]] = {}
        for field, rules in metadata_rules.items():
            if not isinstance(field, str) or not field or not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
                raise TypeError("metadata rules must map field names to sequences")
            normalized = tuple(rules)
            if not normalized or any(not isinstance(rule, str) or not rule or rule == "*" for rule in normalized):
                raise ValueError("metadata rules must use exact values or bounded prefixes")
            copied_rules[field] = normalized
        object.__setattr__(self, "correction_resolver", correction_resolver)
        object.__setattr__(self, "source_classes", sources)
        object.__setattr__(self, "verdict_sources", verdicts)
        object.__setattr__(self, "metadata_rules", MappingProxyType(copied_rules))
        if event_types is None:
            owned = None
        else:
            owned = frozenset(event_types)
            if not owned or not owned <= set(EVENT_TYPES):
                raise ValueError("event_types must be a non-empty subset of EVENT_TYPES")
        object.__setattr__(self, "event_types", owned)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("ProducerPolicy is immutable")
        object.__setattr__(self, name, value)

    def owns(self, event_type: str) -> bool:
        """Whether this channel may emit ``event_type``.

        ``event_types=None`` means the policy makes no claim, so the channel is
        unconstrained - the decision is made once, visibly, at the registration
        that grants the channel. A policy cannot exist in a state where somebody
        forgot to declare ownership elsewhere.
        """
        return self.event_types is None or event_type in self.event_types

    def authorizes(self, field: str, value: str) -> bool:
        for rule in self.metadata_rules.get(field, ()):
            if rule.endswith("*") and value.startswith(rule[:-1]):
                return True
            if value == rule:
                return True
        return False


class _ProducerChannel:
    """Internal producer identity resolved from an immutable store registry."""

    __slots__ = ("producer_id", "policy")

    def __init__(
        self,
        producer_id: str,
        policy: ProducerPolicy,
    ) -> None:
        _require_stable_id(producer_id, "producer channel id")
        object.__setattr__(self, "producer_id", producer_id)
        object.__setattr__(self, "policy", policy)


class TelemetryStore:
    """Trusted composition root for one repository and immutable producer registry."""

    __slots__ = ("_repository_root", "_registry", "_writer_seal", "_frozen")

    def __init__(
        self,
        repository_root: Path | str,
        producer_registry: Mapping[str, ProducerPolicy],
    ) -> None:
        if not isinstance(producer_registry, Mapping):
            raise TypeError("producer_registry must be a mapping")
        copied: dict[str, ProducerPolicy] = {}
        for producer_id, policy in producer_registry.items():
            _require_stable_id(producer_id, "registered producer id")
            if type(policy) is not ProducerPolicy:
                raise TypeError("registered producer entries must be ProducerPolicy instances")
            copied[producer_id] = policy
        object.__setattr__(self, "_repository_root", _canonical_root(repository_root))
        object.__setattr__(self, "_registry", MappingProxyType(copied))
        object.__setattr__(self, "_writer_seal", object())
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("TelemetryStore is immutable")
        object.__setattr__(self, name, value)

    def bind(self, producer_id: str) -> "ProducerWriter":
        # Both identity guards live HERE, not in producer_writer, because this is the join
        # the two sanctioned entry points converge on: producer_writer and _cli_writer each
        # end in .bind(), and a store composed directly still has to bind to obtain a
        # writer. A guard on one wrapper protects only the caller its author had in mind.
        #
        # Scope of that, stated rather than overclaimed: bind is the join for the
        # SANCTIONED paths, not the only route to the identity stamp. Private-API,
        # in-process bypasses exist and Python closes none of them, so a seal deters
        # accident, not intent; producer identity is not a security boundary without
        # process separation. ADR 0004 decision 10 enumerates the known bypasses.
        #
        # Ordering consequence of enforcing here: producer_writer canonicalises the
        # repository root (store construction) BEFORE these guards, so
        # producer_writer("/missing", HARVEST) reports TELEMETRY_HISTORY_CORRUPT rather
        # than the harvest refusal. Both are fail-closed; no contract pins the precedence.
        #
        # type(), not isinstance(): a str subclass with a lying __eq__/__hash__
        # satisfies the registry membership test below, and _prepare_event then stamps
        # the object VERBATIM, so the id on disk is its real value. The store hardens
        # the policy side the same way (`type(policy) is not ProducerPolicy`).
        if type(producer_id) is not str:
            _error(
                "producer channel refused: producer id must be exactly str",
                code="TELEMETRY_CORRECTION_UNAUTHORIZED",
                path=str(EVENT_PATH),
            )
        # Unconditional, and BEFORE the registry lookup: T3.12 L606-620 defers HARVEST
        # behind a Host Adapter trust contract and a producer-owned resolver, and
        # L622-627 approves no activation mechanism for it - so registering it must not
        # become one. Compared against the HARVEST_PRODUCER_ID literal, never a tuple
        # position, which a reorder disables silently; the literal's coupling to a real
        # producer id is asserted by a test, where a failure is loud and free.
        if producer_id == HARVEST_PRODUCER_ID:
            _error(
                "producer channel refused: HARVEST has no emit channel, T3.12 L606-620 defers it",
                code="TELEMETRY_CORRECTION_UNAUTHORIZED",
                path=str(EVENT_PATH),
            )
        if producer_id not in self._registry:
            _error("producer channel refused: id is not in the store registry", code="TELEMETRY_CORRECTION_UNAUTHORIZED", path=str(EVENT_PATH))
        return ProducerWriter(self, producer_id, self._writer_seal)


class ProducerWriter:
    """Bound append surface; event callers cannot supply identity or authority."""

    __slots__ = ("_store", "_producer_id", "_frozen")

    def __init__(self, store: TelemetryStore, producer_id: str, seal: object | None = None) -> None:
        if type(store) is not TelemetryStore or seal is not store._writer_seal:
            raise TypeError("ProducerWriter instances are created only by TelemetryStore.bind")
        object.__setattr__(self, "_store", store)
        object.__setattr__(self, "_producer_id", producer_id)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("ProducerWriter is immutable")
        object.__setattr__(self, name, value)

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        # strict_tail=False and corpus_check=None are DELIBERATE, and both were
        # challenged by qa-agent (2026-07-25). Recorded reasoning, because the
        # asymmetry with the lifecycle path looks like an oversight and is not:
        #
        # 1. Truncating an interrupted final record is the SPECIFIED recovery, not
        #    silent data loss - docs/contracts/telemetry-v3.md T3.8 ("Recovery may
        #    truncate only an interrupted final record", :412) and :60 ("recover one
        #    interrupted final record as specified in T3.8"). Setting strict_tail=True
        #    here was tried and reds two ratified tests that pin exactly that
        #    recovery. The generic writer is the recovering writer by design; the
        #    lifecycle CLI opts INTO strict_tail because a raced lifecycle change
        #    must fail rather than append.
        # 2. corpus_check is lifecycle validation, and a producer channel is not the
        #    lifecycle IN GENERAL. Imposing it unconditionally here would make every
        #    producer a lifecycle writer.
        #
        # Residual, accepted and named - and NOT the hypothetical the previous wording
        # implied. security-reviewer round 2 F2: the one channel _PRODUCER_POLICIES
        # registers owns exactly ("task_resumed",), and task_resumed IS lifecycle-
        # validated - _validate_task_sequences orders it, _unmatched_handoffs matches
        # it against its handoff_created, and coverage is recomputed at its append
        # position. So "a caller who hand-builds lifecycle-shaped events" is not an
        # edge case on this surface; it is the ONLY thing this surface can emit today.
        # Such a caller bypasses _validate_lifecycle_corpus and can leave
        # telemetry/events.jsonl TELEMETRY_LIFECYCLE_INVALID with no repair path, since
        # the stream is append-only. The CLI's handoff-resume path DOES validate
        # (_append_lifecycle_event runs the corpus check before reaching _append) and is
        # the supported way in.
        #
        # The fix - pass corpus_check when the bound policy owns a lifecycle event type
        # - is deferred to ADR 0004 follow-up 6 rather than folded here: it changes the
        # append path that four code-reviewer rounds converged on, and the exposure is
        # local-stream integrity on a gitignored file, not disclosure. Owner scope
        # decision, 2026-07-26, recorded rather than left as a silent omission.
        return self._append(event, corpus_check=None, strict_tail=False)

    def _append(
        self,
        event: Mapping[str, Any],
        *,
        corpus_check: Callable[[Sequence[Mapping[str, Any]]], None] | None,
        strict_tail: bool,
    ) -> dict[str, Any]:
        # Event-type ownership is enforced HERE, at the writer, not in any caller.
        # A ProducerPolicy constrains fields, so without this a channel could
        # stamp its identity on any event whose payload happens to touch none of
        # its metadata rules - task_finished being the obvious case. Round 1 of
        # review named producer_writer as public API and an earlier fix guarded
        # only the CLI caller, which left the public path open with a green test
        # over the private one.
        if not isinstance(event, Mapping):
            _error("event must be a mapping")
        # A malformed event_type is a SHAPE defect, so it gets the shape code. An
        # earlier fix put an isinstance guard inside ProducerPolicy.owns, which
        # returned False and therefore reported a malformed envelope as
        # TELEMETRY_CORRECTION_UNAUTHORIZED - the wrong family, and it silently
        # changed an unconstrained policy from "owns everything" to "owns nothing"
        # for bad input. Checked here, before ownership, so `x in frozenset` never
        # sees an unhashable value either. qa-agent regression 2026-07-25.
        if not isinstance(event.get("event_type"), str):
            _error("event_type must be a string")
        # Event-type ownership is a property of the POLICY, so it travels with the
        # registry entry that grants the channel. There is no side map to forget a
        # row in, and no default question: a policy that makes no claim leaves the
        # channel unconstrained, and that is visible at the registration site.
        policy = self._store._registry[self._producer_id]
        if not policy.owns(event.get("event_type")):
            _error(
                "producer channel refused: channel does not own this event type",
                code="TELEMETRY_CORRECTION_UNAUTHORIZED",
                path=str(EVENT_PATH),
            )
        channel = _ProducerChannel(
            self._producer_id,
            self._store._registry[self._producer_id],
        )
        return _append_local_event(
            self._store._repository_root,
            event,
            channel,
            corpus_check=corpus_check,
            strict_tail=strict_tail,
        )


def _error(
    detail: str,
    *,
    code: str = "TELEMETRY_EVENT_INVALID",
    path: str | None = None,
    event_id: str | None = None,
    line: int | None = None,
) -> None:
    raise TelemetryError(code, detail, path=path, event_id=event_id, line=line)


def _closed_object(value: Any, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _error(f"{name} must contain exactly its closed fields")
    return value


def _is_integer(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value > 0 if positive else value >= 0


def _require_stable_id(value: Any, name: str) -> None:
    if not isinstance(value, str) or STABLE_ID.fullmatch(value) is None:
        _error(f"{name} must be a stable ID")


def _require_stable_ref(value: Any, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or STABLE_REF.fullmatch(value) is None:
        _error(
            f"{name} is not allowlisted metadata",
            code="TELEMETRY_PRIVACY_VIOLATION",
        )
    windows = PureWindowsPath(value)
    if PurePosixPath(value).is_absolute() or windows.is_absolute() or windows.drive:
        _error(
            f"{name} must not contain an absolute path",
            code="TELEMETRY_PRIVACY_VIOLATION",
        )


def _require_uuid4(value: Any, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or value != value.lower():
        _error(f"{name} must be a canonical lowercase UUIDv4")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        _error(f"{name} must be a canonical lowercase UUIDv4")
    if parsed.version != 4 or str(parsed) != value or parsed.int == 0:
        _error(f"{name} must be a canonical lowercase UUIDv4")


def _require_timestamp(value: Any) -> None:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        _error("occurred_at must be an RFC 3339 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _error("occurred_at must be an RFC 3339 UTC timestamp")


def _require_sha256(value: Any, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or LOWER_SHA256.fullmatch(value) is None:
        _error(f"{name} must be a lowercase SHA-256")


def _require_path(value: Any, name: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        _error(f"{name} must be an allowlisted repository-relative path", code="TELEMETRY_PRIVACY_VIOLATION")
    if "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        _error(f"{name} must be an allowlisted repository-relative path", code="TELEMETRY_PRIVACY_VIOLATION")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    parts = value.split("/")
    invalid_part = any(
        not part
        or part in {".", ".."}
        or part.endswith((" ", "."))
        or part.split(".", 1)[0].lower() in WINDOWS_RESERVED
        for part in parts
    )
    if posix.is_absolute() or windows.is_absolute() or windows.drive or invalid_part:
        _error(f"{name} must be an allowlisted repository-relative path", code="TELEMETRY_PRIVACY_VIOLATION")


def _require_enum(value: Any, choices: set[str], name: str) -> None:
    if not isinstance(value, str) or value not in choices:
        _error(f"{name} must use its closed enum")


def _require_sorted_unique(
    value: Any,
    name: str,
    validator: Callable[[Any, str], None],
    *,
    maximum: int,
) -> None:
    if not isinstance(value, list) or len(value) > maximum:
        _error(f"{name} must be a bounded sorted array")
    for item in value:
        validator(item, name)
    if value != sorted(value):
        _error(f"{name} must be a bounded sorted array")
    if len(value) != len(set(value)):
        _error(f"{name} must not contain duplicates")


def _validate_revision(value: Any, name: str) -> None:
    revision = _closed_object(value, {"value", "unavailable_reason"}, name)
    present = revision["value"] is not None
    missing = revision["unavailable_reason"] is not None
    if present == missing:
        _error(f"{name} must contain exactly one revision alternative")
    if present:
        _require_stable_ref(revision["value"], f"{name}.value")
    else:
        _require_enum(
            revision["unavailable_reason"],
            {"not_applicable", "not_emitted", "unsupported_host", "legacy_source", "ambiguous"},
            f"{name}.unavailable_reason",
        )


def _validate_coverage(value: Any) -> None:
    coverage = _closed_object(
        value,
        {"status", "missing_event_types", "missing_requirement_refs", "reason"},
        "coverage",
    )
    _require_enum(coverage["status"], {"full", "partial"}, "coverage.status")
    _require_sorted_unique(
        coverage["missing_event_types"],
        "coverage.missing_event_types",
        lambda item, name: _require_enum(item, set(EVENT_TYPES), name),
        maximum=13,
    )
    _require_sorted_unique(
        coverage["missing_requirement_refs"],
        "coverage.missing_requirement_refs",
        _require_stable_id,
        maximum=128,
    )
    if coverage["status"] == "full":
        if coverage["missing_event_types"] or coverage["missing_requirement_refs"] or coverage["reason"] is not None:
            _error("full coverage must have empty missing arrays and null reason")
    else:
        if not (coverage["missing_event_types"] or coverage["missing_requirement_refs"]):
            _error("partial coverage must name missing requirements")
        _require_enum(
            coverage["reason"],
            {
                "completion_only",
                "unsupported_host_start",
                "telemetry_disabled",
                "legacy_import",
                "producer_failure",
                "unresumed_handoff",
                "in_progress",
            },
            "coverage.reason",
        )


def _validate_tokens(value: Any) -> None:
    tokens = _closed_object(value, {"total", "attribution_status", "reason"}, "tokens")
    _require_enum(tokens["attribution_status"], {"exact", "unknown"}, "tokens.attribution_status")
    if tokens["attribution_status"] == "exact":
        if not _is_integer(tokens["total"]) or tokens["reason"] is not None:
            _error("exact tokens require a non-negative total and null reason")
    else:
        if tokens["total"] is not None:
            _error("unknown tokens require a null total")
        _require_enum(
            tokens["reason"],
            {
                "unsupported_provider",
                "missing_timestamp",
                "no_matching_session",
                "multiple_matching_sessions",
                "ambiguous_multi_task_session",
                "not_reported",
                "legacy_source",
                "telemetry_disabled",
            },
            "tokens.reason",
        )


def _validate_elapsed(value: Any) -> None:
    elapsed = _closed_object(value, {"milliseconds", "clock_source", "reason"}, "elapsed")
    if elapsed["milliseconds"] is None:
        if elapsed["clock_source"] != "unknown":
            _error("unknown elapsed time requires clock_source=unknown")
        _require_enum(
            elapsed["reason"],
            {"not_reported", "unsupported_host", "ambiguous", "legacy_source", "telemetry_disabled"},
            "elapsed.reason",
        )
    elif not _is_integer(elapsed["milliseconds"]) or elapsed["clock_source"] not in {"monotonic", "wall"} or elapsed["reason"] is not None:
        _error("measured elapsed time requires non-negative milliseconds, a measured clock, and null reason")


def _payload(value: Any, fields: set[str], event_type: str) -> Mapping[str, Any]:
    return _closed_object(value, fields, f"{event_type}.payload")


def _validate_payload(event_type: str, value: Any) -> None:
    if event_type == "task_started":
        item = _payload(value, {"workflow"}, event_type)
        _require_stable_id(item["workflow"], "workflow")
    elif event_type == "task_finished":
        item = _payload(value, {"outcome", "scorecard_ref"}, event_type)
        _require_enum(item["outcome"], {"completed", "aborted", "unknown"}, "outcome")
        _require_path(item["scorecard_ref"], "scorecard_ref", nullable=True)
    elif event_type == "handoff_created":
        item = _payload(value, {"handoff_ref", "reason"}, event_type)
        _require_path(item["handoff_ref"], "handoff_ref")
        _require_enum(item["reason"], {"context_ceiling", "deliberate_pause", "delegation_brief"}, "reason")
    elif event_type == "task_resumed":
        item = _payload(value, {"handoff_ref", "resumed_from_handoff", "resumed_from_event_id"}, event_type)
        _require_path(item["handoff_ref"], "handoff_ref")
        if item["resumed_from_handoff"] is not True:
            _error("resumed_from_handoff must be literal true")
        _require_uuid4(item["resumed_from_event_id"], "resumed_from_event_id")
    elif event_type == "delegation_started":
        item = _payload(value, {"delegation_id", "child_task_id", "delegated_role", "brief_ref"}, event_type)
        _require_uuid4(item["delegation_id"], "delegation_id")
        _require_uuid4(item["child_task_id"], "child_task_id")
        _require_stable_id(item["delegated_role"], "delegated_role")
        _require_path(item["brief_ref"], "brief_ref")
    elif event_type == "gate_result":
        item = _payload(value, {"gate_id", "outcome", "first_pass", "verdict_source", "evidence_ref"}, event_type)
        _require_stable_id(item["gate_id"], "gate_id")
        _require_enum(item["outcome"], {"pass", "fail", "skipped"}, "outcome")
        if not isinstance(item["first_pass"], bool):
            _error("first_pass must be boolean")
        _require_enum(item["verdict_source"], {"human", "agent", "automation"}, "verdict_source")
        _require_stable_ref(item["evidence_ref"], "evidence_ref", nullable=True)
    elif event_type == "review_result":
        item = _payload(value, {"reviewer_id", "reviewer_class", "round", "verdict", "verdict_source", "finding_count", "evidence_ref"}, event_type)
        _require_stable_id(item["reviewer_id"], "reviewer_id")
        _require_enum(item["reviewer_class"], {"plan", "qa", "software-dev", "knowledge-work", "security", "owner"}, "reviewer_class")
        if not _is_integer(item["round"], positive=True):
            _error("round must be a positive integer")
        _require_enum(item["verdict"], {"approve", "return_to_builder", "phase_done", "revise", "skipped"}, "verdict")
        _require_enum(item["verdict_source"], {"human", "agent", "automation"}, "verdict_source")
        if not _is_integer(item["finding_count"]):
            _error("finding_count must be a non-negative integer")
        _require_stable_ref(item["evidence_ref"], "evidence_ref", nullable=True)
    elif event_type == "defect_recorded":
        item = _payload(value, {"defect_id", "introduced_task", "approving_reviewers", "gate_that_should_have_caught_it", "evidence_ref"}, event_type)
        _require_stable_id(item["defect_id"], "defect_id")
        _require_uuid4(item["introduced_task"], "introduced_task", nullable=True)
        _require_sorted_unique(item["approving_reviewers"], "approving_reviewers", _require_stable_id, maximum=64)
        _require_stable_id(item["gate_that_should_have_caught_it"], "gate_that_should_have_caught_it")
        _require_stable_ref(item["evidence_ref"], "evidence_ref")
    elif event_type == "rework_recorded":
        item = _payload(value, {"cause_event_id", "round", "reason", "evidence_ref"}, event_type)
        _require_uuid4(item["cause_event_id"], "cause_event_id")
        if not _is_integer(item["round"], positive=True):
            _error("round must be a positive integer")
        _require_enum(item["reason"], {"gate_failure", "review_finding", "spec_correction", "other"}, "reason")
        _require_stable_ref(item["evidence_ref"], "evidence_ref", nullable=True)
    elif event_type == "lesson_candidate_recorded":
        item = _payload(value, {"kit_facing", "root_cause_ref", "candidate_ref"}, event_type)
        if not isinstance(item["kit_facing"], bool):
            _error("kit_facing must be boolean")
        _require_stable_ref(item["root_cause_ref"], "root_cause_ref")
        _require_stable_ref(item["candidate_ref"], "candidate_ref")
    elif event_type == "fact_check_recorded":
        item = _payload(value, {"gate_id", "verdict", "verdict_source", "finding_count", "failure_classes", "evidence_ref"}, event_type)
        _require_stable_id(item["gate_id"], "gate_id")
        _require_enum(item["verdict"], {"sourced", "return_to_builder"}, "verdict")
        _require_enum(item["verdict_source"], {"human", "agent", "automation"}, "verdict_source")
        if not _is_integer(item["finding_count"]):
            _error("finding_count must be a non-negative integer")
        failures = {
            "unsupported_claim", "weaker_than_claim", "contradiction", "unreliable_source",
            "stale_source", "inadequate_coverage", "prose_contradiction",
        }
        _require_sorted_unique(item["failure_classes"], "failure_classes", lambda entry, name: _require_enum(entry, failures, name), maximum=7)
        if item["verdict"] == "sourced" and (item["finding_count"] != 0 or item["failure_classes"]):
            _error("sourced fact checks must have no findings")
        if item["verdict"] == "return_to_builder" and (item["finding_count"] <= 0 or not item["failure_classes"]):
            _error("return_to_builder fact checks must name findings")
        _require_stable_ref(item["evidence_ref"], "evidence_ref")
    elif event_type == "scorecard_imported":
        item = _payload(value, {"source_path", "source_record_ordinal", "source_record_hash", "source_record_ref"}, event_type)
        if item["source_path"] != "benchmarks/scorecard.jsonl":
            _error("source_path must be the closed scorecard path")
        if not _is_integer(item["source_record_ordinal"], positive=True):
            _error("source_record_ordinal must be a positive integer")
        _require_sha256(item["source_record_hash"], "source_record_hash")
        _require_stable_ref(item["source_record_ref"], "source_record_ref")
    elif event_type == "benchmark_exported":
        item = _payload(value, {"export_batch_id", "target_path", "prior_hash", "exported_event_ids"}, event_type)
        _require_uuid4(item["export_batch_id"], "export_batch_id")
        _require_enum(item["target_path"], {"benchmarks/telemetry-v3.jsonl", "benchmarks/defects.jsonl"}, "target_path")
        _require_sha256(item["prior_hash"], "prior_hash", nullable=True)
        _require_sorted_unique(item["exported_event_ids"], "exported_event_ids", _require_uuid4, maximum=256)
    else:
        _error("event_type must use the closed Telemetry v3 enum")


def validate_event(value: Mapping[str, Any]) -> None:
    """Validate one already-persisted Telemetry v3 event."""

    event = _closed_object(value, TOP_LEVEL_FIELDS, "event")
    if event["schema_version"] != 3 or isinstance(event["schema_version"], bool):
        _error("schema_version must be integer literal 3", code="TELEMETRY_SCHEMA_UNSUPPORTED")
    _require_uuid4(event["event_id"], "event_id")
    _require_uuid4(event["task_id"], "task_id")
    _require_enum(event["event_type"], set(EVENT_TYPES), "event_type")
    _require_timestamp(event["occurred_at"])

    producer = _closed_object(event["producer"], {"id", "revision"}, "producer")
    _require_stable_id(producer["id"], "producer.id")
    _require_stable_ref(producer["revision"], "producer.revision")

    revisions = _closed_object(event["revisions"], REVISION_FIELDS, "revisions")
    for name in sorted(REVISION_FIELDS):
        _validate_revision(revisions[name], f"revisions.{name}")

    lineage = _closed_object(event["lineage"], LINEAGE_FIELDS, "lineage")
    _require_uuid4(lineage["parent_task_id"], "lineage.parent_task_id", nullable=True)
    _require_uuid4(lineage["delegation_id"], "lineage.delegation_id", nullable=True)
    if (lineage["parent_task_id"] is None) != (lineage["delegation_id"] is None):
        _error("parent_task_id and delegation_id must be present together")
    _require_uuid4(lineage["correction_of"], "lineage.correction_of", nullable=True)
    _require_stable_ref(lineage["correction_evidence_ref"], "lineage.correction_evidence_ref", nullable=True)
    if (lineage["correction_of"] is None) != (lineage["correction_evidence_ref"] is None):
        _error("correction lineage fields must be present together", code="TELEMETRY_CORRECTION_INVALID")

    if not isinstance(event["source_class"], str) or event["source_class"] not in {"runtime", "repository", "human", "legacy_import", "derived"}:
        _error("source_class is not allowlisted", code="TELEMETRY_PRIVACY_VIOLATION")
    if not isinstance(event["privacy_class"], str) or event["privacy_class"] not in {"public", "project", "local_private"}:
        _error("privacy_class is not allowlisted", code="TELEMETRY_PRIVACY_VIOLATION")
    _validate_coverage(event["coverage"])
    _validate_tokens(event["tokens"])
    _validate_elapsed(event["elapsed"])
    _validate_payload(event["event_type"], event["payload"])

    encoded = _encode_validated_event(event)
    if len(encoded) > MAX_RECORD_BYTES:
        _error("encoded event exceeds 65,536 bytes")


def _encode_validated_event(value: Mapping[str, Any]) -> bytes:
    try:
        return (
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, UnicodeError):
        _error("event is not encodable as one UTF-8 JSON object")


def encode_event(value: Mapping[str, Any]) -> bytes:
    validate_event(value)
    return _encode_validated_event(value)


def _prepare_event(value: Mapping[str, Any], channel: _ProducerChannel) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error("event input must be an object")
    prepared = copy.deepcopy(value)
    producer = prepared.get("producer")
    if not isinstance(producer, dict) or set(producer) != {"revision"}:
        _error("event input accepts producer.revision only; producer.id is injected")
    _require_stable_ref(producer["revision"], "producer.revision")
    prepared["producer"] = {"id": channel.producer_id, "revision": producer["revision"]}
    validate_event(prepared)
    _enforce_producer_policy(prepared, channel.policy)
    return prepared


def _metadata_values(event: Mapping[str, Any]) -> list[tuple[str, str]]:
    values = [("producer.revision", event["producer"]["revision"])]
    for revision_name, revision in event["revisions"].items():
        if revision["value"] is not None:
            values.append((f"revisions.{revision_name}.value", revision["value"]))
    for requirement in event["coverage"]["missing_requirement_refs"]:
        values.append(("coverage.missing_requirement_refs", requirement))
    correction_ref = event["lineage"]["correction_evidence_ref"]
    if correction_ref is not None:
        values.append(("lineage.correction_evidence_ref", correction_ref))

    metadata_fields = {
        "workflow",
        "delegated_role",
        "gate_id",
        "evidence_ref",
        "reviewer_id",
        "defect_id",
        "approving_reviewers",
        "gate_that_should_have_caught_it",
        "root_cause_ref",
        "candidate_ref",
        "source_record_ref",
        # handoff_ref is the schema's only free-text-ish field (any repo-relative
        # path, 1-512 chars) and it rides the handoff -> resume flow straight into
        # the committed public corpus. Policy-bounding it is the difference between
        # "a path" and "a path in handoffs/".
        "handoff_ref",
    }
    for field, value in event["payload"].items():
        if field not in metadata_fields or value is None:
            continue
        if isinstance(value, list):
            values.extend((f"payload.{field}", item) for item in value)
        else:
            values.append((f"payload.{field}", value))
    return values


def _enforce_producer_policy(event: Mapping[str, Any], policy: ProducerPolicy) -> None:
    if event["source_class"] not in policy.source_classes:
        _error("source_class is not authorized for this producer", code="TELEMETRY_PRIVACY_VIOLATION")
    verdict_source = event["payload"].get("verdict_source")
    if verdict_source is not None and verdict_source not in policy.verdict_sources:
        _error("verdict_source is not authorized for this producer", code="TELEMETRY_PRIVACY_VIOLATION")
    for field, value in _metadata_values(event):
        if not policy.authorizes(field, value):
            _error(f"{field} is outside the producer-owned metadata namespace", code="TELEMETRY_PRIVACY_VIOLATION")


def _duplicate_object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _parse_line(raw: bytes, *, path: str, line: int) -> dict[str, Any]:
    if len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n"):
        _error("history record boundary is invalid", code="TELEMETRY_HISTORY_CORRUPT", path=path, line=line)
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=_duplicate_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        _error("history record is not a complete UTF-8 JSON object", code="TELEMETRY_HISTORY_CORRUPT", path=path, line=line)
    if not isinstance(value, dict):
        _error("history record is not an object", code="TELEMETRY_HISTORY_CORRUPT", path=path, line=line)
    schema_version = value.get("schema_version")
    if isinstance(schema_version, int) and not isinstance(schema_version, bool) and schema_version > 3:
        raise TelemetryError(
            "TELEMETRY_SCHEMA_UNSUPPORTED",
            "stored event uses an unsupported future schema version",
            path=path,
            line=line,
        )
    try:
        validate_event(value)
    except TelemetryError as diagnostic:
        if diagnostic.code == "TELEMETRY_SCHEMA_UNSUPPORTED":
            raise TelemetryError(
                "TELEMETRY_SCHEMA_UNSUPPORTED",
                "stored event uses an unsupported schema version",
                path=path,
                line=line,
            ) from None
        candidate_event_id = value.get("event_id")
        safe_event_id = None
        try:
            _require_uuid4(candidate_event_id, "event_id")
            safe_event_id = candidate_event_id
        except TelemetryError:
            pass
        raise TelemetryError(
            "TELEMETRY_HISTORY_CORRUPT",
            f"stored event fails {diagnostic.code}",
            path=path,
            event_id=safe_event_id,
            line=line,
        ) from None
    return value


def _split_history(raw: bytes, *, path: str) -> tuple[list[dict[str, Any]], int]:
    last_boundary = raw.rfind(b"\n") + 1
    complete = raw[:last_boundary]
    events = [
        _parse_line(line, path=path, line=index)
        for index, line in enumerate(complete.splitlines(keepends=True), 1)
    ]
    _validate_existing_corpus(events, path=path)
    return events, last_boundary


def _privacy_rank(value: str) -> int:
    return {"public": 0, "project": 1, "local_private": 2}[value]


def _validate_correction_shape(correction: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    immutable_paths = (
        ("schema_version",),
        ("task_id",),
        ("event_type",),
        ("source_class",),
        ("producer", "id"),
        ("lineage", "parent_task_id"),
        ("lineage", "delegation_id"),
        ("payload",),
    )
    for path in immutable_paths:
        left: Any = correction
        right: Any = target
        for part in path:
            left = left[part]
            right = right[part]
        if left != right:
            _error("correction changes an immutable field", code="TELEMETRY_CORRECTION_INVALID", event_id=correction["event_id"])
    if _privacy_rank(correction["privacy_class"]) < _privacy_rank(target["privacy_class"]):
        _error("correction loosens privacy", code="TELEMETRY_CORRECTION_INVALID", event_id=correction["event_id"])


def _validate_existing_corpus(events: Sequence[Mapping[str, Any]], *, path: str) -> None:
    by_id: dict[str, Mapping[str, Any]] = {}
    for line, event in enumerate(events, 1):
        event_id = event["event_id"]
        if event_id in by_id:
            raise TelemetryError("TELEMETRY_HISTORY_CORRUPT", "duplicate event ID in history", path=path, event_id=event_id, line=line)
        correction_of = event["lineage"]["correction_of"]
        if correction_of is not None:
            target = by_id.get(correction_of)
            if target is None or correction_of == event_id:
                raise TelemetryError("TELEMETRY_HISTORY_CORRUPT", "correction target is not an earlier event", path=path, event_id=event_id, line=line)
            try:
                _validate_correction_shape(event, target)
            except TelemetryError:
                raise TelemetryError("TELEMETRY_HISTORY_CORRUPT", "stored correction is invalid", path=path, event_id=event_id, line=line) from None
        by_id[event_id] = event


def _authorize_correction(
    event: Mapping[str, Any],
    encoded: bytes,
    existing: Sequence[Mapping[str, Any]],
    channel: _ProducerChannel,
) -> None:
    target_id = event["lineage"]["correction_of"]
    if target_id is None:
        return
    by_id = {item["event_id"]: item for item in existing}
    target = by_id.get(target_id)
    if target is None or target_id == event["event_id"]:
        _error("correction target must be an earlier event", code="TELEMETRY_CORRECTION_INVALID", event_id=event["event_id"])
    if target["producer"]["id"] != channel.producer_id:
        _error("correction arrived through a different producer channel", code="TELEMETRY_CORRECTION_UNAUTHORIZED", event_id=event["event_id"])
    _validate_correction_shape(event, target)
    if channel.policy.correction_resolver is None:
        _error("correction lacks channel authority", code="TELEMETRY_CORRECTION_UNAUTHORIZED", event_id=event["event_id"])

    root = target
    seen = {event["event_id"]}
    while root["lineage"]["correction_of"] is not None:
        current_id = root["event_id"]
        if current_id in seen:
            _error("correction chain is cyclic", code="TELEMETRY_CORRECTION_INVALID", event_id=event["event_id"])
        seen.add(current_id)
        parent = by_id.get(root["lineage"]["correction_of"])
        if parent is None:
            _error("correction chain is incomplete", code="TELEMETRY_CORRECTION_INVALID", event_id=event["event_id"])
        root = parent

    binding = {
        "root_event_id": root["event_id"],
        "target_event_id": target_id,
        "correcting_event_id": event["event_id"],
        "record_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    try:
        authorized = channel.policy.correction_resolver(event["lineage"]["correction_evidence_ref"], binding)
    except Exception:
        authorized = False
    if authorized is not True:
        _error("correction evidence binding was rejected", code="TELEMETRY_CORRECTION_UNAUTHORIZED", event_id=event["event_id"])


def _is_linklike(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & REPARSE_ATTRIBUTE)


def _canonical_root(root: Path | str) -> Path:
    supplied = Path(root)
    if not supplied.is_absolute():
        _error("repository root must be absolute", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH))
    try:
        info = supplied.lstat()
    except FileNotFoundError:
        _error("repository root is unavailable", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH))
    except OSError:
        _error("repository root is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=str(EVENT_PATH))
    try:
        resolved = supplied.resolve(strict=True)
    except OSError:
        _error("repository root is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=str(EVENT_PATH))
    if _is_linklike(info) or not stat.S_ISDIR(info.st_mode) or os.path.normcase(str(supplied)) != os.path.normcase(str(resolved)):
        _error("repository root is not canonical", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH))
    return resolved


def _verify_parent(root: Path, parent: Path, *, create: bool, path: str = str(EVENT_PATH)) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError:
        _error("event path escapes the repository root", code="TELEMETRY_HISTORY_CORRUPT", path=path)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if not create:
                _error("event parent path is missing", code="TELEMETRY_HISTORY_CORRUPT", path=path)
            try:
                current.mkdir(mode=0o700)
            except OSError:
                _error("event parent path is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
            info = current.lstat()
        except OSError:
            _error("event parent path is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
        if _is_linklike(info) or not stat.S_ISDIR(info.st_mode):
            _error("event parent path is link-like or non-directory", code="TELEMETRY_HISTORY_CORRUPT", path=path)
        try:
            if not current.resolve(strict=True).is_relative_to(root):
                _error("event parent path escapes the repository root", code="TELEMETRY_HISTORY_CORRUPT", path=path)
        except OSError:
            _error("event parent containment is ambiguous", code="TELEMETRY_HISTORY_CORRUPT", path=path)


def _verify_target_before_open(target: Path, *, path: str = str(EVENT_PATH)) -> None:
    try:
        info = target.lstat()
    except FileNotFoundError:
        return
    except OSError:
        _error("event target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
    if _is_linklike(info) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _error("event target must be one unlinked regular file", code="TELEMETRY_HISTORY_CORRUPT", path=path)


def _handle_identity(fd: int, target: Path, *, path: str = str(EVENT_PATH)) -> tuple[int, int]:
    try:
        handle = os.fstat(fd)
        path_info = target.lstat()
    except OSError:
        _error("event target identity is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
    if (
        _is_linklike(path_info)
        or not stat.S_ISREG(handle.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or handle.st_nlink != 1
        or path_info.st_nlink != 1
        or not os.path.samestat(handle, path_info)
    ):
        _error("event target identity changed", code="TELEMETRY_HISTORY_CORRUPT", path=path)
    return handle.st_dev, handle.st_ino


def _read_fd(fd: int, *, path: str) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    pending = 0
    while True:
        chunk = os.read(fd, min(1024 * 1024, MAX_RECORD_BYTES + 1 - pending))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        start = 0
        while True:
            boundary = chunk.find(b"\n", start)
            if boundary < 0:
                pending += len(chunk) - start
                if pending > MAX_RECORD_BYTES:
                    _error("history record exceeds 65,536 bytes", code="TELEMETRY_HISTORY_CORRUPT", path=path)
                break
            record_bytes = pending + boundary - start + 1
            if record_bytes > MAX_RECORD_BYTES:
                _error("history record exceeds 65,536 bytes", code="TELEMETRY_HISTORY_CORRUPT", path=path)
            pending = 0
            start = boundary + 1


def _append_local_event(
    repository_root: Path | str,
    event: Mapping[str, Any],
    channel: _ProducerChannel,
    *,
    corpus_check: Callable[[Sequence[Mapping[str, Any]]], None] | None = None,
    strict_tail: bool = False,
) -> dict[str, Any]:
    """Validate and append one event to the fixed local Telemetry v3 stream."""

    if type(channel) is not _ProducerChannel:
        _error("producer channel capability is invalid", code="TELEMETRY_CORRECTION_UNAUTHORIZED", path=str(EVENT_PATH))
    root = _canonical_root(repository_root)
    target = root / EVENT_PATH

    with _WRITE_LOCK:
        try:
            prepared = _prepare_event(event, channel)
        except TelemetryError as diagnostic:
            raise TelemetryError(diagnostic.code, diagnostic.detail, path=str(EVENT_PATH)) from None
        encoded = _encode_validated_event(prepared)
        _verify_parent(root, target.parent, create=True)
        _verify_target_before_open(target)
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except OSError:
            _error("event target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=str(EVENT_PATH))
        try:
            identity = _handle_identity(fd, target)
            raw = _read_fd(fd, path=str(EVENT_PATH))
            existing, complete_bytes = _split_history(raw, path=str(EVENT_PATH))
            if strict_tail and complete_bytes != len(raw):
                _error(
                    "lifecycle append refuses a raced interrupted record tail",
                    code="TELEMETRY_HISTORY_CORRUPT",
                    path=str(EVENT_PATH),
                    event_id=prepared["event_id"],
                )
            if corpus_check is not None:
                corpus_check(existing)
            if any(item["event_id"] == prepared["event_id"] for item in existing):
                _error("event ID already exists", code="TELEMETRY_DUPLICATE_EVENT_ID", path=str(EVENT_PATH), event_id=prepared["event_id"])
            _authorize_correction(prepared, encoded, existing, channel)

            _verify_parent(root, target.parent, create=False)
            if _handle_identity(fd, target) != identity:
                _error("event target identity changed before append", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH), event_id=prepared["event_id"])
            if complete_bytes != len(raw):
                os.ftruncate(fd, complete_bytes)
                os.lseek(fd, 0, os.SEEK_END)
            written = os.write(fd, encoded)
            _verify_parent(root, target.parent, create=False)
            if _handle_identity(fd, target) != identity:
                _error("event target identity changed after append", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH), event_id=prepared["event_id"])
            if written <= 0 or written != len(encoded):
                os.fsync(fd)
                _error("append did not write one complete record", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH), event_id=prepared["event_id"])
            os.fsync(fd)
            _verify_parent(root, target.parent, create=False)
            if _handle_identity(fd, target) != identity:
                _error("event target identity changed after append", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH), event_id=prepared["event_id"])
        finally:
            os.close(fd)
    return prepared


def validate_local_events(repository_root: Path | str) -> list[dict[str, Any]]:
    """Read and validate the complete local stream without mutating it."""

    root = _canonical_root(repository_root)
    target = root / EVENT_PATH
    # Path safety begins with lstat: Path.exists() follows links, so a
    # dangling link-like parent would be misreported as an empty corpus.
    try:
        parent_info = target.parent.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        _error("event parent path is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=str(EVENT_PATH))
    if _is_linklike(parent_info) or not stat.S_ISDIR(parent_info.st_mode):
        _error("event parent path is link-like or non-directory", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH))
    _verify_parent(root, target.parent, create=False)
    _verify_target_before_open(target)
    try:
        target.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        _error("event target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=str(EVENT_PATH))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError:
        _error("event target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=str(EVENT_PATH))
    try:
        identity = _handle_identity(fd, target)
        raw = _read_fd(fd, path=str(EVENT_PATH))
        events, complete_bytes = _split_history(raw, path=str(EVENT_PATH))
        _verify_parent(root, target.parent, create=False)
        if _handle_identity(fd, target) != identity:
            _error("event target identity changed while validating", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH))
        if complete_bytes != len(raw):
            _error("event stream ends with an interrupted record", code="TELEMETRY_HISTORY_CORRUPT", path=str(EVENT_PATH))
        return events
    finally:
        os.close(fd)


_COVERAGE_REASON_PRIORITY = (
    "telemetry_disabled",
    "legacy_import",
    "producer_failure",
    "unresumed_handoff",
    "unsupported_host_start",
    "completion_only",
)
_EXPLICIT_TERMINAL_REASONS = {
    "telemetry_disabled",
    "legacy_import",
    "producer_failure",
    "unsupported_host_start",
}
_CLI_VERDICT_SOURCE = {
    "gate_result": "automation",
    "review_result": "agent",
    "fact_check_recorded": "human",
}
_CLI_METADATA_RULES = {
    "producer.revision": (CLI_REVISION,),
    "coverage.missing_requirement_refs": ("handoff:*",),
    "payload.workflow": ("build-loop", "knowledge-work", "other"),
    "payload.delegated_role": ("role:*",),
    "payload.gate_id": ("gate:*",),
    # See the note on handoff_ref in _metadata_values: bounding it to the
    # handoffs/ tree stops arbitrary repo-relative paths reaching the committed
    # public corpus through the handoff -> resume flow.
    "payload.handoff_ref": ("handoffs/*",),
    "payload.evidence_ref": ("evidence:*",),
    "payload.reviewer_id": ("reviewer:*",),
    "payload.defect_id": ("defect:*",),
    "payload.approving_reviewers": ("reviewer:*",),
    "payload.gate_that_should_have_caught_it": ("gate:*",),
    "payload.root_cause_ref": ("evidence:*",),
    "payload.candidate_ref": ("evidence:*",),
    "payload.source_record_ref": ("scorecard:*",),
}


def _lifecycle_error(detail: str) -> None:
    _error(detail, code="TELEMETRY_LIFECYCLE_INVALID", path=str(EVENT_PATH))


def _originals(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [event for event in events if event["lineage"]["correction_of"] is None]


def _task_originals(
    events: Sequence[Mapping[str, Any]], task_id: str
) -> list[Mapping[str, Any]]:
    return [event for event in _originals(events) if event["task_id"] == task_id]


def _select_coverage_reason(reasons: set[str]) -> str | None:
    return next((reason for reason in _COVERAGE_REASON_PRIORITY if reason in reasons), None)


def _unmatched_handoffs(task_events: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    unmatched: dict[str, Mapping[str, Any]] = {}
    for event in task_events:
        if event["event_type"] == "handoff_created" and event["payload"]["reason"] != "delegation_brief":
            unmatched[event["event_id"]] = event
        elif event["event_type"] == "task_resumed":
            unmatched.pop(event["payload"]["resumed_from_event_id"], None)
    return unmatched


def build_resume_linkage(
    events: Sequence[Mapping[str, Any]], task_id: str
) -> dict[str, Any]:
    """Derive the linkage-correct ``task_resumed`` inputs for ``task_id``.

    Reads an already-validated event stream and returns
    ``{"task_id", "payload", "parent_task_id", "delegation_id"}``. ``payload``
    is the closed ``task_resumed`` object (``handoff_ref``,
    ``resumed_from_handoff`` literal ``True``, ``resumed_from_event_id``) whose
    source is the most recent still-unmatched ``handoff_created`` for the task;
    the lineage pair is the task's own. The caller preserves the original task
    ID and parent/delegation linkage by reusing the returned values verbatim::

        link = build_resume_linkage(events, task_id)
        event = _new_event(
            link["task_id"], "task_resumed", link["payload"],
            parent_task_id=link["parent_task_id"],
            delegation_id=link["delegation_id"],
        )

    Pure: it reads only, emits nothing, writes nothing, mutates no input, and
    activates no producer (the ``task-handoff`` producer stays ``planned``).
    Raises ``TelemetryError`` with a fixed, non-echoing message when the task
    has no lifecycle events, has already finished, or has no unmatched handoff
    to resume.
    """
    task_events = _task_originals(events, task_id)
    if not task_events:
        _lifecycle_error("resume target has no lifecycle events")
    if task_events[-1]["event_type"] == "task_finished":
        _lifecycle_error("cannot resume a finished task")
    unmatched = _unmatched_handoffs(task_events)
    if not unmatched:
        _lifecycle_error("no unmatched handoff to resume")
    source_id = next(reversed(unmatched))
    source = unmatched[source_id]
    lineage = task_events[0]["lineage"]
    return {
        "task_id": task_id,
        "payload": {
            "handoff_ref": source["payload"]["handoff_ref"],
            "resumed_from_handoff": True,
            "resumed_from_event_id": source_id,
        },
        "parent_task_id": lineage["parent_task_id"],
        "delegation_id": lineage["delegation_id"],
    }


def _expected_coverage(
    events: Sequence[Mapping[str, Any]],
    task_id: str,
    *,
    explicit_terminal_reason: str | None = None,
) -> dict[str, Any]:
    task_events = _task_originals(events, task_id)
    if not task_events:
        _lifecycle_error("task has no lifecycle events")
    event_types = {event["event_type"] for event in task_events}
    required = {"task_started", "task_finished"}
    starts = [event for event in task_events if event["event_type"] == "task_started"]
    workflow = starts[0]["payload"]["workflow"] if starts else None
    if workflow == "build-loop":
        required.update({"gate_result", "review_result"})
    elif workflow == "knowledge-work":
        required.add("fact_check_recorded")

    lineage = task_events[0]["lineage"]
    if lineage["delegation_id"] is not None:
        linked = any(
            event["event_type"] == "delegation_started"
            and event["payload"]["delegation_id"] == lineage["delegation_id"]
            and event["payload"]["child_task_id"] == task_id
            for event in _originals(events)
        )
        if linked:
            event_types.add("delegation_started")
        required.add("delegation_started")

    missing_events = sorted(required - event_types)
    unmatched = _unmatched_handoffs(task_events)
    missing_refs = sorted(
        f"handoff:{event_id}:task_resumed" for event_id in unmatched
    )
    terminal = task_events[-1]["event_type"] == "task_finished"
    if not terminal:
        return {
            "status": "partial",
            "missing_event_types": missing_events,
            "missing_requirement_refs": missing_refs,
            "reason": "in_progress",
        }

    completion_only = len(task_events) == 1 and not starts
    reasons = set()
    if completion_only:
        reasons.add("completion_only")
    if unmatched:
        reasons.add("unresumed_handoff")
    if explicit_terminal_reason is not None:
        reasons.add(explicit_terminal_reason)
    reason = _select_coverage_reason(reasons)
    if missing_events or missing_refs:
        if reason is None:
            _lifecycle_error("terminal task is missing required lifecycle evidence")
        return {
            "status": "partial",
            "missing_event_types": missing_events,
            "missing_requirement_refs": missing_refs,
            "reason": reason,
        }
    if reason is not None:
        _lifecycle_error("terminal degradation reason has no missing evidence")
    return {
        "status": "full",
        "missing_event_types": [],
        "missing_requirement_refs": [],
        "reason": None,
    }


def build_per_reviewer_view(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the reports-producer per-reviewer view from valid events (T3.12).

    Groups original ``review_result`` rounds by (``reviewer_id``,
    ``reviewer_class``) and joins ``defect_recorded.approving_reviewers`` on the
    stable reviewer ID. The view reports association, never causal blame, and
    never drops a defect: a defect with an empty ``approving_reviewers`` surfaces
    in ``unlinked_defects``, and any approving ID with no ``review_result`` surfaces
    in ``unknown_reviewers`` while its known co-approvers are still linked. Producer
    identity is not reviewer identity; this reads only reviewer-authored fields.
    Corrections are excluded, so a corrected round is never double-counted. This
    derivation does not activate the ``reports`` producer.
    """
    originals = _originals(events)
    reviewers: dict[tuple[str, str], dict[str, Any]] = {}
    for event in originals:
        if event["event_type"] != "review_result":
            continue
        payload = event["payload"]
        key = (payload["reviewer_id"], payload["reviewer_class"])
        entry = reviewers.setdefault(
            key, {"rounds": 0, "verdicts": {}, "linked_defects": set()}
        )
        entry["rounds"] += 1
        verdict = payload["verdict"]
        entry["verdicts"][verdict] = entry["verdicts"].get(verdict, 0) + 1

    unlinked_defects: set[str] = set()
    unknown_reviewers: set[str] = set()
    for event in originals:
        if event["event_type"] != "defect_recorded":
            continue
        payload = event["payload"]
        matched_known = False
        for reviewer_id in payload["approving_reviewers"]:
            linked_here = False
            for key, entry in reviewers.items():
                if key[0] == reviewer_id:
                    entry["linked_defects"].add(payload["defect_id"])
                    linked_here = True
            if linked_here:
                matched_known = True
            else:
                unknown_reviewers.add(reviewer_id)
        # No dropped defect (T3.12): a defect that links to no known reviewer —
        # whether its approving list is empty or entirely unknown — surfaces here.
        if not matched_known:
            unlinked_defects.add(payload["defect_id"])

    reviewer_rows = [
        {
            "reviewer_id": reviewer_id,
            "reviewer_class": reviewer_class,
            "rounds": entry["rounds"],
            "verdicts": dict(sorted(entry["verdicts"].items())),
            "linked_defects": sorted(entry["linked_defects"]),
        }
        for (reviewer_id, reviewer_class), entry in sorted(
            reviewers.items(), key=lambda item: (item[0][1], item[0][0])
        )
    ]
    return {
        "reviewers": reviewer_rows,
        "unlinked_defects": sorted(unlinked_defects),
        "unknown_reviewers": sorted(unknown_reviewers),
    }


def _latest_terminal_coverage_status(
    terminal: Mapping[str, Any], corrected_by: Mapping[str, Mapping[str, Any]]
) -> str:
    """Follow the correction chain from a terminal event to its latest valid tip (T3.5.1).

    Reports use the latest valid terminal coverage, never an earlier snapshot; a
    ``task_finished`` corrected after the fact carries the authoritative result on
    the correction, not the original. The stored ``coverage.status`` is read, not
    recomputed, because the terminal event already carries the terminal result.
    """
    current = terminal
    seen = {current["event_id"]}
    while current["event_id"] in corrected_by:
        nxt = corrected_by[current["event_id"]]
        if nxt["event_id"] in seen:
            break
        current = nxt
        seen.add(current["event_id"])
    return current["coverage"]["status"]


def build_event_coverage_rate_view(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive the reports-producer event-coverage-rate view from valid events (T3.12).

    For each host (the ``revisions.adapter`` value, per decision 0003), the rate is
    tasks whose latest valid terminal coverage is ``full`` over all completed tasks
    observed by finish or scorecard in the window; this subset treats the whole
    corpus as a single window. Completion-only, partial, and aborted tasks remain
    in the denominator (they are terminal-observed). A host with zero completed
    tasks reports a null rate with reason ``no_observed_tasks``, never a fabricated
    0 or 100 percent. This derivation does not activate the ``reports`` producer.
    """
    corrected_by: dict[str, Mapping[str, Any]] = {}
    for event in events:
        correction_of = event["lineage"]["correction_of"]
        if correction_of is not None:
            corrected_by[correction_of] = event

    tasks: dict[str, dict[str, Any]] = {}
    for event in _originals(events):
        event_type = event["event_type"]
        if event_type not in {"task_finished", "scorecard_imported"}:
            continue
        existing = tasks.get(event["task_id"])
        # An original task_finished is authoritative over a scorecard-only observation.
        if existing is not None and event_type == "scorecard_imported":
            continue
        # Both terminal kinds read their latest valid coverage through the
        # correction chain, so a corrected observation is never scored stale.
        status = _latest_terminal_coverage_status(event, corrected_by)
        tasks[event["task_id"]] = {
            "host": event["revisions"]["adapter"]["value"],
            "full": status == "full",
        }

    hosts = {event["revisions"]["adapter"]["value"] for event in events}
    rows = []
    for host in sorted(hosts, key=lambda value: (value is None, value)):
        completed = [task for task in tasks.values() if task["host"] == host]
        denominator = len(completed)
        if denominator == 0:
            rows.append(
                {
                    "host": host,
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                    "reason": "no_observed_tasks",
                }
            )
            continue
        numerator = sum(1 for task in completed if task["full"])
        rows.append(
            {
                "host": host,
                "numerator": numerator,
                "denominator": denominator,
                "rate": numerator / denominator,
                "reason": None,
            }
        )
    return {"hosts": rows}


def _validate_task_sequences(events: Sequence[Mapping[str, Any]]) -> None:
    task_ids = []
    for event in _originals(events):
        if event["task_id"] not in task_ids:
            task_ids.append(event["task_id"])
    for task_id in task_ids:
        task_events = _task_originals(events, task_id)
        starts = [event for event in task_events if event["event_type"] == "task_started"]
        finishes = [event for event in task_events if event["event_type"] == "task_finished"]
        first_type = task_events[0]["event_type"]
        if first_type == "task_finished":
            if len(task_events) != 1 or starts or len(finishes) != 1:
                _lifecycle_error("completion-only task must contain exactly one original finish")
        elif first_type != "task_started" or len(starts) != 1:
            _lifecycle_error("normal task must begin with exactly one original start")
        if len(finishes) > 1:
            _lifecycle_error("task contains duplicate original finishes")
        if finishes and task_events[-1]["event_type"] != "task_finished":
            _lifecycle_error("original event appears after task finish")

        lineage_pairs = {
            (event["lineage"]["parent_task_id"], event["lineage"]["delegation_id"])
            for event in task_events
        }
        if len(lineage_pairs) != 1:
            _lifecycle_error("task lineage pair changes within the lifecycle")

        unmatched: dict[str, Mapping[str, Any]] = {}
        consumed: set[str] = set()
        for event in task_events:
            if event["event_type"] == "handoff_created" and event["payload"]["reason"] != "delegation_brief":
                unmatched[event["event_id"]] = event
            elif event["event_type"] == "task_resumed":
                source_id = event["payload"]["resumed_from_event_id"]
                source = unmatched.get(source_id)
                if source is None or source_id in consumed:
                    _lifecycle_error("resume must consume one earlier unmatched handoff")
                if source["payload"]["handoff_ref"] != event["payload"]["handoff_ref"]:
                    _lifecycle_error("resume handoff reference does not match its source")
                consumed.add(source_id)
                unmatched.pop(source_id)

        if finishes and finishes[0]["payload"]["outcome"] == "completed" and unmatched:
            _lifecycle_error("completed task cannot retain an unmatched handoff")


def _validate_delegations(events: Sequence[Mapping[str, Any]]) -> None:
    originals = _originals(events)
    pairs: dict[str, tuple[str, str, int]] = {}
    child_pairs: dict[str, tuple[str, str]] = {}
    for index, event in enumerate(originals):
        if event["event_type"] != "delegation_started":
            continue
        delegation_id = event["payload"]["delegation_id"]
        child_id = event["payload"]["child_task_id"]
        parent_id = event["task_id"]
        if parent_id == child_id:
            _lifecycle_error("delegation parent and child task IDs must differ")
        if delegation_id in pairs:
            _lifecycle_error("delegation ID must identify exactly one parent-child pair")
        if child_id in child_pairs and child_pairs[child_id] != (parent_id, delegation_id):
            _lifecycle_error("child task cannot belong to multiple delegation pairs")
        pairs[delegation_id] = (parent_id, child_id, index)
        child_pairs[child_id] = (parent_id, delegation_id)

    for task_id in {event["task_id"] for event in originals}:
        task_events = [event for event in originals if event["task_id"] == task_id]
        parent_id = task_events[0]["lineage"]["parent_task_id"]
        delegation_id = task_events[0]["lineage"]["delegation_id"]
        if delegation_id is None:
            if task_id in child_pairs:
                _lifecycle_error("delegated child events must carry the registered lineage pair")
            continue
        pair = pairs.get(delegation_id)
        if pair is None or pair[:2] != (parent_id, task_id):
            _lifecycle_error("child lineage does not match one parent delegation event")
        first_index = originals.index(task_events[0])
        if pair[2] >= first_index:
            _lifecycle_error("parent delegation event must precede child lifecycle")

    graph = {child: parent for child, (parent, _delegation) in child_pairs.items()}
    for start in graph:
        seen = set()
        current = start
        while current in graph:
            if current in seen:
                _lifecycle_error("delegation graph contains a parent-child cycle")
            seen.add(current)
            current = graph[current]


def _validate_lifecycle_corpus(events: Sequence[Mapping[str, Any]]) -> None:
    _validate_task_sequences(events)
    _validate_delegations(events)
    for index, event in enumerate(events):
        prefix = events[: index + 1]
        reason = event["coverage"]["reason"]
        explicit = reason if reason in _EXPLICIT_TERMINAL_REASONS else None
        expected = _expected_coverage(prefix, event["task_id"], explicit_terminal_reason=explicit)
        if event["coverage"] != expected:
            _lifecycle_error("event coverage does not equal lifecycle requirements at append position")


def validate_lifecycle_events(repository_root: Path | str) -> list[dict[str, Any]]:
    """Strictly validate schema, storage, lifecycle, linkage, and coverage read-only."""

    events = validate_local_events(repository_root)
    _validate_lifecycle_corpus(events)
    return events


# --- Defect projection (T3.10.2) -------------------------------------------
#
# The diagnosing-bugs producer's durable projection. A ``defect_recorded``
# event is projected to the committed, append-only ``benchmarks/defects.jsonl``
# as the closed 13-field record defined by telemetry-v3 T3.10.2. This is the
# defect-specific projection only; the general benchmark export/aggregation is a
# separate B4 concern. Building the projection does NOT activate the producer:
# ``producer.id`` on the export receipt is the channel-injected ``dat-kit-cli``,
# and ``telemetry/producers.json`` is untouched.

DEFECT_PROJECTION_PATH = Path("benchmarks/defects.jsonl")
# Contract-facing path literal. The receipt's ``target_path`` and the CLI
# ``--target`` value are matched against the forward-slash enum in the
# ``benchmark_exported`` validator, so they must use this POSIX string, never
# ``str(Path(...))`` which yields backslashes on Windows and self-rejects.
DEFECT_PROJECTION_TARGET = "benchmarks/defects.jsonl"

GENERAL_EXPORT_PATH = Path("benchmarks/telemetry-v3.jsonl")
# Contract-facing POSIX literal for the receipt ``target_path`` and CLI
# ``--target`` value, matched against the ``benchmark_exported`` enum; never
# ``str(Path(...))`` (backslashes on Windows self-reject the receipt).
GENERAL_EXPORT_TARGET = "benchmarks/telemetry-v3.jsonl"

DEFECT_PROJECTION_FIELDS = {
    "schema_version",
    "event_id",
    "task_id",
    "parent_task_id",
    "delegation_id",
    "correction_of",
    "correction_evidence_ref",
    "occurred_at",
    "defect_id",
    "introduced_task",
    "approving_reviewers",
    "gate_that_should_have_caught_it",
    "evidence_ref",
}


def _defect_projection_record(event: Mapping[str, Any]) -> dict[str, Any]:
    """Build the closed 13-field T3.10.2 projection from one defect event."""

    payload = event["payload"]
    lineage = event["lineage"]
    return {
        "schema_version": 3,
        "event_id": event["event_id"],
        "task_id": event["task_id"],
        "parent_task_id": lineage["parent_task_id"],
        "delegation_id": lineage["delegation_id"],
        "correction_of": lineage["correction_of"],
        "correction_evidence_ref": lineage["correction_evidence_ref"],
        "occurred_at": event["occurred_at"],
        "defect_id": payload["defect_id"],
        "introduced_task": payload["introduced_task"],
        "approving_reviewers": list(payload["approving_reviewers"]),
        "gate_that_should_have_caught_it": payload["gate_that_should_have_caught_it"],
        "evidence_ref": payload["evidence_ref"],
    }


def _validate_projection_record(record: Any, *, line: int) -> dict[str, Any]:
    path = str(DEFECT_PROJECTION_PATH)
    if not isinstance(record, dict) or set(record) != DEFECT_PROJECTION_FIELDS:
        raise TelemetryError(
            "TELEMETRY_HISTORY_CORRUPT",
            "defect projection record must contain exactly its closed fields",
            path=path,
            line=line,
        )
    try:
        if isinstance(record["schema_version"], bool) or record["schema_version"] != 3:
            _error("schema_version must be the integer 3")
        _require_uuid4(record["event_id"], "event_id")
        _require_uuid4(record["task_id"], "task_id")
        _require_uuid4(record["parent_task_id"], "parent_task_id", nullable=True)
        _require_uuid4(record["delegation_id"], "delegation_id", nullable=True)
        if (record["parent_task_id"] is None) != (record["delegation_id"] is None):
            _error("parent_task_id and delegation_id must both be null or both set")
        _require_uuid4(record["correction_of"], "correction_of", nullable=True)
        _require_stable_ref(record["correction_evidence_ref"], "correction_evidence_ref", nullable=True)
        if (record["correction_of"] is None) != (record["correction_evidence_ref"] is None):
            _error("correction_of and correction_evidence_ref must agree on nullness")
        _require_timestamp(record["occurred_at"])
        _require_stable_id(record["defect_id"], "defect_id")
        _require_uuid4(record["introduced_task"], "introduced_task", nullable=True)
        _require_sorted_unique(record["approving_reviewers"], "approving_reviewers", _require_stable_id, maximum=64)
        _require_stable_id(record["gate_that_should_have_caught_it"], "gate_that_should_have_caught_it")
        _require_stable_ref(record["evidence_ref"], "evidence_ref")
    except TelemetryError as diagnostic:
        raise TelemetryError("TELEMETRY_HISTORY_CORRUPT", diagnostic.detail, path=path, line=line) from None
    return record


def _parse_projection_bytes(raw: bytes) -> list[dict[str, Any]]:
    path = str(DEFECT_PROJECTION_PATH)
    boundary = raw.rfind(b"\n") + 1
    if boundary != len(raw):
        _error("projection stream ends with an interrupted record", code="TELEMETRY_HISTORY_CORRUPT", path=path)
    records: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(raw[:boundary].splitlines(keepends=True), 1):
        try:
            value = json.loads(line, object_pairs_hook=_duplicate_object_pairs)
        except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError):
            _error("projection record is not one UTF-8 JSON object", code="TELEMETRY_HISTORY_CORRUPT", path=path, line=index)
        record = _validate_projection_record(value, line=index)
        event_id = record["event_id"]
        if event_id in seen:
            _error("duplicate projection event ID", code="TELEMETRY_HISTORY_CORRUPT", path=path, event_id=event_id, line=index)
        correction_of = record["correction_of"]
        if correction_of is not None and correction_of not in seen:
            _error("projection correction target is not an earlier record", code="TELEMETRY_HISTORY_CORRUPT", path=path, event_id=event_id, line=index)
        seen[event_id] = record
        records.append(record)
    return records


def validate_defect_projection(repository_root: Path | str) -> list[dict[str, Any]]:
    """Read and validate the durable defect projection without mutating it."""

    root = _canonical_root(repository_root)
    target = root / DEFECT_PROJECTION_PATH
    path = str(DEFECT_PROJECTION_PATH)
    try:
        parent_info = target.parent.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        _error("projection parent path is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
    if _is_linklike(parent_info) or not stat.S_ISDIR(parent_info.st_mode):
        _error("projection parent path is link-like or non-directory", code="TELEMETRY_HISTORY_CORRUPT", path=path)
    _verify_parent(root, target.parent, create=False, path=path)
    _verify_target_before_open(target, path=path)
    try:
        target.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        _error("projection target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags)
    except OSError:
        _error("projection target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
    try:
        identity = _handle_identity(fd, target, path=path)
        raw = _read_fd(fd, path=path)
        if _handle_identity(fd, target, path=path) != identity:
            _error("projection target identity changed while validating", code="TELEMETRY_HISTORY_CORRUPT", path=path)
    finally:
        os.close(fd)
    return _parse_projection_bytes(raw)


def export_defect_projection(
    repository_root: Path | str,
    task_id: str,
    *,
    target_path: str,
) -> dict[str, Any]:
    """Project every ``defect_recorded`` event to the durable defect corpus.

    Append-only and idempotent by ``event_id``: an identical record is a no-op,
    the same ID with different canonical bytes fails ``TELEMETRY_EXPORT_COLLISION``,
    and a new event appends exactly one record. The ``benchmark_exported``
    receipt is emitted into the local stream only AFTER the durable append
    succeeds; a no-op export emits no receipt. A receipt-append failure after a
    successful projection append leaves the append-only records intact (T3.10.2
    partial-failure semantics); a later retry deduplicates by ``event_id``.
    """

    if target_path != DEFECT_PROJECTION_TARGET:
        _error("export target is not the defect projection path")
    _require_uuid4(task_id, "task_id")
    root = _canonical_root(repository_root)
    events = validate_lifecycle_events(root)
    task_events = _task_originals(events, task_id)
    if not task_events:
        _lifecycle_error("export requires an existing started task")
    # The receipt is a lifecycle event, so a terminal task cannot own one: the
    # durable append would succeed and _validate_task_sequences would then reject
    # the receipt forever ("original event appears after task finish"). Because the
    # corpus is append-only and the retry is idempotent by event_id, those bytes
    # could NEVER get a receipt, and the retry reports {"no_op": true, "status":
    # "ok"} so an operator sees success. Refuse before any write instead. Found by
    # qa-agent 2026-07-25; the finished-data case is served by an OPEN exporter task
    # (see test_finished_task_events_are_copied_via_open_exporter).
    if any(item["event_type"] == "task_finished" for item in task_events):
        _lifecycle_error("export receipt cannot be owned by a task that has already finished")
    parent_task_id = task_events[0]["lineage"]["parent_task_id"]
    delegation_id = task_events[0]["lineage"]["delegation_id"]

    defects = [event for event in events if event["event_type"] == "defect_recorded"]
    target = root / DEFECT_PROJECTION_PATH
    path = str(DEFECT_PROJECTION_PATH)
    new_ids: list[str] = []
    prior_hash: str | None = None
    with _WRITE_LOCK:
        _verify_parent(root, target.parent, create=True, path=path)
        _verify_target_before_open(target, path=path)
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except OSError:
            _error("projection target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
        try:
            identity = _handle_identity(fd, target, path=path)
            raw = _read_fd(fd, path=path)
            existing = {record["event_id"]: _encode_validated_event(record) for record in _parse_projection_bytes(raw)}
            prior_hash = hashlib.sha256(raw).hexdigest() if raw else None
            blob = b""
            for event in defects:
                encoded = _encode_validated_event(_defect_projection_record(event))
                stored = existing.get(event["event_id"])
                if stored is not None:
                    if stored != encoded:
                        _error("defect projection record collides with stored bytes", code="TELEMETRY_EXPORT_COLLISION", path=path, event_id=event["event_id"])
                    continue
                blob += encoded
                existing[event["event_id"]] = encoded
                new_ids.append(event["event_id"])
            if not blob:
                return {"status": "ok", "command": "export", "no_op": True, "exported_event_ids": []}
            if _handle_identity(fd, target, path=path) != identity:
                _error("projection target identity changed before append", code="TELEMETRY_HISTORY_CORRUPT", path=path)
            written = os.write(fd, blob)
            if written != len(blob):
                os.fsync(fd)
                _error("projection append did not write the complete batch", code="TELEMETRY_HISTORY_CORRUPT", path=path)
            os.fsync(fd)
            if _handle_identity(fd, target, path=path) != identity:
                _error("projection target identity changed after append", code="TELEMETRY_HISTORY_CORRUPT", path=path)
        finally:
            os.close(fd)

    receipt = _new_event(
        task_id,
        "benchmark_exported",
        {
            "export_batch_id": str(uuid.uuid4()),
            "target_path": DEFECT_PROJECTION_TARGET,
            "prior_hash": prior_hash,
            "exported_event_ids": sorted(new_ids),
        },
        parent_task_id=parent_task_id,
        delegation_id=delegation_id,
    )
    stored = _append_lifecycle_event(root, events, receipt)
    return {
        "status": "ok",
        "command": "export",
        "no_op": False,
        "exported_event_ids": sorted(new_ids),
        "task_id": stored["task_id"],
        "event_id": stored["event_id"],
    }


def _export_eligible(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Events eligible for the committed general export (telemetry-v3 T3.10.2).

    ``local_private`` events are excluded from every committed export (T3.9); a
    ``benchmark_exported`` receipt is never export-eligible (T3.10.2), so an export
    cannot create an endless tail of receipts about receipts. Every other event —
    ``project``/``public``, any type, corrections included — is copied whole.
    """
    return [
        event
        for event in events
        if event["privacy_class"] != "local_private"
        and event["event_type"] != "benchmark_exported"
    ]


def export_event_corpus(
    repository_root: Path | str,
    task_id: str,
    *,
    target_path: str,
) -> dict[str, Any]:
    """Copy every eligible validated event whole to the general benchmark corpus (T3.10.2).

    Mirrors ``export_defect_projection``'s append-only, idempotent-by-``event_id``,
    receipt-after-append semantics, but writes the COMPLETE validated event rather
    than the defect projection, and filters eligibility through ``_export_eligible``.
    The existing target is read with ``_split_history`` (schema, ID-uniqueness, and
    correction-shape only) and never ``validate_lifecycle_events``: the eligible
    subset is not a complete lifecycle corpus (no receipts, filtered ``local_private``),
    so a lifecycle validator would falsely reject it. That read is safe because
    privacy monotonicity (a correction may never loosen privacy) guarantees an
    eligible correction can never target an excluded ``local_private`` original.
    The ``benchmark_exported`` receipt is emitted only after the durable append
    succeeds and activates no producer (receipt ``producer.id`` stays the CLI's).
    """
    if target_path != GENERAL_EXPORT_TARGET:
        _error("export target is not the general export path")
    _require_uuid4(task_id, "task_id")
    root = _canonical_root(repository_root)
    events = validate_lifecycle_events(root)
    task_events = _task_originals(events, task_id)
    if not task_events:
        _lifecycle_error("export requires an existing started task")
    # The receipt is a lifecycle event, so a terminal task cannot own one: the
    # durable append would succeed and _validate_task_sequences would then reject
    # the receipt forever ("original event appears after task finish"). Because the
    # corpus is append-only and the retry is idempotent by event_id, those bytes
    # could NEVER get a receipt, and the retry reports {"no_op": true, "status":
    # "ok"} so an operator sees success. Refuse before any write instead. Found by
    # qa-agent 2026-07-25; the finished-data case is served by an OPEN exporter task
    # (see test_finished_task_events_are_copied_via_open_exporter).
    if any(item["event_type"] == "task_finished" for item in task_events):
        _lifecycle_error("export receipt cannot be owned by a task that has already finished")
    parent_task_id = task_events[0]["lineage"]["parent_task_id"]
    delegation_id = task_events[0]["lineage"]["delegation_id"]

    eligible = _export_eligible(events)
    target = root / GENERAL_EXPORT_PATH
    path = str(GENERAL_EXPORT_PATH)
    new_ids: list[str] = []
    prior_hash: str | None = None
    with _WRITE_LOCK:
        _verify_parent(root, target.parent, create=True, path=path)
        _verify_target_before_open(target, path=path)
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except OSError:
            _error("export target is operationally unavailable", code="TELEMETRY_OPERATIONAL_FAILURE", path=path)
        try:
            identity = _handle_identity(fd, target, path=path)
            raw = _read_fd(fd, path=path)
            existing_events, _boundary = _split_history(raw, path=path)
            existing = {record["event_id"]: _encode_validated_event(record) for record in existing_events}
            prior_hash = hashlib.sha256(raw).hexdigest() if raw else None
            blob = b""
            for event in eligible:
                encoded = _encode_validated_event(event)
                stored = existing.get(event["event_id"])
                if stored is not None:
                    if stored != encoded:
                        _error("exported event collides with stored bytes", code="TELEMETRY_EXPORT_COLLISION", path=path, event_id=event["event_id"])
                    continue
                blob += encoded
                existing[event["event_id"]] = encoded
                new_ids.append(event["event_id"])
            if not blob:
                return {"status": "ok", "command": "export", "no_op": True, "exported_event_ids": []}
            if _handle_identity(fd, target, path=path) != identity:
                _error("export target identity changed before append", code="TELEMETRY_HISTORY_CORRUPT", path=path)
            written = os.write(fd, blob)
            if written != len(blob):
                os.fsync(fd)
                _error("export append did not write the complete batch", code="TELEMETRY_HISTORY_CORRUPT", path=path)
            os.fsync(fd)
            if _handle_identity(fd, target, path=path) != identity:
                _error("export target identity changed after append", code="TELEMETRY_HISTORY_CORRUPT", path=path)
        finally:
            os.close(fd)

    receipt = _new_event(
        task_id,
        "benchmark_exported",
        {
            "export_batch_id": str(uuid.uuid4()),
            "target_path": GENERAL_EXPORT_TARGET,
            "prior_hash": prior_hash,
            "exported_event_ids": sorted(new_ids),
        },
        parent_task_id=parent_task_id,
        delegation_id=delegation_id,
    )
    stored = _append_lifecycle_event(root, events, receipt)
    return {
        "status": "ok",
        "command": "export",
        "no_op": False,
        "exported_event_ids": sorted(new_ids),
        "task_id": stored["task_id"],
        "event_id": stored["event_id"],
    }


def _cli_policy() -> ProducerPolicy:
    return ProducerPolicy(
        source_classes=("runtime",),
        verdict_sources=("human", "agent", "automation"),
        metadata_rules=_CLI_METADATA_RULES,
    )


def _cli_writer(root: Path | str) -> ProducerWriter:
    return TelemetryStore(root, {CLI_PRODUCER_ID: _cli_policy()}).bind(CLI_PRODUCER_ID)


# --- Producer-bound channels (T3.12 L601 "runtime") ---------------------------
# A producer may only become ``active`` once its runtime exists (T3.12 L601-602),
# and a receipt bound to a producer may never be hand-authored (L603-604). Until
# a producer has a channel of its own, every event that can reach the corpus is
# stamped ``dat-kit-cli``, so no such receipt can exist. These channels close
# that gap. They activate nothing: ``telemetry/producers.json`` is untouched and
# no resolver reads them.
#
# The producer id is stamped by ``_prepare_event`` from the channel and rejected if a
# caller supplies it, so no channel is selected by a value carried IN AN EVENT
# (T3.12 L616-620). Scope, stated precisely: through the CLI every channel is a
# compile-time literal in the subcommand that binds it. ``producer_writer`` is public
# API and takes the id as an argument, so an in-process caller selects the channel
# there - constrained by the registry and the guards in ``TelemetryStore.bind``, not by
# a literal. ADR 0004 decision 10.

HARVEST_PRODUCER_ID = "build-loop-harvest"
TASK_HANDOFF_PRODUCER_ID = "task-handoff"
TASK_HANDOFF_REVISION = "task-handoff/1"

_TASK_HANDOFF_METADATA_RULES = {
    "producer.revision": (TASK_HANDOFF_REVISION,),
    "coverage.missing_requirement_refs": ("handoff:*",),
    "payload.handoff_ref": ("handoffs/*",),
}



def _task_handoff_policy() -> ProducerPolicy:
    # source_classes must admit "runtime": _enforce_producer_policy gates
    # event["source_class"], which _new_event fixes to "runtime".
    # verdict_sources stays empty: the closed task_resumed payload carries no
    # verdict_source, and the policy check only fires when one is present.
    return ProducerPolicy(
        source_classes=("runtime",),
        verdict_sources=(),
        metadata_rules=_TASK_HANDOFF_METADATA_RULES,
        event_types=("task_resumed",),
    )


_PRODUCER_POLICIES: Mapping[str, ProducerPolicy] = MappingProxyType(
    {TASK_HANDOFF_PRODUCER_ID: _task_handoff_policy()}
)


def producer_writer(repository_root: Path | str, producer_id: str) -> ProducerWriter:
    """Bind a producer-owned append surface over the module's producer registry.

    This is a composition convenience, NOT a trust boundary. Both identity guards -
    ``build-loop-harvest`` refused unconditionally regardless of registry contents
    (T3.12 L606-620 defers it behind a Host Adapter trust contract and a
    producer-owned resolver; L622-627 approves no activation mechanism for it), and
    ``type(producer_id) is not str`` against a lying str subclass - are enforced in
    ``TelemetryStore.bind``, the join this function delegates to. See the comment
    there for why they live at the join and what the guards do not cover.
    """
    return TelemetryStore(repository_root, _PRODUCER_POLICIES).bind(producer_id)


def _unknown_revision() -> dict[str, Any]:
    return {"value": None, "unavailable_reason": "not_emitted"}


def _new_event(
    task_id: str,
    event_type: str,
    payload: Mapping[str, Any],
    *,
    parent_task_id: str | None = None,
    delegation_id: str | None = None,
    producer_revision: str = CLI_REVISION,
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "event_id": str(uuid.uuid4()),
        "task_id": task_id,
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "producer": {"revision": producer_revision},
        "revisions": {name: _unknown_revision() for name in REVISION_FIELDS},
        "lineage": {
            "parent_task_id": parent_task_id,
            "delegation_id": delegation_id,
            "correction_of": None,
            "correction_evidence_ref": None,
        },
        "source_class": "runtime",
        "privacy_class": "project",
        "coverage": {
            "status": "partial",
            "missing_event_types": ["task_finished"],
            "missing_requirement_refs": [],
            "reason": "in_progress",
        },
        "tokens": {"total": None, "attribution_status": "unknown", "reason": "not_reported"},
        "elapsed": {"milliseconds": None, "clock_source": "unknown", "reason": "not_reported"},
        "payload": dict(payload),
    }


# The knowledge-work fact-check deliverable carries a machine-readable footer
# fenced between these markers. ``parse_fact_check_footer`` extracts and validates
# it into the closed ``fact_check_recorded`` payload WITHOUT activating the
# producer: it derives the payload from the human verdict, it does not compute it.
# (telemetry-v3 T3.12 "preserving the human verdict"; the producer stays planned.)
FACT_CHECK_FOOTER_BEGIN = "<!-- fact_check_recorded:begin -->"
FACT_CHECK_FOOTER_END = "<!-- fact_check_recorded:end -->"
FACT_CHECK_GATE_ID = "gate:fact"


def parse_fact_check_footer(text: str) -> dict[str, Any]:
    """Extract and validate the ``fact_check_recorded`` footer from deliverable text.

    Newline-agnostic (a CRLF checkout parses identically), bounded before parsing,
    and duplicate-key-rejecting like the CLI append path. The returned payload has
    passed the same closed ``fact_check_recorded`` validator the append path uses,
    so ``sourced`` implies zero findings/empty classes and ``return_to_builder``
    implies a positive count and a non-empty sorted-unique class array. Raises
    ``TelemetryError`` on any malformed footer and never echoes the rejected value.
    Pure: it returns the payload only; it emits nothing and activates no producer.
    """
    if not isinstance(text, str) or len(text.encode("utf-8", errors="replace")) > MAX_RECORD_BYTES:
        _error("fact-check footer exceeds the bounded input limit")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    start = normalized.find(FACT_CHECK_FOOTER_BEGIN)
    if start == -1:
        _error("fact-check footer begin marker is missing")
    start += len(FACT_CHECK_FOOTER_BEGIN)
    end = normalized.find(FACT_CHECK_FOOTER_END, start)
    if end == -1:
        _error("fact-check footer end marker is missing")
    block = normalized[start:end]
    fence = block.find("```")
    if fence == -1:
        _error("fact-check footer has no fenced JSON block")
    fence = block.find("\n", fence)
    if fence == -1:
        _error("fact-check footer fenced block is unterminated")
    closing = block.find("```", fence)
    if closing == -1:
        _error("fact-check footer fenced block is unterminated")
    raw = block[fence + 1:closing].strip()
    if len(raw.encode("utf-8", errors="replace")) > MAX_RECORD_BYTES:
        _error("fact-check footer exceeds the bounded input limit")
    try:
        value = json.loads(raw, object_pairs_hook=_duplicate_object_pairs)
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError):
        _error("fact-check footer JSON is invalid")
    if not isinstance(value, dict):
        _error("fact-check footer JSON must be an object")
    if value.get("gate_id") != FACT_CHECK_GATE_ID:
        _error("fact-check footer gate_id must be gate:fact")
    _validate_payload("fact_check_recorded", value)
    return value


def _bounded_payload(raw: str, event_type: str) -> dict[str, Any]:
    if not isinstance(raw, str) or len(raw.encode("utf-8", errors="replace")) > MAX_RECORD_BYTES:
        _error("payload JSON exceeds the bounded input limit")
    try:
        value = json.loads(raw, object_pairs_hook=_duplicate_object_pairs)
    except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError):
        _error("payload JSON is invalid")
    if not isinstance(value, dict):
        _error("payload JSON must be an object")
    expected_source = _CLI_VERDICT_SOURCE.get(event_type)
    if expected_source is not None and value.get("verdict_source") != expected_source:
        _error("verdict_source does not match the fixed CLI producer policy", code="TELEMETRY_PRIVACY_VIOLATION")
    return value


def _append_lifecycle_event(
    root: Path | str,
    existing: Sequence[Mapping[str, Any]],
    event: dict[str, Any],
    *,
    explicit_terminal_reason: str | None = None,
    producer_id: str | None = None,
) -> dict[str, Any]:
    # Closed-payload validation MUST precede any lifecycle-specific payload
    # indexing so shape failures stay structured strict diagnostics.
    _validate_payload(event["event_type"], event["payload"])
    candidate = [*existing, event]
    event["coverage"] = _expected_coverage(
        candidate,
        event["task_id"],
        explicit_terminal_reason=explicit_terminal_reason,
    )
    _validate_lifecycle_corpus(candidate)

    def _locked_corpus_check(actual: Sequence[Mapping[str, Any]]) -> None:
        # Re-validate the actually opened corpus plus the proposed event under
        # _WRITE_LOCK immediately before mutation; a raced lifecycle change
        # (duplicate finish/resume) fails strictly instead of appending.
        _validate_lifecycle_corpus([*actual, event])

    # Same append contract on every channel: the corpus_check re-validation under
    # _WRITE_LOCK and strict_tail are what make a raced lifecycle change fail
    # instead of appending. The public ProducerWriter.append passes neither, so a
    # producer channel must go through _append exactly as the CLI channel does.
    writer = _cli_writer(root) if producer_id is None else producer_writer(root, producer_id)
    return writer._append(
        event,
        corpus_check=_locked_corpus_check,
        strict_tail=True,
    )


class _CliParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        _error("command line is invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _CliParser(prog="telemetry.py")
    parser.add_argument("--repository-root", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--workflow", required=True)

    append = commands.add_parser("append")
    append.add_argument("--task-id", required=True)
    append.add_argument("--event", required=True, choices=EVENT_TYPES)
    append.add_argument("--payload-json", required=True)
    append.add_argument("--parent-task-id")
    append.add_argument("--delegation-id")

    resume = commands.add_parser("resume")
    resume.add_argument("--task-id", required=True)

    # Producer-bound variant of `resume`. The producer is a literal in the
    # dispatch, never an argument, so no caller-supplied value can select a
    # channel. No lineage flags: build_resume_linkage derives lineage from the
    # task's first event, so a flag would be dead or would inject a
    # caller-supplied value into an authority-relevant field.
    handoff_resume = commands.add_parser("handoff-resume")
    handoff_resume.add_argument("--task-id", required=True)

    finish = commands.add_parser("finish")
    identity = finish.add_mutually_exclusive_group(required=True)
    identity.add_argument("--task-id")
    identity.add_argument("--completion-only", action="store_true")
    finish.add_argument("--outcome", choices=("completed", "aborted", "unknown"), default="completed")
    finish.add_argument("--scorecard-ref")
    finish.add_argument("--degraded-reason", choices=tuple(sorted(_EXPLICIT_TERMINAL_REASONS)))

    export = commands.add_parser("export")
    export.add_argument("--task-id", required=True)
    export.add_argument("--target", required=True, choices=(DEFECT_PROJECTION_TARGET, GENERAL_EXPORT_TARGET))

    commands.add_parser("validate")
    return parser


def _execute_command(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repository_root)
    existing = validate_lifecycle_events(root)
    if args.command == "validate":
        return {"status": "ok", "command": "validate", "event_count": len(existing)}
    if args.command == "export":
        if args.target == GENERAL_EXPORT_TARGET:
            return export_event_corpus(root, args.task_id, target_path=args.target)
        return export_defect_projection(root, args.task_id, target_path=args.target)
    if args.command == "start":
        task_id = str(uuid.uuid4())
        event = _new_event(task_id, "task_started", {"workflow": args.workflow})
        stored = _append_lifecycle_event(root, existing, event)
    elif args.command == "append":
        _require_uuid4(args.task_id, "task_id")
        if (args.parent_task_id is None) != (args.delegation_id is None):
            _lifecycle_error("parent task ID and delegation ID must be supplied together")
        if args.parent_task_id is not None:
            _require_uuid4(args.parent_task_id, "parent_task_id")
            _require_uuid4(args.delegation_id, "delegation_id")
        if args.event == "task_finished":
            _lifecycle_error("task_finished must use the finish command")
        if args.event == "task_started" and args.delegation_id is None:
            _lifecycle_error("root task_started must use the start command")
        payload = _bounded_payload(args.payload_json, args.event)
        event = _new_event(
            args.task_id,
            args.event,
            payload,
            parent_task_id=args.parent_task_id,
            delegation_id=args.delegation_id,
        )
        stored = _append_lifecycle_event(root, existing, event)
    elif args.command in {"resume", "handoff-resume"}:
        _require_uuid4(args.task_id, "task_id")
        linkage = build_resume_linkage(existing, args.task_id)
        # The subcommand->producer map is a closed set of compile-time literals:
        # `resume` keeps the generic CLI channel, `handoff-resume` binds the
        # task-handoff producer. No argv value selects a channel (T3.12 L616-620).
        bound = args.command == "handoff-resume"
        event = _new_event(
            linkage["task_id"],
            "task_resumed",
            linkage["payload"],
            parent_task_id=linkage["parent_task_id"],
            delegation_id=linkage["delegation_id"],
            producer_revision=TASK_HANDOFF_REVISION if bound else CLI_REVISION,
        )
        stored = _append_lifecycle_event(
            root,
            existing,
            event,
            producer_id=TASK_HANDOFF_PRODUCER_ID if bound else None,
        )
    else:
        if args.completion_only:
            task_id = str(uuid.uuid4())
            parent_task_id = delegation_id = None
            if args.degraded_reason is not None:
                _lifecycle_error("completion-only reason is fixed by the lifecycle contract")
        else:
            task_id = args.task_id
            _require_uuid4(task_id, "task_id")
            task_events = _task_originals(existing, task_id)
            if not task_events:
                _lifecycle_error("normal finish requires an existing started task")
            parent_task_id = task_events[0]["lineage"]["parent_task_id"]
            delegation_id = task_events[0]["lineage"]["delegation_id"]
        event = _new_event(
            task_id,
            "task_finished",
            {"outcome": args.outcome, "scorecard_ref": args.scorecard_ref},
            parent_task_id=parent_task_id,
            delegation_id=delegation_id,
        )
        stored = _append_lifecycle_event(
            root,
            existing,
            event,
            explicit_terminal_reason=args.degraded_reason,
        )
    return {
        "status": "ok",
        "command": args.command,
        "task_id": stored["task_id"],
        "event_id": stored["event_id"],
    }


def _emit_result(value: Mapping[str, Any], *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), file=stream)


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run the host-neutral lifecycle CLI and return its process exit code."""

    try:
        args = _parser().parse_args(argv)
        environment = os.environ if environ is None else environ
        if args.command in {"start", "append", "resume", "handoff-resume", "finish", "export"} and environment.get("DAT_KIT_TELEMETRY") == "off":
            _emit_result({"status": "disabled", "command": args.command})
            return 0
        result = _execute_command(args)
    except TelemetryError as diagnostic:
        command = getattr(locals().get("args"), "command", "unknown")
        if diagnostic.code == "TELEMETRY_OPERATIONAL_FAILURE" and command in {"start", "append", "resume", "handoff-resume", "finish"}:
            _emit_result({
                "status": "degraded",
                "command": command,
                "code": "TELEMETRY_OPERATIONAL_FAILURE",
            })
            return 0
        _emit_result({"status": "error", "code": diagnostic.code}, error=True)
        return 2
    except OSError:
        command = getattr(locals().get("args"), "command", "unknown")
        if command in {"start", "append", "resume", "handoff-resume", "finish"}:
            _emit_result({
                "status": "degraded",
                "command": command,
                "code": "TELEMETRY_OPERATIONAL_FAILURE",
            })
            return 0
        _emit_result({"status": "error", "code": "TELEMETRY_OPERATIONAL_FAILURE"}, error=True)
        return 2
    _emit_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
