# Agent working rules — MeoLoom maintainers

This document is part of the root `AGENTS.md` contract. It contains no generated
project placeholders.

## Architecture

- `templates/common/AGENTS.md` is the canonical generated-project entrypoint.
- `templates/common/docs/agent-*.md` contain shared generated-project policy.
- Runtime compatibility pointers are derived from `scripts/contract_check.py`'s
  registry and contain no substantive policy.
- Skills define reusable workflows; `scripts/validate.py` and `scripts/tests/`
  enforce their packaging and evidence contracts.

## Quality gates

Run from the repository root:

```text
python scripts/validate.py
pytest scripts/tests
bash -n scripts/init.sh
shellcheck scripts/init.sh
git diff --check
```

When a gate itself changes, prove red-before-green with an isolated failing
fixture before trusting the final green run.

For a red gate, preserve a private, access-scoped command-start log containing
the command, cwd, relevant input or environment identity, diagnostic, stdout,
stderr, exit status, and completion status; never log secrets. Classify the
cause as `change-induced`, `pre-existing`, `environment`, or `unknown`.
`Unknown` and an interrupted run are not passes. QA reports the cause, exact
evidence, and condition for rerun, then stops; it never repairs. The controller
assigns an owner and an authorized response before a warranted rerun.

Rerun only for a relevant input or environment change, a concrete evidence gap,
or Dat's explicit request. Diagnose unchanged known failures instead of
speculatively rerunning the full suite. Focused checks are diagnostic or repair
evidence, never whole QA; final closure still runs every gate required by the
plan and governance. Preserve the existing one evidence-based consult and one
final retry discipline; persistent failure stops with logs and remaining work.

## Scope and evidence

- Preserve user changes and append-only benchmark history.
- Brownfield scaffolding must inspect before it mutates and fail closed on any
  competing instruction source, unsafe path, or incompatible partial install.
- New scorecard records use schema v2; historical v1 records are not rewritten.
- Whenever a skill description changes, add or update its positive trigger case
  in `benchmarks/skill-evals.jsonl`.

## Token discipline

- Grep before Read; Read targeted line ranges of large files, never whole files
  by default.
- Never re-read a file just edited or already summarized in this session.
- Resume from the newest `handoffs/` file instead of re-deriving state from the
  tree.
- Reviewer subagents run sequentially (never in parallel), read only the diff
  plus touched files, cap their reports, and re-review findings-scoped — per
  the scope-discipline blocks in `agents/*.md`.
- A session executing a plan phase loads only that phase's section plus the
  standing-discipline section — not the whole plan.

## Traps

- Git line endings differ across Windows and Linux; compare normalized text.
- A workflow file is not proof CI ran; verify a real run before release.
- Installed plugins and active sessions retain old metadata until reinstall or
  update and a fresh session.
