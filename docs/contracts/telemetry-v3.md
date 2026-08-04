# Telemetry v3 contract

- Contract revision: `telemetry-v3/1`
- Event schema version: `3`
- Governance: Class C under `platform-contract-policy/1`
- Status: accepted and effective from the MeoLoom 3.0 public clean root
- Authorization: `docs/decisions/0007-telemetry-v3-public-baseline.md`

This contract defines the host-neutral Telemetry v3 event model for MeoLoom
3.0. It is normative for producers, validators, storage, imports,
exports, retention, reports, disable behavior, and downgrade behavior. This
document and the checked registry are its public program source.

Compatibility note: the schema `$id` host and producer ID `dat-kit-cli` are
frozen wire identifiers. They remain unchanged across the MeoLoom rename so
existing telemetry receipts and validators keep their identity.

The public baseline authorizes the contract, `scripts/telemetry.py`, the
`telemetry/` runtime root, and the three committed benchmark surfaces. It does
not activate a producer by itself: each producer remains bound to the exact
status and evidence requirements in T3.12 and `telemetry/producers.json`.

## T3.1 Scope and non-goals

Telemetry v3 records task lifecycle evidence needed to evaluate MeoLoom's
work loops without turning telemetry into authority. Events describe what ran,
which contract and producer revisions were involved, what gates and reviewers
reported, what rework followed, and how complete the observation was.

Telemetry does not approve a plan, close a gate, merge a change, modify a
Domain Pack, or make an evolution decision. Human and reviewer authority stays
where the governing workflow places it. Raw prompts and secrets are not
telemetry inputs.

The following are explicitly outside v3:

- automatic self-evolution or automatic merge authority;
- multi-writer correctness or a multi-process locking claim;
- retroactive rewriting of scorecard, defect, or telemetry history;
- inferred token counts, inferred elapsed time, or inferred reviewer verdicts;
- guaranteed full coverage on hosts that cannot emit lifecycle-start events.

## T3.2 Storage surfaces and ownership boundary

The v3 surfaces are exact:

| Surface | Role | Durability |
|---|---|---|
| `telemetry/events.jsonl` | machine-local working event stream | local, uncommitted, not a cross-machine corpus |
| `benchmarks/telemetry-v3.jsonl` | general exported v3 event corpus | committed, append-only |
| `benchmarks/defects.jsonl` | defect producer's durable projection | committed, append-only |
| `benchmarks/scorecard.jsonl` | existing scorecard history and legacy import source | committed, append-only; existing bytes stay untouched |

These paths are governed by the `telemetry-v3-runtime` component in
`registry/evolution.json`; the Class C contract remains owned by the
`registry-contract` component. A broad glob that merely hides an orphan
diagnostic is not conformance.

Every JSONL surface uses UTF-8, one closed JSON object per line, and one
terminal LF per complete record. Unknown fields are invalid. A reader may
recover one interrupted final record as specified in T3.8; it may not skip an
invalid interior record.

## T3.3 Closed event envelope

Every v3 event contains exactly these required top-level fields:

| Field | Type and rule |
|---|---|
| `schema_version` | integer literal `3` |
| `event_id` | canonical lowercase UUIDv4 string; unique across the corpus |
| `task_id` | canonical lowercase UUIDv4 string |
| `event_type` | one closed event-type value from T3.6 |
| `occurred_at` | RFC 3339 UTC timestamp ending in `Z`; describes when this record was emitted |
| `producer` | closed object `{id, revision}`; both are stable IDs from T3.3.1 |
| `revisions` | closed object with all revision references in T3.4 |
| `lineage` | closed object `{parent_task_id, delegation_id, correction_of, correction_evidence_ref}`; every key is present and nullable |
| `source_class` | `runtime`, `repository`, `human`, `legacy_import`, or `derived` |
| `privacy_class` | `public`, `project`, or `local_private` |
| `coverage` | closed coverage object from T3.5 |
| `tokens` | closed token-attribution object from T3.5 |
| `elapsed` | closed elapsed-attribution object from T3.5 |
| `payload` | the closed object selected by `event_type` in T3.6 |

UUID values use the textual `8-4-4-4-12` form. Nil UUIDs and non-v4 UUIDs are
invalid. Nullable fields use JSON `null`; an empty string is never a null
substitute. Arrays described as sets are sorted, contain no duplicates, and
use the identity rules of their element type.

The maximum encoded event record is 65,536 UTF-8 bytes including its terminal
LF. Array cardinalities are closed: `coverage.missing_event_types` has at most
13 entries, `coverage.missing_requirement_refs` at most 128,
`defect_recorded.approving_reviewers` at most 64,
`fact_check_recorded.failure_classes` at most 7, and
`benchmark_exported.exported_event_ids` at most 256. No other v3 field is a
variable-length array.

### T3.3.1 String grammars

No telemetry field accepts free-form text. Every non-enum string is one of:

- **stable ID**: 1-128 ASCII characters matching
  `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`;
- **stable reference**: 1-512 ASCII characters matching
  `[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,511}`; or
- **path**: a 1-512 character canonical repository-relative POSIX path with
  no empty, `.`, or `..` segment, no control character, no backslash, no
  Windows-reserved basename, and no trailing space or dot.

Hashes, UUIDs, timestamps, and literal paths use their narrower declared
grammar. Arbitrary descriptions, error messages, prompt excerpts, copied
source, and user-entered notes have no field in v3. Producers map a condition
to a closed enum and store only a stable evidence reference.

A stable reference is an opaque identifier. A v3 reader, validator, exporter,
or reporter never treats it as a filesystem path or URI, joins it to a root,
opens it, or follows its slash/colon syntax. A field that authorizes filesystem
access must instead have type `path` and pass the path and containment rules.

### T3.3.2 Source and privacy classes

`source_class` describes provenance:

- `runtime`: emitted directly by a work-loop runtime or host adapter;
- `repository`: derived from a tracked repository artifact or gate result;
- `human`: an explicit owner or human-run gate/review verdict;
- `legacy_import`: derived from a pre-v3 durable record;
- `derived`: calculated only from already-valid v3 events.

`privacy_class` describes the maximum handling boundary:

- `public`: already public, allowlisted metadata;
- `project`: project-scoped allowlisted metadata that may enter committed
  benchmarks;
- `local_private`: allowlisted metadata that must remain local and must never
  be exported.

A class is not permission to copy arbitrary source content. T3.9's field
allowlist and forbidden-value rules always win.

## T3.4 Revision references

`revisions` contains exactly these required keys:

`domain`, `engine`, `adapter`, `canonical_contract`, and `profile`.

Each value is a closed object `{value, unavailable_reason}`. Exactly one is
non-null:

- `value` is a stable reference and `unavailable_reason` is
  null; or
- `value` is null and `unavailable_reason` is one of
  `not_applicable | not_emitted | unsupported_host | legacy_source | ambiguous`.

Missing revision data must never be filled from memory or guessed from a
nearby checkout. `producer.revision` follows the same honesty rule but is
required: a producer unable to identify its own revision must not emit a v3
event.

## T3.5 Coverage and attribution

### T3.5.1 Coverage

`coverage` contains exactly
`{status, missing_event_types, missing_requirement_refs, reason}`:

- `status` is `full | partial`;
- `missing_event_types` is a sorted unique array of T3.6 event types;
- `missing_requirement_refs` is a sorted unique stable-ID array of unmet
  instance-level requirements; and
- `reason` is null for `full`, otherwise exactly one of
  `completion_only | unsupported_host_start | telemetry_disabled | legacy_import |
  producer_failure | unresumed_handoff | in_progress`.

`full` requires both missing arrays to be empty and a null reason. `partial`
requires at least one non-empty missing array and a non-null reason. Partial
coverage is valid data, not an error to hide. A completion-only scorecard may
mint a task ID, but its events must use `partial` with reason
`completion_only` and name the lifecycle events that were not observed.

At minimum, full coverage requires both `task_started` and `task_finished` in
valid T3.6 order. The validator derives the required set, then requires
`missing_event_types` to equal the required types absent from the stream:

- every task: `task_started`, `task_finished`;
- `workflow=build-loop`: at least one `gate_result` and one `review_result`;
- `workflow=knowledge-work`: at least one `fact_check_recorded` carrying the
  load-bearing fact-check verdict;
- `resumed_from_handoff=true`: `task_resumed`;
- any delegated parent/child pair: the linked `delegation_started` event;
- any emitted handoff: `handoff_created`.

`missing_requirement_refs` is normally empty. For every unmatched
`handoff_created` whose reason is `context_ceiling` or `deliberate_pause`, it
contains exactly `handoff:<handoff-event-UUIDv4>:task_resumed`. A later matching
`task_resumed` removes that reference. A `delegation_brief` does not create
this resume requirement because its child lifecycle is linked through
`delegation_started` instead.

An isolated `task_finished` therefore cannot claim `full`. Unknown workflows
owe the universal start/finish pair; their producer revision may declare a
stricter required-event profile but may never weaken this floor.

`in_progress` is valid only before the original `task_finished`. On each
non-terminal event, both missing arrays are the exact requirements not yet
observed at that append position; `missing_event_types` includes
`task_finished`. The arrays may shrink as evidence arrives. The original
`task_finished` and any correction of it carry the terminal `full` or degraded
`partial` result and cannot use `in_progress`. Reports use that latest valid
terminal coverage, never an earlier in-progress snapshot.

When more than one terminal degradation cause applies, the single reason is
selected by this strict precedence:
`telemetry_disabled` > `legacy_import` > `producer_failure` > `unresumed_handoff` > `unsupported_host_start` > `completion_only`.
The two missing-requirement arrays still expose the complete loss; the reason
identifies the highest-precedence cause and is never selected opportunistically
to improve a coverage report.

### T3.5.2 Tokens

`tokens` contains exactly `{total, attribution_status, reason}`.
`attribution_status` is `exact | unknown`:

- `exact`: `total` is a non-negative integer and `reason` is null;
- `unknown`: `total` is null and `reason` is one of
  `unsupported_provider | missing_timestamp | no_matching_session |
  multiple_matching_sessions | ambiguous_multi_task_session | not_reported |
  legacy_source | telemetry_disabled`.

Estimates are forbidden. The existing scorecard v2 unknown reasons retain
their current meaning.

### T3.5.3 Elapsed time

`elapsed` contains exactly `{milliseconds, clock_source, reason}`:

- measured: `milliseconds` is a non-negative integer, `clock_source` is
  `monotonic | wall`, and `reason` is null;
- unknown: `milliseconds` is null, `clock_source` is `unknown`, and `reason`
  is `not_reported | unsupported_host | ambiguous | legacy_source |
  telemetry_disabled`.

Durations prefer a monotonic clock. A wall-clock duration is permitted only
when labeled `wall`; clock corrections must not silently produce a negative
duration.

## T3.6 Lifecycle and closed event payloads

The normal lifecycle is:

```text
task_started -> work/gate/review/handoff/delegation events -> task_finished
```

The task UUIDv4 is minted at LOAD, before SELF-QUESTION or its domain
equivalent. The same `task_id` propagates through gates, reviews, handoffs,
HARVEST, and finish. A completion-only degraded producer is the sole path that
may mint the task ID at finish; T3.5.1 then requires partial coverage.

Each payload contains exactly the fields below. `stable-id`, `stable-ref`, and
`path` use T3.3.1. `verdict_source` is always
`human | agent | automation`. In the table, slash-separated values are the
exact closed enum alternatives, not free text.

The load-bearing named fields include `resumed_from_handoff`, `first_pass`,
`verdict_source`, `introduced_task`, `approving_reviewers`,
`gate_that_should_have_caught_it`, and `kit_facing`; their exact owning
payloads and types are fixed below.

| `event_type` | Exact payload fields |
|---|---|
| `task_started` | `{workflow: stable-id}` |
| `task_finished` | `{outcome: completed/aborted/unknown, scorecard_ref: path or null}` |
| `handoff_created` | `{handoff_ref: path, reason: context_ceiling/deliberate_pause/delegation_brief}` |
| `task_resumed` | `{handoff_ref: path, resumed_from_handoff: true, resumed_from_event_id: UUIDv4}` |
| `delegation_started` | `{delegation_id: UUIDv4, child_task_id: UUIDv4, delegated_role: stable-id, brief_ref: path}` |
| `gate_result` | `{gate_id: stable-id, outcome: pass/fail/skipped, first_pass: bool, verdict_source: human/agent/automation, evidence_ref: stable-ref or null}` |
| `review_result` | `{reviewer_id: stable-id, reviewer_class: plan/qa/software-dev/knowledge-work/security/owner, round: positive-integer, verdict: approve/return_to_builder/phase_done/revise/skipped, verdict_source: human/agent/automation, finding_count: non-negative-integer, evidence_ref: stable-ref or null}` |
| `defect_recorded` | `{defect_id: stable-id, introduced_task: UUIDv4 or null, approving_reviewers: sorted-unique-stable-id-array, gate_that_should_have_caught_it: stable-id, evidence_ref: stable-ref}` |
| `rework_recorded` | `{cause_event_id: UUIDv4, round: positive-integer, reason: gate_failure/review_finding/spec_correction/other, evidence_ref: stable-ref or null}` |
| `lesson_candidate_recorded` | `{kit_facing: bool, root_cause_ref: stable-ref, candidate_ref: stable-ref}` |
| `fact_check_recorded` | `{gate_id: stable-id, verdict: sourced/return_to_builder, verdict_source: human/agent/automation, finding_count: non-negative-integer, failure_classes: sorted-unique-fact-check-failure-array, evidence_ref: stable-ref}` |
| `scorecard_imported` | `{source_path: "benchmarks/scorecard.jsonl", source_record_ordinal: positive-integer, source_record_hash: lowercase-sha256, source_record_ref: stable-ref}` |
| `benchmark_exported` | `{export_batch_id: UUIDv4, target_path: "benchmarks/telemetry-v3.jsonl" or "benchmarks/defects.jsonl", prior_hash: lowercase-sha256 or null, exported_event_ids: sorted-unique-UUIDv4-array}` |

`gate_result.first_pass` reports whether this gate passed on its first
attempt for the task; it is not reconstructed from a later final result.
Human-run gates use `verdict_source=human`; deterministic commands use
`automation`; an AI reviewer or agent uses `agent`.

For `fact_check_recorded`, `sourced` is the machine value for the
knowledge-work charter's `SOURCED` verdict: `finding_count` is zero and
`failure_classes` is empty. `return_to_builder` records the charter's numbered
failure outcome: the count is positive and the array is non-empty. Its closed
failure values are `unsupported_claim`, `weaker_than_claim`, `contradiction`,
`unreliable_source`, `stale_source`, `inadequate_coverage`, and
`prose_contradiction`. The `evidence_ref` points to the complete numbered
finding record; telemetry never copies its prose.

Exactly one original `task_started` exists for every normally observed task.
Exactly one original `task_finished` also exists. The original start is the task's first
event and the original finish follows every work, gate, review, handoff,
delegation, and HARVEST event for that task. Duplicate starts, duplicate
finishes, finish-before-start, and an original event appended after finish are
invalid. Correction events do not alter this original-event cardinality.

The completion-only degraded path has exactly one original `task_finished`, no
`task_started`, and the T3.5.1 partial-coverage label.

A resumed execution preserves the same `task_id` and does not emit another `task_started`. It emits `task_resumed` after an earlier unmatched `handoff_created.event_id` for that same task and before finish. Its
`resumed_from_event_id` names that event, its `handoff_ref` is identical, and
`resumed_from_handoff` is the literal true. One task may have multiple ordered
handoff/resume pairs, but a handoff event can be consumed at most once. A
completed task has no unmatched non-delegation handoff; an aborted task may
end with one and uses terminal partial reason `unresumed_handoff` plus the
corresponding `missing_requirement_refs` entry.

## T3.7 Lineage and corrections

`lineage.parent_task_id` is null for a root task and the parent task UUID for
a delegated child. `lineage.delegation_id` is null outside a delegated child
and is copied from the parent's `delegation_started.payload.delegation_id` to
every child event. A child always has its own `task_id`; it never reuses the
parent's identity.

All original events for one task carry one immutable `(parent_task_id, delegation_id)` pair. A delegation ID identifies exactly one parent-child task pair,
appears in exactly one parent `delegation_started` payload whose
`child_task_id` names that child, and cannot be reused for another parent or
child. The parent event keeps the parent's own lineage pair; a root parent may
therefore delegate multiple children through distinct payload delegation IDs
without lineage drift. A parent ID without a delegation ID, a delegation ID
without a parent ID on the child, pair drift within a task, or a parent/child
cycle is invalid.

`lineage.correction_of` and `lineage.correction_evidence_ref` are both null for
an original event. A correction is a new, complete event with a new `event_id`
and the same `event_type` as its target; both correction lineage fields are
non-null. It carries the corrected envelope rather than a JSON patch. The
target remains byte-for-byte present. A validator resolves the latest valid
correction in append order but preserves the entire chain.

Immutable target fields are `schema_version`, `task_id`, `event_type`,
`source_class`, `producer.id`, `lineage.parent_task_id`,
`lineage.delegation_id`, and every `payload` field; a correction must equal its
target for all of them. Replacement fields are `coverage`, `tokens`, and
`elapsed`; the correction supplies their complete current values.
Correction-evidence fields are `event_id`, `occurred_at`, `producer.revision`,
and `revisions`; they describe the correcting write and may differ from the
target. `lineage.correction_of` names the immediate target. `privacy_class` may
stay equal or tighten only in the order
`public` -> `project` -> `local_private`; it may never loosen. Aggregation uses
the immutable identity from the chain and the latest replacement values, so it
never merges unspecified fields.

The writer injects `producer.id` from a registered producer channel; it never
accepts that ID from event input. Every correction must arrive through the same
registered channel as the root original event. Its
`lineage.correction_evidence_ref` is an opaque stable reference to an
append-only correction receipt owned by that producer and bound to the root
event ID, immediate target event ID, correcting event ID, and SHA-256 of the
complete encoded correcting event record including its terminal LF. That hash
covers every envelope, lineage, privacy, attribution, and payload byte,
including `lineage.correction_evidence_ref`; it is not a hash of replacement
fields alone. Before append, the writer verifies that exact binding through the
registered producer's evidence resolver. Missing, mismatched, caller-authored,
or self-asserted evidence fails `TELEMETRY_CORRECTION_UNAUTHORIZED`; v3 has no
owner-override shortcut.

Because every payload field is immutable, a correction cannot change a gate,
review, fact-check, task outcome, legacy provenance, or other load-bearing
claim. A later gate/review/fact-check observation is a new original event with
its own source evidence; an erroneous terminal claim remains auditable and is
followed by defect/rework evidence rather than overwritten.

Privacy may tighten to `local_private` only before any member of the correction
chain has been exported. Once one member is present in either durable benchmark
target, every later correction must remain `public` or `project` and therefore
export-eligible. A request to make already-exported evidence `local_private`
fails with `TELEMETRY_PRIVACY_IRREVERSIBLE`, stops further export of that chain,
and requires separately governed incident handling; append-only history cannot
claim to retract bytes already committed.

The target must be an earlier event in the same corpus. A forward, self, missing, or cyclic correction is invalid. A correction never changes the identity or
bytes of its target and never authorizes removal of the original.

## T3.8 Append, validation, and recovery

The v2.1 guarantee is a single writer using the released append primitive's
semantics: open with `O_APPEND`, hold the record-boundary lock for validation,
write, and recovery, require an exact positive write count, flush before
success, and re-check replacement-aware path identity while the lock is held.
Multi-writer locking is deferred until delegated agents actually write
concurrently; v3 must not claim it today.

These checks apply before the first normal append and every later local or
durable write, not only during recovery. The writer resolves the fixed target
and every existing parent component under the canonical repository root,
rejects any symlink or reparse point, and rejects a target outside that root.
It opens or creates only the fixed final path with no-follow semantics, requires
a regular file with link count one, and compares the opened handle's file
identity and containment before append, after append, and after flush. A
missing target may be created only beneath an already verified parent chain.
Any identity change, hard link, link-like component, non-regular file, or
containment ambiguity fails closed before further mutation.

Before append, the writer validates the closed envelope, payload, privacy
allowlist, correction target and authority, encoded-line size, array bounds,
and corpus-wide ID uniqueness. Duplicate `event_id` values are invalid. The
same ID with different bytes is never a correction; it is a collision. A
reader or importer stops after 65,537 bytes without LF and rejects the record,
so size validation never requires unbounded allocation.

Recovery may truncate only an interrupted final record that lacks a complete
UTF-8 JSON object plus terminal LF. Truncation returns exactly to the byte
offset after the last validated line, under the same lock. An invalid interior
record, invalid UTF-8 before the tail, path replacement, symlink/reparse point,
hard link, or ambiguous recovery boundary fails closed without mutation.

Normative diagnostic families are:

- `TELEMETRY_SCHEMA_UNSUPPORTED`;
- `TELEMETRY_EVENT_INVALID`;
- `TELEMETRY_DUPLICATE_EVENT_ID`;
- `TELEMETRY_CORRECTION_INVALID`;
- `TELEMETRY_CORRECTION_UNAUTHORIZED`;
- `TELEMETRY_PRIVACY_IRREVERSIBLE`;
- `TELEMETRY_HISTORY_CORRUPT`;
- `TELEMETRY_PRIVACY_VIOLATION`;
- `TELEMETRY_EXPORT_COLLISION`.

Diagnostics identify the path and event or line when known but must not echo a
forbidden value.

## T3.9 Privacy and source handling

Persisted values are allowlisted metadata only. Raw prompts, full user
messages, tool request or response bodies, environment values, credentials,
secrets, arbitrary file contents, and provider transcripts are forbidden.
They must be omitted, not masked and stored. A producer that cannot prove a
value is allowlisted must omit it or fail with `TELEMETRY_PRIVACY_VIOLATION`.

References may contain stable IDs, canonical repository-relative paths,
lowercase hashes, enum verdicts, counts, and durations. They must not contain
absolute home paths, access tokens, query strings carrying secrets, or copied
source text. `local_private` events stay only in `telemetry/events.jsonl` and
are excluded from every committed export. `project` and `public` events are
exportable only field-for-field under this contract's allowlist.

The T3.3.1 grammar and size bounds apply before persistence, including
`workflow`, producer and reviewer identity, gate/defect IDs, every reason,
and every evidence/root-cause/candidate reference. A producer may not place
free-form text in a stable-ref field merely because the characters happen to
match the grammar; the opaque value must denote a stable artifact, identifier,
or closed enum owned by the producer. Telemetry never dereferences it; any
producer-side evidence resolver applies its own authenticated namespace and
returns only a binding verdict, never bytes for telemetry to open.

Disable and error paths obey the same rules. A diagnostic may name a field but
never print its rejected secret-like value.

## T3.10 Import, export, retention, and durable history

### T3.10.1 Legacy import

A v2 scorecard import reads `benchmarks/scorecard.jsonl` without modifying it
and emits exactly one `scorecard_imported` and one `task_finished` for each
valid source line, in that order, with the same task ID. The importer mints one
UUIDv4 task ID on the first import of the source-record slot. If append is
interrupted after either event, retry finds the existing event by source
slot and event type, reuses that task ID after an interrupted import, and emits only the
missing member of the pair.

The immutable source-record slot is path + ordinal. Its
`source_record_hash` is the content binding, not a way to mint another slot.
Each linked event identity is source-record slot + event type. The ordinal is
the one-based physical line number. Once any event records a slot/hash pair, a
later import of that slot with a different hash fails
`TELEMETRY_HISTORY_CORRUPT`; it never creates new evidence or a new task ID.
To compute `source_record_hash`, take the exact
UTF-8 bytes of that physical JSON record, normalize only its terminal CRLF or CR to LF, include that LF in the SHA-256 input, and perform no JSON
reserialization or other normalization. The stable source reference is
`benchmarks/scorecard.jsonl#line-<ordinal>`. Two byte-identical source lines at
different ordinals remain distinct historical records.

A legacy physical line has the same 65,536-byte maximum including terminal LF
as a v3 event. The importer reads at most 65,537 bytes while seeking LF and
rejects an oversized line before JSON parsing or event creation; hashing may be
streamed but cannot bypass the bound.

Only the original `scorecard_imported` and `task_finished` consume these two
linked event identities. T3.7 corrections preserve the import provenance
fields and do not count as additional pair members.

Both linked events use `source_class=legacy_import` and explicit unknowns for
unavailable lifecycle, token, elapsed, and revision facts. The non-terminal
`scorecard_imported` uses `status=partial`, reason `in_progress`, and the exact
required event types still absent at that append position. The linked
`task_finished` uses terminal `status=partial`; its reason is selected by the
T3.5.1 precedence, so an ordinary import uses `legacy_import` while a disabled
scorecard import covered by T3.11 uses `telemetry_disabled`.
`task_finished.payload.scorecard_ref` is `benchmarks/scorecard.jsonl`;
`scorecard_imported` carries the exact ordinal, hash, and source reference.

No import may normalize, reorder, truncate, or rewrite existing scorecard
bytes. Historical schema-v1 and schema-v2 scorecard records remain valid in
their original file.

### T3.10.2 Export

General export copies the complete eligible validated event to
`benchmarks/telemetry-v3.jsonl`. A `defect_recorded` event also appends this
closed projection to `benchmarks/defects.jsonl`:

| Defect projection field | Normative value |
|---|---|
| `schema_version` | integer literal `3` |
| `event_id` | source defect event UUIDv4 |
| `task_id` | source event task UUIDv4 |
| `parent_task_id` | source lineage value, UUIDv4 or null |
| `delegation_id` | source lineage value, UUIDv4 or null |
| `correction_of` | source lineage value, UUIDv4 or null |
| `correction_evidence_ref` | source lineage opaque stable reference or null |
| `occurred_at` | source event RFC 3339 UTC timestamp |
| `defect_id` | source payload stable ID |
| `introduced_task` | source payload UUIDv4 or null |
| `approving_reviewers` | source payload sorted unique stable reviewer IDs |
| `gate_that_should_have_caught_it` | source payload stable gate ID |
| `evidence_ref` | source payload stable reference |

The projection has no other fields. A corrected defect appends a new projection
record with its new `event_id` and `correction_of`; it never rewrites the prior
projection. Consumers resolve the correction chain by source event identity.

Export is idempotent by `event_id`:

- an existing identical event is a no-op;
- the same ID with different canonical bytes fails with
  `TELEMETRY_EXPORT_COLLISION`;
- a new event appends one record and never rewrites existing benchmark bytes.

The exporter verifies and records the target's prior-byte hash before the
batch and emits `benchmark_exported` only after the target append succeeds.
Partial failure leaves already-valid append-only records intact and reports
the unexported IDs; retry deduplicates the completed IDs.

`benchmark_exported` events are never export-eligible and never appear in
`exported_event_ids`. A no-op export with no new eligible events emits no new
receipt. The stream is caught up when every eligible non-receipt event is
present identically in its target, so an export cannot create an endless tail
of receipts that makes pruning unreachable.

### T3.10.3 Retention

No automatic TTL exists in v2.1. Local events remain until an explicit prune
operation. Prune is allowed only after verified export proves every selected
exportable event is present in its durable target; `local_private` records
require a separate explicit selection because they have no export receipt.

Committed benchmark records are retained indefinitely under v3 and are never
deleted, normalized, or rewritten by retention. A future retention change to
the durable corpus requires a separately governed contract and cannot act
retroactively without explicit authority.

## T3.11 Disable, downgrade, and compatibility

The host-neutral disable switch is `DAT_KIT_TELEMETRY=off`. In disabled mode,
start, append, and finish perform no new telemetry writes and return a
non-error disabled result; telemetry failure must not block the work loop,
gates, reviews, or scorecard completion. Disable does not delete or rewrite
existing local or committed history.

When a completion-only producer still emits a scorecard outside the disabled
writer, any later import labels the resulting v3 evidence `partial` with
reason `telemetry_disabled`.

Legacy dat-kit 2.0 and 1.x tooling must ignore v3 artifacts it does not own or fail
closed with `TELEMETRY_SCHEMA_UNSUPPORTED`; downgrade must never mutate v3
files. v3 readers reject future `schema_version` values without attempting a
partial load. v3 exports do not change the schema or bytes of existing
scorecard history.

The schema freeze begins at the MeoLoom 3.0 public clean root authorized by
Decision 0007. After that boundary, any new top-level field, payload field, enum value, event
type, or changed interpretation that a strict v3 reader would reject requires
a new schema version and Class C approval. Producer-only changes that preserve
all v3 bytes and meaning follow their separately governed class.

## T3.12 Required producers and status truthfulness

Schema without producers is not telemetry completion. The five required
producer responsibilities are:

| PLAN item | Producer responsibility | Required evidence before `active` |
|---|---|---|
| build-loop HARVEST | emit `lesson_candidate_recorded` with `kit_facing=true` only when root cause is in a MeoLoom skill, template, or gate | a real HARVEST task plus validated event, emitted only through the trusted context and resolver prerequisites below |
| diagnosing-bugs | emit `defect_recorded` and export its projection to `benchmarks/defects.jsonl` | a real post-mortem with the required defect tuple |
| knowledge-work fact-check | emit a machine-readable `fact_check_recorded` footer while preserving the human verdict | a real knowledge-work task with human-vs-agent-vs-automation source distinguished |
| task/handoff schema | emit `task_resumed.resumed_from_handoff=true`, preserve the original task ID across handoff, and preserve parent/delegation linkage | a real resumed or delegated task |
| reports | derive the per-reviewer view and event-coverage-rate view from valid events | report fixtures plus representative software-dev and knowledge-work observations |

Every producer begins `planned`. It becomes `active` only when its runtime,
artifact/schema revision, validation, and a real producer receipt exist.
Contract prose, a schema fixture, or a synthetic event alone cannot activate a
producer.

The build-loop HARVEST responsibility remains required but is
`planned/deferred`. It cannot satisfy Phase 6 completion and must not emit live
events until both of these prerequisites have separate approval:

1. a Host Adapter trust contract propagates the LOAD-minted task identity
   through a trusted context that the caller cannot select; and
2. a producer-owned resolver verifies receipt existence and exact binding to
   the task, root cause, lesson candidate, producer revision, and activation
   receipt.

The generic scorecard CLI is not a trusted LOAD/HARVEST context. It must not
accept a task UUID, root-cause reference, lesson-candidate reference, or locus
as authority to attach evidence, emit a HARVEST event, finish a task, or
activate a producer. UUIDs are correlation data, and stable-reference grammar
or namespace shape does not authenticate producer ownership.

This deferment approves no capability transport, receipt store, schema field,
event type, resolver implementation, Host Adapter implementation, or activation
mechanism. Fixtures, prose, scorecard records, namespace-shaped hashes, task
UUIDs, and synthetic events cannot activate the producer. A future live
implementation requires a new governed proposal with its own observation,
budget, threat model, cross-host contract, and security review.

The per-reviewer view groups `review_result` rounds by the payload's explicit
`reviewer_id` and `reviewer_class`, then joins linked
`defect_recorded.approving_reviewers` on the same stable reviewer IDs. The
producer identity is not a substitute for reviewer identity. The view reports
association, not causal blame, and includes unknown/unlinked defects rather
than dropping them.

For each host and observation window, the event-coverage-rate view is:

```text
tasks whose latest valid coverage status is full
------------------------------------------------
all completed tasks observed by finish or scorecard in the window
```

Completion-only and other partial tasks remain in the denominator. A window
with zero completed tasks reports null with the reason `no_observed_tasks`,
never a fabricated zero or 100 percent.

## T3.13 Conformance and release boundary

Decision 0007 authorizes this exact Class C contract hash at the MeoLoom 3.0
public clean root. Implementations owe schema/storage, lifecycle CLI, task-ID
propagation, five named producer responsibilities, privacy/retention/disable
behavior, import/export, reports, recovery, and compatibility tests without
weakening this contract.

The build-loop HARVEST producer remains `planned/deferred` at this release
boundary and does not satisfy the five-producer completion obligation. Runtime
cleanup may remove unsafe caller-authorized seams, but live emission remains
blocked until the two T3.12 prerequisites receive separate approval.

Presence of the runtime is not evidence that every producer is active. A
producer may move from `planned` only through its governed activation evidence;
the public registry and producer descriptor remain the source of status truth.
