---
name: kit-evolve
description: >-
  Governed EV-lite proposal miner for MeoLoom. Invoke when the user says "run
  kit-evolve", "mine one evolution proposal", or asks MeoLoom to inspect its
  committed lessons and scorecards for one recurring improvement. The skill
  selects its own theme, writes one proposal, and stops for Dat's approval.
---

# kit-evolve — mine one governed improvement

Produce exactly one evidence-backed EV-lite proposal. Do not implement it.

## Ground truth

Read these committed versions from `HEAD`, not uncommitted working copies:

1. `docs/contracts/evolution.md`
2. `lessons-learned/lessons-learned.md`
3. `benchmarks/scorecard.jsonl`

Use only evidence present in those committed files. Always select the theme
open-ended; never accept a candidate or theme supplied in the invocation as
the answer.

## Workflow

1. Confirm the current directory belongs to the intended MeoLoom Git worktree.
2. Extract recurring themes supported by at least two concrete evidence items.
3. Rank them by repeated impact, reversibility, and how directly MeoLoom can
   improve itself. Select exactly one highest-supported theme.
4. Create exactly one new file:
   `evolution/PROPOSAL-YYYY-MM-DD-<slug>.md`.
5. Fill every EV-lite field and section from the contract. Use
   `Status: proposed`, `Approved-by: n/a`, `Implementation: n/a`, and
   `Outcome: pending`. Cite the committed evidence precisely.
6. Report the proposal path, selected theme, and evidence references; then stop
   and wait for Dat to approve or reject it.

## Guardrails

- Write only the single proposal file. If its target path exists, stop without
  overwriting it.
- Do not edit source, tests, contracts, registries, benchmarks, lessons, or the
  evidence you read.
- Do not apply, approve, merge, commit, push, export, deploy, use networked
  services, or perform any external write.
- Do not create a second proposal in the same run.
- Dat remains the approval authority and final merge control.
