# Domain Pack contract

Status: normative for MeoLoom 3.0 implementation. This document owns the
six-slot interface, domain descriptor semantics, composition, trigger behavior,
and Domain Pack lifecycle. A registry descriptor is metadata, not a seventh
slot.

## DP1. Exact interface and load order

Every active Domain Pack has exactly these six semantic slots, loaded in this
order:

| Order | Slot | Artifact | Sole responsibility |
|---|---|---|---|
| 1 | `workflow` | `workflow.md` | Domain phases, decision flow, required inputs, and missing-information behavior. |
| 2 | `ground_truth` | `ground-truth.md` | Authoritative sources, evidence hierarchy, trust, and currency rules. |
| 3 | `gates` | `gates.md` | Stable gate IDs, criteria, worked pass/fail cases, gaming lines, and automation status. |
| 4 | `reviewers` | `reviewers.md` | Roles, routing, authority, verdict contract, and escalation. |
| 5 | `deliverables` | `deliverables/` | One or more named templates or examples for pack outputs. |
| 6 | `loop_profile` | `loop-profile.md` | Allowed Turn/Goal/Time/Proactive modes and evidence for the ceiling. |

An active pack missing a slot is invalid. `deliverables/` is one slot even when
it contains several files. Extra supporting files may exist only when a slot
links to them; they do not create new semantic slots.

## DP2. Descriptor and field ownership

`registry/domains.json` is the Registry R2 child envelope with a required
`domains` array and owns one closed descriptor per stable domain ID:

| Field | Owner and rule |
|---|---|
| `domain_id` | Registry identity; immutable after publication. |
| `contract_revision` | Domain Pack format revision understood by the Catalog. |
| `lifecycle` | `legacy`, `active`, or `retired`. |
| `pack_location` | Canonical plugin-root-relative directory containing the six slots. |
| `trigger` | Descriptor-owned `name`, `description`, and `aliases`; no policy body. |
| `required_engine_revision` | Exact engine revision composed with this pack. |
| `gate_authority_ref` | Stable typed role or opaque authority reference with succession. |
| `loop_ceiling` | `Turn`, `Goal`, `Time`, or `Proactive`; mirrors `loop-profile.md`. |
| `evolution_profile_ref` | Owner/class/policy reference in `evolution.json`. |

The descriptor owns discovery and composition metadata. Slot files own domain
behavior. The engine owns only `LOAD → SELF-QUESTION → PLAN → EXECUTE → VERIFY
→ REVIEW → REPORT → HARVEST` mechanics (canonical phase names per the Phase 4
ownership map, convention 5; materialized as `engine/work-loop/ENGINE.md`). It must not contain software terms, repository
operations, test commands, host model routing, or a profession's standards of
truth.

Phase 1 descriptors remain `legacy`: they inventory the existing v1.17 layout
but claim no six-slot behavioral conformance. Only the Phase 4 before/after
evals may change them to `active`.

`trigger.name` also owns the generated destination
`skills/<trigger.name>/SKILL.md`; `domain_id` never substitutes for it. Trigger
names obey Registry R3 stable-ID/path rules, and destinations are globally
unique.

## DP3. Slot requirements

### DP3.1 Workflow

The workflow declares entry assumptions, required inputs, what may be safely
assumed, what requires escalation, domain phases, stop conditions, and recovery
behavior. Host invocation and generic loop mechanics are references, not copied
policy.

### DP3.2 Ground truth

Ground truth ranks sources and states currency, provenance, uncertainty, and
conflict rules. It distinguishes authoritative evidence from examples and
memory. A source that cannot support a decision must not be upgraded by the
engine or trigger.

### DP3.3 Gates

Every gate has a stable ID, owner, criterion, at least one passing and failing
worked case, a gaming line, evidence contract, automation status, and closer
role. A gate that is actually gamed produces a same-day lesson and Class B
proposal revising its gaming line. A measurable gate is not treated as valid
until practitioner/owner evidence closes that validation.

### DP3.4 Reviewers

Reviewer routes state independence, authority, inputs, output/verdict schema,
retry/escalation behavior, and conflicts of interest. A proposer cannot close
the same proposal. Named host/model routing belongs to maintainer or Host
Adapter policy, not the reusable engine.

### DP3.5 Deliverables

Every pack supplies at least one usable template/example. A deliverable names
the gates and evidence expected before it is called complete. Templates do not
silently define workflow or gate policy.

### DP3.6 Loop profile

The profile explains which of Turn, Goal, Time, and Proactive are allowed and
why. `loop_ceiling` semantically equals the highest allowed mode; it is not an
aspirational target. Goal requires a validated measurable gate plus independent
review. Time requires an automated gate and real recurrence. Proactive requires
stable Goal+Time and low risk; high-risk domains remain notify-only. A ceiling
change is Class C.

## DP4. Composition and contradictions

Composition order is deterministic:

```text
canonical project contract → engine revision → descriptor + six slots
  → optional project profile → Host Adapter projection
```

Later layers may narrow execution but may not contradict earlier policy. A
contradiction or engine revision mismatch stops composition. The trigger loads
the declared engine, all six slots in DP1 order, then an optional project
profile. Execution routes deliverables, gates, and reviewers from the loaded
pack rather than trigger prose.

Project profiles may specialize a registered domain for one project but cannot
raise its loop ceiling, weaken gates, change authority, or redefine stable IDs.
Host Adapters translate host behavior only; they cannot alter domain semantics.

## DP5. Generated trigger

The descriptor owns trigger name, description, and aliases. The Projection
Module owns one standardized thin body which resolves the descriptor, checks
engine revision, loads DP1 slots, loads an allowed project profile, and emits a
named diagnostic on failure. It contains no independent domain policy.

Aliases are sorted and collision-checked before UTF-8/LF rendering. The child
registry's `registry_revision` is embedded as provenance. `--check`
is byte-exact. A changed descriptor or trigger requires render/eval, plugin
reinstall or update, and a fresh host session; an open/cached session is not
evidence.

## DP6. Lifecycle, extension, and retirement

Lifecycle transitions are `legacy → active → retired`:

- `legacy` is recognized/inventoried but not six-slot conforming or generated.
- `active` has a valid descriptor, six slots, generated trigger, conformance
  tests, installed-host load smoke, and approved loop ceiling.
- `retired` is recognized for guidance and alias conflict prevention but is not
  offered as an active trigger.

A new pack proves extension depth with a synthetic/non-software fixture: adding
its descriptor and six files requires no engine, renderer, shell, or validator
dispatch edit. Domain-builder authors descriptor + six slots + trigger source
metadata and inherits an evolution profile; sentence-marker detection is not
conformance.

Retirement records replacement/guidance, removes active trigger projection,
preserves stable ID/alias recognition for its compatibility window, and proves
that projects receive no silent mutation. Rollback restores one semantic owner;
old and new policy may never coexist as duplicates.

## DP7. Diagnostics

Domain diagnostics use the Registry diagnostic shape and stable codes:

| Code | Required condition |
|---|---|
| `DOMAIN_DESCRIPTOR_INVALID` | Closed descriptor field/type/invariant fails. |
| `DOMAIN_SLOT_MISSING` | Active pack lacks one of DP1's exact slots. |
| `DOMAIN_SLOT_INVALID` | Slot path/type/content contract is invalid. |
| `DOMAIN_ENGINE_REVISION_MISMATCH` | Descriptor requires a different engine revision. |
| `DOMAIN_LOOP_CEILING_MISMATCH` | Descriptor ceiling and loop profile disagree. |
| `DOMAIN_TRIGGER_MISSING` | Active domain lacks its generated trigger. |
| `DOMAIN_TRIGGER_STALE` | Trigger bytes do not match descriptor/render rules. |
| `DOMAIN_POLICY_CONTRADICTION` | Later composition layer contradicts earlier policy. |
| `DOMAIN_GATE_AUTHORITY_INVALID` | Gate has no valid independent closer/succession rule. |
| `DOMAIN_LIFECYCLE_INVALID` | Transition or lifecycle claim violates DP6. |

## DP8. Compatibility and rollback expectations

The v1.17 software-dev and knowledge-work behavior remains the before-baseline
until Phase 4. Cutover commits are grouped by semantic owner (engine,
software-dev, knowledge-work, project contract, maintainer policy), validated
after each move, and revert that whole slice on failure. No partial six-slot
claim reaches `master`.

Option A places packs under `domains/` inside the plugin root. If a dated live
host conformance test later disproves that boundary, Option B relocates physical
files beside skills without changing this interface, IDs, ownership, or tests.

## DP9. Review-only Python protocol sketch

```python
from typing import Literal, TypedDict

class TriggerDescriptor(TypedDict):
    name: str
    description: str
    aliases: tuple[str, ...]

class DomainDescriptor(TypedDict):
    domain_id: str
    contract_revision: str
    lifecycle: Literal["legacy", "active", "retired"]
    pack_location: str
    trigger: TriggerDescriptor
    required_engine_revision: str
    gate_authority_ref: str
    loop_ceiling: Literal["Turn", "Goal", "Time", "Proactive"]
    evolution_profile_ref: str

DOMAIN_SLOT_ORDER: tuple[str, ...] = (
    "workflow", "ground_truth", "gates", "reviewers", "deliverables", "loop_profile"
)
```

The sketch mirrors DP1–DP2 only. It is not a runtime schema and must not be
imported by Phase 1B code.

## DP10. Implementation task references

- Phase 1B inventories both current domains as `legacy` under DP2 and DP6; it
  must not claim DP1 conformance.
- Phase 4 creates the engine/slots/triggers under DP1–DP5 and proves DP6
  activation with real and synthetic pack evals.
- Phase 4 semantic-owner commits and rollback follow DP8; domain-builder changes
  follow DP6's extension rule.
