---
name: scorecard
description: >-
  Benchmark scoring for AI-assisted work sessions. Invoke at the END of any
  substantive task — or whenever the user says "scorecard", "score this
  task", "benchmark this session", "log this work", or "log this completed
  task". Scores the task on a
  fixed 1-5 complexity rubric, estimates manual hours saved (clearly labeled as
  an estimate), records actual wall time and gate results, and appends one JSONL
  line to the project's benchmarks/scorecard.jsonl through the append-only
  scripts/scorecard.py helper. Exact Claude session totals are attached only
  when one session maps to one task; ambiguous or unsupported attribution stays
  null with a reason code. The build-loop skill calls this automatically at the
  end of every phase; use it standalone for one-off tasks outside the build loop.
---

# scorecard — score a completed task

Score honestly. A benchmark built on flattering numbers is worse than no benchmark: it teaches the user to trust noise. Estimated values are always labeled as estimates.

## Complexity rubric (fixed — never improvise your own scale)

| Score | Meaning |
|---|---|
| 1 | One file, cosmetic or config change, no logic risk |
| 2 | Single-layer logic change, few files, existing tests cover it |
| 3 | Multi-file feature inside one layer/module, new tests needed |
| 4 | Cross-layer feature (data → domain → UI), migrations or new contracts, edge-case surface |
| 5 | Multi-phase or architectural: DB schema + public contract + several modules, high blast radius |

Half-points are allowed (e.g. 3.5) when genuinely between levels.

## Fields to record

- `date` — ISO date. `ts` — ISO timestamp of task end (used for token attribution before append).
- `task` — short label ("blog phase 1", "fix Form.config ftCode bug").
- `complexity` — from the rubric, with one line of justification in `notes`.
- `est_manual_hours` — your estimate of hands-on hours a competent developer would need without AI. Propose it with your reasoning in one line; if the user is present, let them adjust — their number wins. This is an ESTIMATE and stays labeled as such.
- `actual_wall_minutes` — real elapsed time for the task (from session timestamps if known, otherwise ask).
- `gates` — concrete results string ("pest 24/24 ✓, tsc ✓") or "none run" — never invent.
- `tokens` — supply `null`; the append helper replaces it with exact Claude
  session totals only when one transcript session maps to this task and no
  existing scorecard task maps to that session.
- `token_attribution` — written by the append helper: `status` is `exact` or
  `unknown`; `reason` is `exact_session_total`, `unsupported_provider`,
  `missing_timestamp`, `no_matching_session`, `multiple_matching_sessions`, or
  `ambiguous_multi_task_session`.
- `model` — which model did the work, if known.
- `schema_version` — always `2` for new records.
- `agent_runtime` — `claude-code`, `codex`, `cursor`, or `other`; use the enum from `scripts/contract_check.py`.
- `workflow` — `build-loop`, `standalone`, or a named Domain Pack; identifies the working discipline used.
- `canonical_contract_revision` — exact root `AGENTS.md` revision; use `none` only when no MeoLoom contract exists.
- `git_state` — `branch`, `head`, and `dirty`; Git values may be `null` only outside a Git repository.

Existing schema-v1 lines are historical records and remain valid before the v2
boundary. Every new line is strict schema v2; never append v1 after the first v2
record or rewrite history merely to normalize attribution.

## Process

### Host support

Resolve `DAT_KIT_ROOT` from the selected skill directory (two parent directories
up to the package root) before invoking the helper.
Use `python3 "$DAT_KIT_ROOT/scripts/scorecard.py" --provider <host>
--append-record <record.json> --project <project-root>` to append. The record may
also be supplied as JSON on stdin with `--append-record -`. Use `claude` for
Claude Code and `codex` for Codex. Codex token parsing remains unverified, so the
helper records `tokens: null` with `reason: unsupported_provider`.

1. Compute/propose all input fields with `tokens: null`. Show the candidate to
   the user in one compact block.
2. Pass that JSON object to the host-appropriate append command above. The
   helper is the only scorecard writer: it validates schema v2, resolves token
   attribution, and performs one append. Never edit, normalize, or rewrite
   existing lines. It fails closed on symlink, reparse-point, and hard-linked
   scorecard paths. Corrections are new records with a `supersedes` field.
3. For a report, run the same host command without `--append-record`.
   Report-time Claude attribution is display-only and never persists. Never
   invoke the Claude transcript parser from Codex.

Example line:

```json
{"schema_version":2,"ts":"2026-07-12T15:04:00+07:00","date":"2026-07-12","task":"blog phase 1 — data layer","complexity":4,"notes":"migrations + repos + DTOs across api/, seeders","est_manual_hours":6,"actual_wall_minutes":42,"gates":"pest 18/18 ✓, pint ✓","tokens":null,"model":"sonnet-5","agent_runtime":"codex","workflow":"build-loop","canonical_contract_revision":"MeoLoom 3.0","git_state":{"branch":"main","head":"abc123","dirty":false}}
```

## What NOT to do

Do not inflate `est_manual_hours` to make the tool look good — when unsure,
estimate low. Do not fill `tokens` or `token_attribution` yourself; the helper
owns both. Do not score trivial Q&A exchanges — the benchmark is for work, not
chat.
