# Registry contract

Status: normative for MeoLoom 3.0 implementation. This document owns registry
formats, bootstrap order, the Catalog boundary, FilePlan semantics, project
contract revisions, and the two current projections. Examples and Python sketches
illustrate this contract; they do not override it.

## R1. Authority and atomicity

`registry/platform.json` is the only hardcoded registry entrypoint. Registry
JSON is authoritative; generated files and examples are derived artifacts. A
Catalog is either completely valid or unavailable: callers must receive all
diagnostics and no partially loaded Catalog when any bootstrap, child, or
cross-reference check fails.

Implementations use the Python standard library and must not claim JSON Schema
compliance. JSON files are UTF-8 objects with no duplicate keys. Every object
uses a closed field set; an unknown field is an error with its JSON path.

## R2. Bootstrap format and load order

The bootstrap object owns these fields:

| Field | Type | Rule |
|---|---|---|
| `format_revision` | integer | Required. Current code supports only `1`. |
| `registry_revision` | string | Required stable revision of this bootstrap payload. |
| `release_version` | string | Required single SemVer owner for the MeoLoom release. |
| `version_targets` | array | Required closed locations that must mirror `release_version`. |
| `children` | array | Required non-empty list of child references. |
| `canonical_revision` | string | Required; `MeoLoom 3.0`. |
| `green_revisions` | array of strings | Required; exactly revisions accepted as current. |
| `migratable_source_revisions` | array of strings | Required; recognized but non-green sources. |
| `unsupported_revisions` | array of strings | Required guidance categories, not green states. |
| `revision_descriptors` | array | Required immutable recognition metadata per named revision. |
| `migration_edges` | array | Required allowed source-to-target migrations; may be empty. |

A child reference is exactly
`{kind, path, revision}`. v2.0 requires one each for `domains`, `adapters`, and
`evolution`. `path` is a canonical repository-relative POSIX path under
`registry/`; `revision` must equal the loaded child's `registry_revision`.
Each child is a closed object with `format_revision = 1`,
`registry_revision`, `contract_revision`, and its kind-specific arrays/fields.
The child's `format_revision` must be supported by the same atomic code/data
release as the bootstrap.

A `revision_descriptors` item is exactly `revision`, `marker_rules`,
`required_pointer_paths`, `static_template_hashes`, `snapshot_provenance`, and
`support_removal_not_before`. A marker rule is exactly `{path, required_text}`.
Hashes map canonical target paths to lowercase SHA-256. A `migration_edges`
item is exactly `migration_id`, `source_revision`, `target_revision`, and
`status`, where status is `planned`, `available`, or `retired`.

A `version_targets` item is exactly `{path, kind, locator}`. In format revision
`1`, `kind` is only `json-pointer`; `locator` is an RFC 6901 pointer to a string
field. `path` is canonical and unique. The target string must equal the SemVer
`release_version`; the Catalog derives rather than stores the expected value.
Checking targets is validation, not a third projection. A release commit changes
the one owner and its mirrors together, then proves equality.

Pointer evaluation decodes only `~0` and `~1`. When the current value is an
array, the next token must be ASCII `0` or `[1-9][0-9]*`; leading-zero,
non-ASCII, negative, out-of-range, scalar-traversal, and malformed-escape tokens
fail. Implementations must not delegate these rules to a permissive pointer
library without conformance probes.

Load order is fixed:

1. Check bootstrap existence.
2. Decode JSON and require an object.
3. Validate `format_revision` before reading any child.
4. Validate bootstrap fields and child-reference uniqueness.
5. Read every referenced child without publishing Catalog state.
6. Validate child revisions, closed schemas, paths, IDs, and cross-references.
7. Publish one immutable Catalog only if the complete graph is valid.

A future bootstrap revision therefore fails before a missing or malformed child
can influence the result. Code and registry data that require different format
revisions fail as one atomic-upgrade error.

## R3. Common lexical and ownership rules

Stable IDs and registry revisions match `[a-z][a-z0-9-]*(/[0-9]+)?`; IDs are
case-sensitive and unique within their registry. User-facing aliases compare
after Unicode case-folding and surrounding-whitespace removal. Trigger names
and aliases share one globally unique invocation namespace across all domain
descriptors, including retired domains.

Repository-relative paths use `/`, are non-empty NFC text, and must already be
in canonical form; normalization that changes the submitted string is rejection,
not repair. Empty, `.`, or `..` segments; repeated separators; absolute,
drive-qualified, or UNC forms; backslashes; Unicode `Cc` controls; Windows
reserved device basenames (`CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, and
`LPT1`-`LPT9`, including extensions); colons/ADS; portable-illegal
`<>:"|?*`; and segments ending in a space or dot are forbidden.

Every collection of source or target paths also rejects collisions under the
supported target filesystem identity: NFC plus per-segment Unicode case-folding
at minimum. A consumer may add stricter filesystem-specific collision rules but
may not relax this portable identity. For filesystem access, it walks from an
already-open declared-root handle component by component without following
symlinks or reparse points, verifies each opened component remains below that
root, and rejects any alias or link escape.

Each descriptor field has one owning child registry. Cross-references name an
owner; they never copy the referenced policy. Generated artifacts inherit the
governance class and owner of their source descriptor.

## R4. Catalog boundary

The public Registry Module exposes one deep interface:

```text
Catalog.load(repo_root) -> Catalog | Diagnostic[]
Catalog.domains() -> DomainDescriptor[]
Catalog.adapters() -> AdapterDescriptor[]
Catalog.evolution_policy() -> EvolutionCatalog
Catalog.scaffold_file_plan(mode) -> FilePlan
Catalog.version_targets() -> VersionTarget[]
Catalog.governed_paths() -> GovernedPathSet
Catalog.explain_path(path) -> OwnershipExplanation
```

`load` is the only supported constructor. Returned collections are
deterministic, sorted by stable ID or canonical path, and defensive copies.
`explain_path` is read-only and reports the matched root/exclusion, owner,
governance class, required evidence, gates, reviewers, authority reference, and
source descriptor. It never mutates a project or creates a proposal.

`load` validates the registry graph only. It does **not** sweep the working
tree: the governed-inventory check (`validate_governed_inventory() ->
Diagnostic[]`) runs at validation entry points (`scripts/validate.py`,
`registry.py validate`), so a stray untracked file fails validation without
bricking every Catalog consumer. `load` performs no subprocess call.

Convenience members, stable but secondary to the eight methods above:
`load_or_raise(repo_root)` (raises `CatalogLoadError` carrying the same
diagnostics), the read-only properties `registry_revision`, `release_version`,
and `domain_registry_revision`, `pointer_inventory()` (per-adapter
`scaffold_active` project targets, consumed by the contract checker),
`validate_governed_inventory()`, and `revision_model()` — a defensive copy of
the project-contract state machine (`canonical_revision`, `green_revisions`,
`migratable_source_revisions`, `unsupported_revisions`,
`revision_descriptors`, `migration_edges`, and loaded snapshots), consumed by
the Phase 3 contract checker so no second parser of `platform.json` exists.
Anything not listed in this section is internal; new members require a
contract amendment first.

`version_targets()` returns deterministic records containing `path`, `kind`,
`locator`, and derived `expected_version`. A missing target, invalid locator, or
mismatched mirror is diagnostic. Adding a target under `json-pointer` is
compatible; adding a kind or changing version ownership changes the format.

`evolution_policy()` returns the complete Evolution Catalog graph defined by
Evolution EV10, not one policy record. `governed_paths()` returns its immutable
roots/exclusions/component-class subset as `GovernedPathSet`; `explain_path()`
returns one `OwnershipExplanation`.

## R5. FilePlan

A FilePlan is an ordered, read-only preview. Each entry has exactly:

| Field | Meaning |
|---|---|
| `source_template` | Canonical path inside the MeoLoom/plugin root. |
| `target_relative_path` | Canonical path inside the target project. |
| `ownership_class` | `dat-kit`, `adapter`, or `user`. |
| `materialization_action` | Registry R5 closed action under format revision `1`. |
| `artifact_lifecycle` | Host Adapter lifecycle controlling whether emission is allowed. |
| `project_contract_revision` | Revision whose bytes/shape the entry implements. |
| `expected_content_hash` | SHA-256 of static expected bytes, or explicit `null` for rendered/user-owned content. |
| `precondition` | Named condition that must hold before the action. |

Modes are `greenfield`, `add-missing`, `inspect-brownfield`, and
`migrate-approved`:

- `greenfield` may materialize only `scaffold_active` entries into a new target.
- `add-missing` may add an absent active artifact but never replace content.
- `inspect-brownfield` reports classification only and never writes.
- `migrate-approved` requires a displayed plan, explicit approval, a pre-change
  snapshot/backup, and satisfied entry preconditions before mutation.

Plans sort by target path and reject duplicate targets. Planning never implies
approval. No registry entry silently becomes a project write.

Execution reopens from the declared-root handle, rechecks the target identity,
type, absence/hash, and parent chain immediately before each mutation, and fails
the whole operation if any value differs from the preview. Writes use a temporary
file created in the verified target directory, flush as required, then atomically
replace only the approved target; removals operate through the verified parent
handle and exact target identity. Symlink/reparse swaps, case aliases, and
check-to-use changes are errors, never reasons to follow a new path. Rollback
uses the same rules.

Registry format revision `1` owns the materialization action vocabulary:

- `copy`: write source bytes exactly to an absent/approved target;
- `render-pointer`: deterministically render only the Host Adapter pointer
  semantics to an absent/approved target;
- `preserve`: publish no write; retain and report existing user/customized
  content; and
- `RETIRE_LEGACY`: remove only an exact adapter-owned legacy artifact during
  `migrate-approved`, after explicit approval and backup.

The closed precondition vocabulary is `target-absent`,
`target-exact-expected-hash`, `target-user-owned-preserve`, and
`approved-backup-and-exact-hash`. `greenfield`/`add-missing` writes require
`target-absent`; `preserve` requires `target-user-owned-preserve`;
`RETIRE_LEGACY` requires `approved-backup-and-exact-hash`. A replacement copy
or pointer render requires `target-exact-expected-hash` plus the mode-level
approved backup from R5. Adding an action or precondition changes the registry
format and follows R9.

`copy` and `RETIRE_LEGACY` require a non-null expected SHA-256;
`target-exact-expected-hash` always requires one. `render-pointer` may use null
because bytes are rendered deterministically from pointer semantics; `preserve`
uses user ownership and publishes no expected replacement bytes.

## R6. Project contract revision state machine

For MeoLoom 3.0:

- `canonical_revision = "MeoLoom 3.0"`;
- `green_revisions = ["MeoLoom 3.0"]`;
- `migratable_source_revisions = ["dat-kit 2.0", "dat-kit 1.16.0"]`;
- pre-marker and unknown revisions are unsupported-with-guidance.

A recognized dat-kit 2.0 or v1.16 project returns nonzero
`CONTRACT_MIGRATION_REQUIRED`; it is not green. A revision descriptor owns
marker rules, required pointer set,
static-template hashes, snapshot provenance, migration edges, and the earliest
release allowed to remove support. Recognition and migration rely on shipped
immutable snapshot metadata, never Git history. Removing v1.16 source support
before the next major release is Class C.

A file-backed `snapshot_provenance` resolves to a closed object with exactly
`format_revision`, `snapshot_revision`, `project_contract_revision`, and
`files`. Its format matches the bootstrap, its project revision matches the
owning descriptor, and `files` is a sorted, portable-unique array of exact R5
FilePlan entries. For the **canonical** revision's snapshot — the only
scaffold source — every `copy` source exists and its canonical shipped
UTF-8/LF SHA-256 equals both the entry hash and the descriptor's
`static_template_hashes[target_relative_path]`. A **historical** revision's
snapshot is an immutable record of what already-scaffolded projects have on
disk: live templates move on, so its hashes are never compared against live
template bytes; instead each entry hash must equal the owning descriptor's
`static_template_hashes[target_relative_path]`. This preserves recognition of
already-scaffolded projects without treating historical snapshots as current
scaffold sources.
Scaffold FilePlans draw snapshot rows from the canonical revision's snapshot
only; historical snapshots serve recognition and migration. Repository
attributes pin these text inputs to LF so the snapshot is identical on
Windows and Linux. A fragment-valued provenance points to the owning registry
record and is not a file snapshot.

Detection precedes writes. Migration classifies exact/customized/missing state,
preserves user-authored policy, displays the FilePlan, snapshots hashes, and
verifies the result with the new checker and host smokes. Partial or unknown
states are inspect-only until an approved migration can classify every target.

## R7. Projection Module

MeoLoom 3.0 has exactly two projections owned by `scripts/render.py`:

1. `domain-trigger <domain-id>` from a domain descriptor; and
2. `scaffold-manifest` at `templates/common/.meoloom-files.tsv` from the
   Catalog FilePlan surface.

`all` renders both kinds; `--check` compares expected bytes and never rewrites.
Output is UTF-8, LF, terminal-newline, deterministic for the same Catalog, and
contains `GENERATED FROM REGISTRY — DO NOT EDIT` plus source revision. Paths,
IDs, aliases, and references validate before rendering. Missing, hand-edited,
or stale output fails byte-exact checking.

The domain-trigger destination is `skills/<trigger.name>/SKILL.md` after
`trigger.name` passes the stable-ID/path rules. `domain_id` is lookup identity,
not an output directory: `software-dev` therefore renders to
`skills/build-loop/SKILL.md`. Two descriptors resolving to one destination are
`PROJECTION_DESTINATION_COLLISION` and publish no projection.

The manifest begins with exactly one provenance line:
`# GENERATED FROM REGISTRY — DO NOT EDIT; source_revision=<revision>`. Bash
validates that line but never treats it as a row. The remaining row contract is
`source_rel<TAB>target_rel<TAB>ownership<TAB>action<TAB>introduced_revision<TAB>lifecycle`.
Fields contain no tabs/newlines, unsafe paths, or shell metacharacters; enums
are closed and versioned. Bash validates the complete manifest and publishes no
partial materialization plan on an invalid tail. Only `scaffold_active` rows may
materialize. There is no `eval` and no JSON parsing in Bash.

Manifest mapping is exact: `source_template → source_rel`,
`target_relative_path → target_rel`, `ownership_class → ownership`,
`materialization_action → action`, `project_contract_revision →
introduced_revision`, and `artifact_lifecycle → lifecycle`.
`expected_content_hash` and `precondition` are not projected because the Bash
manifest is greenfield-only: the renderer may include an entry only when its
precondition is `target-absent`; Python retains all fields for other modes.
Because the manifest aggregates adapter, project-revision, and lifecycle data,
its `<revision>` is exactly bootstrap `platform.json.registry_revision`.
Domain-trigger provenance remains the domains child's `registry_revision`.

`docs/domains.md` and `docs/loops.md` are consistency-checked documentation,
not additional Projection Module outputs.

## R8. Diagnostics

Every diagnostic contains `code`, human message, source path, optional JSON
path, and optional related paths. Codes are stable API; wording is not.
Validation is deterministic and reports independent errors in canonical
source/JSON-path order.

The complete emitted vocabulary is enumerated below, grouped by family. A code
appearing in code but not in this table, or removed from this table while still
emitted, is a contract violation; `scripts/tests/test_diagnostic_codes.py`
enforces the subset mechanically in both directions.

**Bootstrap and child graph**

| Code | Required condition |
|---|---|
| `REGISTRY_BOOTSTRAP_MISSING` | Bootstrap path absent. |
| `REGISTRY_BOOTSTRAP_MALFORMED` | Not a decodable JSON object, duplicate key, or empty/non-array `children`. |
| `REGISTRY_FORMAT_UNSUPPORTED` | Bootstrap format not understood; checked before children. |
| `REGISTRY_CHILD_MISSING` | Referenced child absent, or a required child kind never loaded. |
| `REGISTRY_CHILD_MALFORMED` | Referenced child undecodable, not an object, or duplicate keys. |
| `REGISTRY_CHILD_KIND_INVALID` | Child reference declares an unsupported kind. |
| `REGISTRY_CHILD_PATH_INVALID` | Child path escapes `registry/`. |
| `REGISTRY_CHILD_DUPLICATE` | Two references declare the same child kind. |
| `REGISTRY_CHILD_REVISION_MISMATCH` | Child revision differs from bootstrap reference. |
| `REGISTRY_ATOMIC_UPGRADE_REQUIRED` | Code and registry graph require incompatible format revisions. |

**Generic schema and value**

| Code | Required condition |
|---|---|
| `REGISTRY_UNKNOWN_FIELD` | Closed object contains an undeclared field. |
| `REGISTRY_REQUIRED_FIELD_MISSING` | Required field absent. |
| `REGISTRY_TYPE_INVALID` | Value has the wrong JSON type. |
| `REGISTRY_INVALID_VALUE` | Enum, lexical, or invariant violation. |
| `REGISTRY_PATH_INVALID` | Canonical/containment path rule fails. |
| `REGISTRY_PATH_COLLISION` | Two portable path keys collide. |
| `REGISTRY_HASH_INVALID` | Digest is not a lowercase SHA-256. |
| `REGISTRY_REVISION_INVALID` | Registry revision fails the stable-ID rule. |
| `REGISTRY_RELEASE_VERSION_INVALID` | Release version is not SemVer. |
| `REGISTRY_PROJECT_REVISION_INVALID` | Project-contract revision fields differ from format 1. |
| `REGISTRY_REVISION_DUPLICATE` | Duplicate revision descriptor. |

**Version mirrors**

| Code | Required condition |
|---|---|
| `REGISTRY_VERSION_KIND_INVALID` | Mirror kind unsupported in format 1. |
| `REGISTRY_VERSION_TARGET_INVALID` | Mirror path/locator unreadable or unresolvable. |
| `REGISTRY_VERSION_MISMATCH` | Mirror value differs from bootstrap `release_version`. |

**Snapshots and file plans**

| Code | Required condition |
|---|---|
| `REGISTRY_SNAPSHOT_INVALID` | Snapshot unreadable, malformed, or hashing failed. |
| `REGISTRY_SNAPSHOT_REVISION_MISMATCH` | Snapshot revision differs from its descriptor. |
| `REGISTRY_SNAPSHOT_HASH_MISMATCH` | Canonical snapshot/descriptor hash disagrees with live template bytes, or a historical snapshot disagrees with its descriptor's `static_template_hashes`. |
| `REGISTRY_SOURCE_MISSING` | Referenced template/artifact file absent. |
| `REGISTRY_SOURCE_HASH_MISMATCH` | Template bytes differ from declared hash. |
| `REGISTRY_FILEPLAN_INVALID` | FilePlan entry enum/precondition/hash invariant fails. |

**Domains, triggers, adapters**

| Code | Required condition |
|---|---|
| `REGISTRY_DOMAIN_ID_INVALID` / `REGISTRY_DOMAIN_ID_DUPLICATE` | Domain ID fails stable-ID rule / collides. |
| `REGISTRY_DOMAIN_LIFECYCLE_INVALID` | Domain lifecycle outside the closed enum. |
| `REGISTRY_TRIGGER_INVALID` | Trigger name/alias fails lexical rules. |
| `REGISTRY_TRIGGER_ALIAS_COLLISION` | Normalized trigger aliases collide. |
| `DOMAIN_SLOT_MISSING` | Active pack lacks one of the six slots. |
| `REGISTRY_ADAPTER_ID_INVALID` / `REGISTRY_ADAPTER_ID_DUPLICATE` | Adapter ID fails stable-ID rule / collides. |
| `REGISTRY_ADAPTER_LIFECYCLE_INVALID` | Adapter lifecycle outside enum, or below its artifacts' minimum. |
| `REGISTRY_ADAPTER_ALIAS_INVALID` / `REGISTRY_ADAPTER_ALIAS_COLLISION` | Adapter alias empty / collides. |
| `REGISTRY_FACT_INVALID` / `REGISTRY_FACT_ID_DUPLICATE` / `REGISTRY_FACT_REF_MISSING` | Official-fact record malformed / duplicated / dangling reference. |

**Evolution governance**

| Code | Required condition |
|---|---|
| `EVOLUTION_CLASS_INVALID` | Governance class outside A/B/C. |
| `EVOLUTION_GLOB_INVALID` | Component glob uses unsupported syntax. |
| `EVOLUTION_ORPHAN_PATH` | Tracked product path matches no governed root or component. |
| `EVOLUTION_OWNERSHIP_AMBIGUOUS` | Path matches more than one root or component. |
| `EVOLUTION_EXCLUSION_AMBIGUOUS` | Path matches more than one explicit exclusion. |
| `EVOLUTION_AUTHORITY_REQUIRED` | Policy or domain references a missing authority. |
| `EVOLUTION_POLICY_MISSING` | Component or domain references a missing/mismatched policy. |
| `EVOLUTION_SIGNAL_UNAVAILABLE` | Policy requires a missing or `planned` signal. |

**Projections (Projection Module)**

| Code | Required condition |
|---|---|
| `PROJECTION_MISSING` | Required derived artifact absent. |
| `PROJECTION_BYTE_MISMATCH` | Committed bytes differ from the authoritative render. |
| `PROJECTION_STALE_OUTPUT` | A marked generated file has no active descriptor owner. |
| `PROJECTION_DESTINATION_COLLISION` | Two source descriptors derive the same output path. |
| `DOMAIN_NOT_FOUND` / `DOMAIN_LIFECYCLE_INELIGIBLE` | Render request names an unknown / non-active domain. |

**Reserved (defined by this contract, emitted by the Phase 3 migration
machinery, not by the Phase 1 registry):** `CONTRACT_MIGRATION_REQUIRED`,
`CONTRACT_UNSUPPORTED_REVISION`, `CONTRACT_PARTIAL_MIGRATION`,
`CONTRACT_MIGRATION_CONFLICT`, `FILE_PLAN_PRECONDITION_FAILED`,
`FILE_PLAN_APPROVAL_REQUIRED`.

## R9. Extension, retirement, compatibility, rollback

Adding a child kind, field, enum value, projection kind, or bootstrap revision
is a format change: older code must fail closed, and code/data ship atomically.
Adding a descriptor under an existing closed schema needs red-before-green
extension fixtures proving no Python or shell dispatch edit is required.

Retirement first removes active references/emission, then preserves recognition
and guidance for the documented compatibility window. Generated projections
retire with their source owner. A rollback reverts descriptor, implementation,
projection, and fixtures as one slice; it never hand-edits a projection or
restores duplicate policy.

**Format freeze — MeoLoom 3.0.0 successor train (2026-08-03).** The
registry format and the project-contract format are frozen for the 2.0.0
release: `format_revision` remains `1` across the bootstrap, every child, and
every snapshot; the canonical project-contract revision is `MeoLoom 3.0`;
`green_revisions` is exactly `["MeoLoom 3.0"]` and
`migratable_source_revisions` is exactly `["dat-kit 2.0", "dat-kit 1.16.0"]`.
The dat-kit 2.0.0 freeze remains an immutable historical snapshot, not the
current green revision. Any change to these values after this cutover is a
format change under this section and reopens the release train. The freeze is
mechanically pinned by
`scripts/tests/test_format_freeze.py`; amending it requires updating that pin
test and this statement in the same commit.

## R10. Review-only Python protocol sketch

This non-executable sketch contains no semantics beyond R1–R9:

```python
from pathlib import Path
from typing import Literal, Protocol, TypedDict

class Diagnostic(TypedDict):
    code: str
    message: str
    source_path: str
    json_path: str | None
    related_paths: tuple[str, ...]

class FilePlanEntry(TypedDict):
    source_template: str
    target_relative_path: str
    ownership_class: Literal["dat-kit", "adapter", "user"]
    materialization_action: Literal["copy", "render-pointer", "preserve", "RETIRE_LEGACY"]
    artifact_lifecycle: Literal["repo_only", "migration_ready", "scaffold_active", "retired"]
    project_contract_revision: str
    expected_content_hash: str | None
    precondition: Literal[
        "target-absent",
        "target-exact-expected-hash",
        "target-user-owned-preserve",
        "approved-backup-and-exact-hash",
    ]

class FilePlan(TypedDict):
    mode: Literal["greenfield", "add-missing", "inspect-brownfield", "migrate-approved"]
    entries: tuple[FilePlanEntry, ...]

class VersionTarget(TypedDict):
    path: str
    kind: Literal["json-pointer"]
    locator: str
    expected_version: str

class CatalogProtocol(Protocol):
    @classmethod
    def load(cls, repo_root: Path) -> "CatalogProtocol | list[Diagnostic]": ...
    def domains(self) -> tuple["DomainDescriptor", ...]: ...
    def adapters(self) -> tuple["AdapterDescriptor", ...]: ...
    def evolution_policy(self) -> "EvolutionCatalog": ...
    def scaffold_file_plan(self, mode: str) -> FilePlan: ...
    def version_targets(self) -> tuple[VersionTarget, ...]: ...
    def governed_paths(self) -> "GovernedPathSet": ...
    def explain_path(self, path: str) -> "OwnershipExplanation": ...
```

Quoted cross-contract types are the exact review-only sketches in
`domain-pack.md`, `host-adapter.md`, and `evolution.md`; Registry does not own
second copies.

## R11. Implementation task references

- Phase 1B bootstrap/Catalog implements R1–R4 and R8 before any consumer.
- Phase 1B FilePlan and scaffold manifest implement R5 and R7 together; their
  conformance fixture proves one Catalog plan drives Python and Bash.
- Phase 1B immutable v1.16 metadata and Phase 3 migration implement R6.
- Every Phase 1B extension fixture and future format change follows R9.
