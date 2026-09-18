# Model selection for subagents

Choose a model by **the cost of being wrong**, not by how tedious the work looks. Reserve the strongest model for the step where a mistake is expensive; route mechanical steps to a cheap model. A single task legitimately mixes tiers — the orchestrator does not need to match the worker.

## Scope

Choose a model by the cost of being wrong, uncertainty, and the authority a
result could influence. These mappings are approved by Dat; they are policy
decisions, not benchmark results or price rankings. Keep the author, builder,
and independent reviewer separate as the normal case. If independent agents
are unavailable, the mandatory build-loop reviewer fallback is a clearly
disclosed fresh-eyes pass in both hosts; never silently self-review.

The Claude sections below apply **only to Claude Code**. `agents/*.md`
frontmatter, Claude aliases, and `CLAUDE_CODE_SUBAGENT_MODEL` do not configure
Codex. Claude behavior below is retained unchanged.

## What Claude Code can actually set

An agent's `model:` frontmatter field (see `agents/*.md`) accepts the tier aliases `haiku`, `sonnet`, `opus`, `fable`, a full model ID (e.g. `claude-opus-4-8`), or `inherit`; omitted, it defaults to `inherit`. Prefer aliases over model IDs — an alias always resolves to whatever Anthropic currently ships at that tier, an ID goes stale. Claude Code resolves a dispatch's model in this order: `CLAUDE_CODE_SUBAGENT_MODEL` env var → the per-invocation `model` parameter → the agent file's frontmatter → the main conversation's model. The per-invocation parameter beating frontmatter matters: an orchestrator can raise (or lower) one specific dispatch without touching the agent file.

| Tier alias | Use for |
|---|---|
| `haiku` | Scouting, file-finding, read-and-list, mechanical bulk edits (rename across files, reformat) — independent, low-risk, high-volume steps. |
| `sonnet` | Implementation inside a clearly bounded file set, following an established pattern — most `build-loop` phase work. |
| `opus` | Judge/verify roles: adversarial QA, code review, security audit, the final go/no-go on a phase. Also implementation that requires real architectural judgment, not just pattern-following. |
| `fable` | The top tier. Don't pin it in a reusable agent file — availability varies by plan and it's the most expensive; when one dispatch genuinely needs judgment beyond `opus`, raise that dispatch with the per-invocation `model` parameter instead. |
| `inherit` (default when unset) | Anything without a clear reason to diverge — the subagent runs at whatever tier the main session is on. Only override when a tier mismatch is a known, named risk. |

## Claude rule of thumb

- **Don't** set `haiku` for a step that needs real reasoning — cheap but wrong costs more than the tier upgrade would have.
- **Don't** set `opus` for a step Haiku already does correctly — no speed or quality gain, just cost.
- **Default to unset (`inherit`)** unless you're confident a different tier is clearly better for that specific role.
- The controller (the session running the loop, dispatching subagents) should be the highest-tier model in play; workers doing mechanical steps should be the cheapest one that doesn't sacrifice correctness.

## Where this applies in Claude Code

- **`agents/plan-reviewer.md`, `agents/qa-agent.md`, `agents/code-reviewer.md`, `agents/security-reviewer.md`, `agents/prior-art-auditor.md`, `agents/premise-challenger.md`** — all judge/verify/audit roles per the table above, so they set `model: opus`. The last two are plan-stage roles (see `domains/software-dev/reviewers.md`) and warrant the same tier: one has to search exhaustively enough to prove absence, the other has to find the framing error nobody else did. Known trade-off: frontmatter pins, it doesn't set a floor — a main session on a higher tier (e.g. Fable) runs these reviewers *below* itself. That's accepted for predictable cost and availability; for a review that genuinely warrants the session's tier, raise that one dispatch with the per-invocation `model` parameter.
- **`build-loop`'s delegated-build mode** — the orchestrator dispatches a fresh builder subagent per task. Apply the same table when choosing that dispatch's model: a task that's pure scaffolding from a clear brief can run `sonnet`; a task requiring real design judgment can run `opus`. The two-stage review (spec compliance, then `code-reviewer`) still runs regardless of which tier built the code — it is what catches a wrong tier choice.
- If the user is running the main session below the tier a step actually needs (e.g. auditing security on Sonnet), say so and suggest they raise it with `/model` — don't silently degrade the audit, and don't silently second-guess their choice either.

## Claude escalation — the consult dispatch

The table above covers difficulty you can see up front. For **surprise** difficulty — a cheap builder failing its gates, a diagnosis running out of hypotheses — escalate with a **consult dispatch**: ONE read-only subagent raised to `opus` (or `fable`) via the per-invocation `model` parameter, returning a plan for the cheap tier to execute. Rules that keep it honest:

- **Objective triggers only** — a failed review round, gates still red after a retry, an exhausted hypothesis list. Never "the builder feels stuck" (cheap models are confidently wrong far more often than they are self-aware), and never a severity-rubric STOP — those are authority questions only the user can answer, at any tier.
- **Feed it a failure bundle**, not a summary: the original brief, the diff so far, verbatim gate/review output, approaches already tried — plus the constraint that the plan must build on the partial work, never restart it.
- **Verdict is `PLAN` or `TAKE_OVER`.** `PLAN` → the final retry runs on the normal tier with the consult's plan added to the brief. `TAKE_OVER` (the failure is execution skill, not planning) → the final retry itself runs at the consult's tier. One consult per task; still failing after it → STOP per the loop's existing rules.
- **Log each consult** as one JSON line in `benchmarks/escalations.jsonl`: `{task, trigger, consult_model, verdict, outcome}`. Separate file on purpose — `scorecard.jsonl` is one-line-per-task and `scripts/scorecard.py` aggregates every line it sees. Caveat: `CLAUDE_CODE_SUBAGENT_MODEL` overrides the per-invocation parameter, so ask the consult to state which model it actually ran on and log that.
- **Escalation complements static routing, never replaces it** — a task known up front to need `opus` goes straight there; fail-then-consult on a known-hard task is the expensive path.

## Codex model policy

Codex dispatch uses the actual destination-host tool schema, not Claude
frontmatter or aliases. Recheck that schema before dispatch: support says what
the host accepts, not how a model performs or what it costs.

| Model | Eligibility | Status | Policy role | Limitation |
|---|---|---|---|---|
| `gpt-6-astra` | Approved-policy | Approved | Controller; ambiguous or architectural work; high-consequence planning; high-risk review. | The highest approved available model designation on 2026-09-18. It is not a runtime alias or config and cannot auto-switch the parent. |
| `gpt-5.6-sol` | Approved-policy | Approved | Bounded technical planning, complex coding, and routine review when adequate. | Do not use where Astra's floor applies. |
| `gpt-5.6-terra` | Approved-policy | Approved | Bounded implementation. | Current eligibility ends at bounded implementation; expanding its roles requires documented admission checks and Dat approval. |
| `gpt-5.6-luna` | Approved-policy | Approved | Low-risk retrieval and mechanical work. | Never the final plan or review. |
| `gpt-5.5` | Approved-policy, only with explicit selection or role evidence | Approved | Explicit selection or role-specific evidence only. | Never an automatic downgrade. |

Risk is high when architecture is unresolved, effects cross components, data or
security is involved, an external commitment is affected, or rollback is
difficult. Uncertainty raises the floor. `inherit` is acceptable only if the
actual inherited capability meets that floor. If a user pins a model below the
floor, or a required model is unavailable, disclose that and wait for direction;
never silently downgrade or bypass authority.

For example, a scoped documentation plan may use Sol; a cross-component
migration plan requires Astra.

The dated catalog evidence for this Codex host (2026-09-18) is
`collaboration.spawn_agent`: `gpt-6-astra`, `gpt-5.6-sol`, and
`gpt-5.6-terra` support `low`, `medium`, `high`, `xhigh`, `max`, and `ultra`;
`gpt-5.6-luna` supports `low`, `medium`, `high`, `xhigh`, and `max`; and
`gpt-5.5` supports `low`, `medium`, `high`, and `xhigh`. Recheck the current
schema per host before use.

Catalog lifecycle is `candidate`, `approved`, then `deprecated`.
"Approved-policy" means eligible under this policy, not benchmark-certified.
A future entry records its ID, host/date/support evidence, eligible roles,
limitations, and status. It needs current host-support validation,
representative role criteria and baseline checks, independent review, and Dat
approval before it becomes eligible or a default. Numeric names never
auto-promote. Keep evidence bounded and use existing infrastructure.

## Codex dispatch and consult discipline

Every harness assignment names its objective, allowed paths, inputs, output,
acceptance criteria, and stop conditions. Give agents only the bounded diff and
relevant sections. Run independent reviews sequentially: QA, review,
conditional security, then regression. Security is conditional on touched
paths, permissions, public input, or external writes.

Record requested model and effort. Record resolved identity only when tool
metadata provides it; otherwise record `unknown`. A Codex agent's self-report
is not resolved identity. The existing consult-log policy remains unchanged.

For an objective consult trigger—a failed review round, gates still red after a
retry, or exhausted hypotheses—make one read-only consult with the original
brief, bounded diff or relevant sections, verbatim gate/review output, and
prior attempts. Its verdict is `PLAN` or `TAKE_OVER`: `PLAN` gives one final
retry with its plan; `TAKE_OVER` gives that final retry to the consult tier.
After that retry fails, stop. Severity STOPs remain user-authority questions.

For Codex, select an adequate stronger approved model supported by the actual
host schema; do not translate this to an `opus` or `fable` alias. A consult
cannot cause an automatic downgrade or bypass authority. Model routing and
consults do not authorize external or destructive actions.
