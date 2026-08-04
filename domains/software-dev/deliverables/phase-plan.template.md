# Phase plan — <phase N: title>

> Template for the PLAN phase (workflow.md). Delete guidance lines (>) when
> filling in. A plan is complete only when every section below is filled or
> explicitly marked "none for this phase".

## Scope

One paragraph: what this phase delivers, and what is explicitly OUT.

## Files to create/modify (grouped by area)

| Area | File | Action | Why |
|---|---|---|---|
| <data layer> | `path/to/file` | create/modify | <one line> |

## Endpoints / interfaces (with shapes)

> Request/response shapes, pagination, versioning. "None for this phase" if
> the phase has no contract surface.

## Components (with paths)

> UI or module components, exact paths, and their states (loading / empty /
> error / success where applicable).

## Test list

> Every test this phase adds or changes, by name. These become part of SW-G1.

## Risks

> Known traps (from lessons-learned/ and the stack profile), migration
> hazards, rollback story.

## Demo steps

> The exact steps that will be walked for SW-G2 — commands, URLs, expected
> observable results. Browser-only steps the user must perform are marked.

## Done-evidence this phase owes (gates.md)

- SW-G1: verbatim per-gate results (+ red-green proof output for any
  added/changed gate command)
- SW-G2: the demo steps above, walked, with observed results
- SW-G3: qa-agent PHASE DONE · code-reviewer APPROVE · security-reviewer
  APPROVE / skip-with-reason (trigger surfaces: see reviewers.md)
