# Agent working rules — {{PROJECT_NAME}}

<!-- meoloom:working-rules -->

This document is part of the canonical `AGENTS.md` contract.

## What this repo is

**{{PROJECT_NAME}}** — {{PROJECT_DESC}}

Rules use RFC 2119 keywords. MUST / MUST NOT violations are blocking defects.

## Architecture rules (stack profile: {{PROFILE_NAME}})

{{PROFILE_ARCHITECTURE}}

## Quality gates (MUST)

{{PROFILE_GATES}}

## Silent-failure traps (inherited from the profile — extend per project)

{{PROFILE_TRAPS}}

## Scope control

Declare files you will touch before editing. Each phase (see
`spec/04-build-phases.md`) has a defined scope. Ask before crossing into
another phase's territory or editing root configs or `spec/`; spec changes are
proposals, not silent edits. Exception: appending to `spec/08-decisions.md` is
always allowed because it is the decision log.

## Plan gate (MUST)

When the prompt asks for a plan, present the plan and STOP. No mutating actions
until explicit approval. Ambiguous between plan and execute means default to a
plan and ask. During build-loop autopilot, the skill's PREFLIGHT is the single
approval stop and this gate relaxes as the skill defines.

## Effort

- Build phases or work touching DB schema or public API contracts: **high** —
  full build-loop with independent reviewers.
- Small fixes, docs, or spec edits: **medium** — run gates and a fresh-eyes pass.
- Q&A and lookups: **low** — answer directly without guessing checkable facts.

## Ground truth and decisions

Read files before editing. Probe real API and database response shapes before
building on them. Use primary sources over memory. Decide reversible in-scope
details yourself; ask before irreversible or destructive data operations, real
money, spec conflicts, or scope expansion.

## Reporting

Never declare done with failing or unrun gates. End substantive work with:

1. Done/fixed.
2. Left intentionally, with reason.
3. Remaining user actions, with exact commands in dependency order.
4. Concrete verification results; never merely claim that everything works.

## Never

Edit unread files. Re-ask what `spec/` or `spec/08-decisions.md` already
answers. Add ticket/scaffolding comments or commented-out code.
