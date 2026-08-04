# Host Adapter contract

Status: normative for MeoLoom 3.0 implementation. This document owns Host
Adapter descriptors, artifact lifecycle, conformance, project emission,
migration activation, retirement, and rollback. Host facts are dated evidence,
not permanent architecture claims.

## HA1. Boundary

A Host Adapter translates the canonical project contract and registered skills
into one host's supported discovery/pointer conventions. It must not duplicate
canonical policy, Domain Pack behavior, engine mechanics, or governance
authority. `AGENTS.md` remains the canonical generated-project contract; host
files are thin pointers or host-mandated descriptors.

Adapter files inside the MeoLoom plugin/repository are not automatically project
artifacts. Only a lifecycle-eligible FilePlan entry may be emitted.

## HA2. Descriptor and field ownership

`registry/adapters.json` is the Registry R2 child envelope with a required
`adapters` array and owns one closed descriptor per stable adapter ID:

| Field | Rule |
|---|---|
| `adapter_id` | Immutable stable identity. |
| `aliases` | Unique case-folded host names accepted by inventory/CLI lookup. |
| `contract_revision` | Host Adapter descriptor revision. |
| `host` | Stable host family name; display labels are non-authoritative. |
| `lifecycle` | Adapter-level minimum state across its artifacts. |
| `official_facts` | Dated source references, verified behavior, scope, and recheck gate. |
| `plugin_root_rules` | Host-mandated manifest/discovery paths and containment boundary. |
| `repository_artifact_paths` | Canonical paths required in the MeoLoom repository/plugin package. |
| `project_artifacts` | FilePlan-source descriptors owned by this adapter. |
| `pointer_semantics` | Canonical target, supported host mechanism, and missing-target behavior. |
| `policy_prohibition` | Explicit canonical owner and policy categories forbidden in adapter files. |
| `capability_assumptions` | Dated/fact-backed host capabilities required by conformance. |
| `conformance_fixtures` | Repository and live-host fixture IDs. |
| `smoke_command` | Argument vector for the fresh-session thin-trigger/pack smoke. |
| `migration_fixture_refs` | Clean/customized source-revision cases. |
| `rollback` | Adapter-owned paths and verification required to remove them safely. |

Each `project_artifacts` entry owns exactly the FilePlan fields from Registry
contract R5: `source_template`, `target_relative_path`, `ownership_class`,
`materialization_action`, `artifact_lifecycle`,
`project_contract_revision`, `expected_content_hash`, and `precondition`.
Adapters do not invent additional materialization behavior outside that entry.

`official_facts` entries contain `fact_id`, `verified_on`, `source_url`,
`claim`, `scope`, and `reverify_before`. A community report may motivate a test
but cannot become a normative host fact when primary documentation or a live
conformance test is available. `fact_id` is unique within the adapter.

Nested objects are closed:

- `plugin_root_rules` is exactly `{manifest_paths, skill_roots,
  containment_root, fresh_session_required}`; paths are arrays of canonical
  plugin-root-relative paths, `containment_root` is `plugin-root` or
  `extension-root`, and `fresh_session_required` is boolean.
- `pointer_semantics` is exactly `{canonical_target, mechanism,
  missing_target_behavior}`. The target is `AGENTS.md`; mechanism is a stable
  host-supported name such as `native` or `relative-import`; missing behavior
  is `clear-failure` or `documented-degradation`.
- `policy_prohibition` is exactly `{canonical_owner, forbidden_categories}`;
  canonical owner is `AGENTS.md`, and categories are selected from
  `canonical-policy`, `engine-policy`, `domain-policy`, and
  `governance-authority`.
- A capability assumption is exactly `{assumption_id, claim, fact_ref,
  required_for}` and must resolve to one `official_facts.fact_id`.
- `smoke_command` is a non-empty array of literal arguments, not a shell
  string. Placeholders are limited to `{plugin_root}` and `{project_root}` and
  are substituted as single arguments. The executor must direct-spawn the first
  argument with shell processing disabled and pass the remaining elements
  unchanged; it never joins or reparses argv. Shell interpreters (`sh`, `bash`,
  `cmd`, PowerShell/pwsh, and equivalents) and command-string flags such as
  `-c`, `/c`, or `-Command` are forbidden anywhere in format revision `1`
  command fields. Indirect launchers such as `env`, `command`, `xargs`, and
  `start` are also forbidden; the executable is always the declared first token.
- `rollback` is exactly `{owned_repository_paths, owned_project_paths,
  removal_precondition, verification_commands}`. Paths are canonical;
  removal precondition is `exact-adapter-owned-hash`; verification commands are
  direct-exec argument-vector arrays under the same no-shell rules and must
  include repository conformance after cleanup.

`verified_on` is a real `YYYY-MM-DD` calendar date. `source_url` is a non-empty
HTTPS URL, and `claim`, `scope`, and `reverify_before` are non-empty. An invalid
or stale fact blocks activation rather than degrading into an assumption.

## HA3. Artifact lifecycle

The only forward lifecycle is:

```text
repo_only → migration_ready → scaffold_active → retired
```

- `repo_only`: present and conformance-tested in MeoLoom; never emitted to a
  project in any FilePlan mode.
- `migration_ready`: preview and clean/customized brownfield fixtures exist;
  greenfield and migration emission remain off.
- `scaffold_active`: greenfield and explicitly approved migration may emit;
  add-missing remains non-replacing.
- `retired`: recognized for removal/preservation guidance; never emitted.

Transitions cannot skip a state. A rollback may move to the preceding state
only with the same evidence needed to prove emission is disabled and no
unowned artifact is removed. Adapter-level lifecycle is the least-advanced
state among its required artifacts and cannot hide mixed artifact states.

## HA4. Activation gates

Every transition to `scaffold_active` requires all of:

1. repository descriptor and generic synthetic-adapter conformance;
2. current official host behavior fact-check with dated primary sources;
3. a live/fresh-session smoke when the host is available;
4. clean and customized brownfield fixtures for every migratable source;
5. canonical project-contract checker green after materialization/migration;
6. no duplicated policy in host files;
7. exact adapter-owned rollback paths and a successful rollback rehearsal; and
8. an approved lifecycle decision at the governance class of the behavior.

Unavailable hosts remain `repo_only`; absence of a test environment is not
positive evidence. A registry entry never self-activates based on file presence.

## HA5. Conformance

Repository conformance checks closed descriptor fields, pointer thinness,
plugin-root containment, FilePlan equivalence, lifecycle emission rules,
generated manifest bytes, and fixture inventory. A synthetic adapter must be
addable by descriptor/template/fixtures without editing Python dispatch or Bash.

Live conformance uses a fresh installed-host session. Plugin or trigger changes
require reinstall/update plus a new session. Agentic file-origin smokes use a
per-run unpredictable oracle available only in the target file, run from an
empty working directory, compare after exit, and retain only a hash. A fixed
published sentinel is not file-read proof.

Missing files must produce an observable failure; the host must not silently
invent pack contents. Reads may resolve inside the plugin root but cannot
traverse outside it. A host-specific failure at that boundary selects the
documented Option B physical relocation without changing Domain Pack semantics.

## HA6. Project materialization and migration

The Catalog, not the Host Adapter implementation, produces the FilePlan.
Greenfield consumes only `scaffold_active` rows from the generated sanitized
manifest. `repo_only`, `migration_ready`, and `retired` rows publish no action.

Brownfield handling follows Registry R6: detect and classify before writes,
distinguish exact/customized/missing bytes using immutable snapshots, preserve
user content, show the FilePlan, obtain explicit approval, back up/hash, execute
preconditions, and verify checker + host smoke. `RETIRE_LEGACY` is a migration
action requiring explicit approval; deprecation alone never authorizes deletion.

Adapter-owned rollback removes only artifacts that still match the approved
adapter-owned snapshot. Customized or user-owned artifacts are preserved and
reported. The plan must not rely on Git history or silently overwrite a pointer.

## HA7. Initial v2.0 adapter states

Phase 1 inventory uses these states without emitting new project artifacts:

- Claude Code and Codex: current repository/plugin behavior fact-checked, but
  new v2 project artifacts remain `repo_only` until Phase 3 activation.
- Gemini CLI: `repo_only` until official facts and live-host availability meet
  HA4; documented degradation is explicit.
- Cursor: `repo_only`; `.cursorrules` is deprecated but still supported, so
  retirement occurs only through approved migration fixtures.

Current root host manifests remain host-mandated repository artifacts. Phase 1
does not relocate them or change released scaffolding.

## HA8. Diagnostics

| Code | Required condition |
|---|---|
| `ADAPTER_DESCRIPTOR_INVALID` | Closed descriptor field/type/invariant fails. |
| `ADAPTER_FACT_STALE` | Required dated host fact passed its recheck boundary. |
| `ADAPTER_LIFECYCLE_TRANSITION_INVALID` | State skipped, regressed unsafely, or mixed state hidden. |
| `ADAPTER_ACTIVATION_INCOMPLETE` | One or more HA4 gates missing. |
| `ADAPTER_EMISSION_FORBIDDEN` | FilePlan attempts emission outside `scaffold_active` rules. |
| `ADAPTER_POLICY_DUPLICATED` | Host artifact contains canonical/domain policy rather than a pointer. |
| `ADAPTER_ROOT_ESCAPE` | Resolved plugin/project path escapes its declared root. |
| `ADAPTER_CONFORMANCE_FAILED` | Repository or live-host fixture fails. |
| `ADAPTER_ROLLBACK_UNSAFE` | Removal target is unowned, customized, unresolved, or unrehearsed. |

Registry/project diagnostics remain authoritative for malformed fields,
revision state, FilePlan approval, migration conflicts, and unsafe generic
paths; adapters must not rename them.

## HA9. Extension, retirement, compatibility, rollback

Adding an adapter under the existing descriptor revision is compatible only if
generic registry, projection, and Bash consumers need no host-specific branch.
A new field/action/lifecycle state is a registry-format change under R9.

Retirement transitions active artifacts to `retired`, disables future
emission, retains recognition and migration guidance, then removes exact
unchanged adapter-owned files only through an approved FilePlan. Public support
windows and host deprecation dates are recorded; architecture docs use explicit
revisit conditions rather than “final” or “permanent.”

Rollback reverts one adapter descriptor, projections, fixtures, and lifecycle
decision together. If a project was changed, rollback consumes its pre-change
hashes/backup and preserves customization. It never broad-deletes a host
directory or affects another adapter.

## HA10. Review-only Python protocol sketch

```python
from typing import Literal, TypedDict

class OfficialFact(TypedDict):
    fact_id: str
    verified_on: str
    source_url: str
    claim: str
    scope: str
    reverify_before: str

class AdapterArtifact(TypedDict):
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

class PluginRootRules(TypedDict):
    manifest_paths: tuple[str, ...]
    skill_roots: tuple[str, ...]
    containment_root: Literal["plugin-root", "extension-root"]
    fresh_session_required: bool

class PointerSemantics(TypedDict):
    canonical_target: Literal["AGENTS.md"]
    mechanism: str
    missing_target_behavior: Literal["clear-failure", "documented-degradation"]

class PolicyProhibition(TypedDict):
    canonical_owner: Literal["AGENTS.md"]
    forbidden_categories: tuple[
        Literal["canonical-policy", "engine-policy", "domain-policy", "governance-authority"], ...
    ]

class CapabilityAssumption(TypedDict):
    assumption_id: str
    claim: str
    fact_ref: str
    required_for: str

class AdapterRollback(TypedDict):
    owned_repository_paths: tuple[str, ...]
    owned_project_paths: tuple[str, ...]
    removal_precondition: Literal["exact-adapter-owned-hash"]
    verification_commands: tuple[tuple[str, ...], ...]

class AdapterDescriptor(TypedDict):
    adapter_id: str
    aliases: tuple[str, ...]
    contract_revision: str
    host: str
    lifecycle: Literal["repo_only", "migration_ready", "scaffold_active", "retired"]
    official_facts: tuple[OfficialFact, ...]
    plugin_root_rules: PluginRootRules
    repository_artifact_paths: tuple[str, ...]
    project_artifacts: tuple[AdapterArtifact, ...]
    pointer_semantics: PointerSemantics
    policy_prohibition: PolicyProhibition
    capability_assumptions: tuple[CapabilityAssumption, ...]
    conformance_fixtures: tuple[str, ...]
    smoke_command: tuple[str, ...]
    migration_fixture_refs: tuple[str, ...]
    rollback: AdapterRollback
```

The sketch mirrors HA2–HA3 only and is not executable runtime policy.

## HA11. Implementation task references

- Phase 1B creates `repo_only` descriptors/FilePlan entries under HA2–HA3 and
  proves generic extension depth under HA5; it emits nothing.
- Phase 2 implements repository/live conformance and dated facts under HA4–HA5.
- Phase 3 performs migration previews and lifecycle activation under HA4/HA6;
  adapter-by-adapter rollback follows HA9.
