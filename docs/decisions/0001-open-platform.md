# ADR 0001: Open-platform registry and six-slot Domain Packs

- Status: accepted
- Public baseline: MeoLoom 3.0
- Owner and approving authority: Dat Mai Ba

## Context

MeoLoom supports multiple work domains and multiple agent hosts. Keeping domain
policy inside one host-facing skill would duplicate policy and make generated
surfaces drift.

## Decision

Keep the reusable work-loop engine under `engine/`, Domain Packs under
`domains/`, and generated thin host entrypoints under `skills/`. A Domain Pack
has exactly six semantic slots: `workflow`, `ground_truth`, `gates`,
`reviewers`, `deliverables`, and `loop_profile`. Registry descriptors are
metadata, not a seventh slot.

Registry validation remains Python-standard-library-only. Greenfield
initialization remains Bash-only through a generated sanitized TSV projection.
Host adapters advance through `repo_only → migration_ready → scaffold_active →
retired`. `MeoLoom 3.0` is the current green contract; `dat-kit 2.0` and
`dat-kit 1.16.0` are recognized migration sources.

## Conditions to revisit

Revisit the physical layout only when official host behavior or a repeatable
conformance test shows that a supported host cannot resolve registered files,
or when a security review identifies a changed trust boundary. A revisit is
Class C and requires current evidence, two independent reviews, regression
proof, rollback proof, and a new decision record.
