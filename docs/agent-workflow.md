# Agent workflow — MeoLoom maintainers

This document is part of the root `AGENTS.md` contract.

## Execution

Load the approved plan, current Git state, relevant source, and lessons before
editing. Work dependency-first, keep changes commit-sized, and run every declared
gate before reporting completion. Plans and spec amendments require explicit
approval; execution of an already approved plan does not require a second gate.

## QA evidence intake (R1 — External Verification Receipt Gate)

The `review-evidence` CI job (`.github/workflows/ci.yml`) runs Ruff, mypy
(report-only), pytest with JUnit output, validate.py, ShellCheck, `bash -n`,
and `git diff --check`. It writes the compact `reports/summary.json` receipt.
For a PR, its `source_head_sha` is the reviewed PR head while its
`tested_commit_sha` is GitHub's tested synthetic merge commit; `candidate_commit`
remains a compatibility alias of the latter.

For QA, begin with independently known identity from the active review task:
repository, current PR number, and current reviewed source SHA. Do not discover
those values from the receipt. Query:

```text
gh api repos/<repository>/pulls/<pr-number>                         # PR only
gh api repos/<repository>/actions/runs/<run-id>
gh api repos/<repository>/actions/runs/<run-id>/artifacts
gh api repos/<repository>/actions/artifacts/<artifact-id>/zip
gh api repos/<repository>/git/commits/<tested-commit-sha>
```

Accept a receipt only when repository, event, run ID/attempt, current PR
head/base, run head, and tested commit all match the documented event mapping.
For a PR, the tested commit must have exactly the recorded base and source-head
as its two parents. Download only the non-expired artifact selected by the exact
`review-evidence-<tested-sha>-attempt-<attempt>` name and returned artifact ID.
Treat every `required_gate_set` outcome as the QA verdict. Any non-pass,
missing, stale, malformed, cancelled, skipped, or mismatched fact means QA is
not satisfied. Green-path intake reads run metadata and `summary.json` only;
download raw JUnit, Ruff, or mypy reports only for a failing/malformed gate.
Mypy remains report-only (`required: false`) and never blocks QA on its own.

This replaces re-execution of the mechanical checks only. It does not
change, skip, or shorten code review or security review — those still run
per the order below. The receipt schema and required/report-only split are the
public evidence contract; changing the reviewer-agent order requires a
separately approved governance decision.

## Review

Use the build-loop review order: plan audit, implementation, QA, code review,
security review when paths, permissions, public input, or external writes are
touched, then regression QA. If independent agents are unavailable, perform a
clearly disclosed fresh-eyes pass against the same charters.

## Contract migration

`scripts/contract_check.py` is the shared source for runtime pointers, contract
diagnostics, brownfield preflight, and evidence enums. Never add an independent
pointer inventory to shell, CI, documentation, or another validator.

All legacy migration is manual. A conflict report must name the diagnostic and
link to `docs/codex.md`; no scaffold path may transform existing policy.

## Reporting and handoff

Report concrete gate counts/results, intentional deferrals, and exact remaining
commands. A paused task uses the handoff skill and records runtime, workflow,
contract revision, Git state, decisions, and verified gates.
