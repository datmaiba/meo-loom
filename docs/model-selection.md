# Model selection for subagents

Choose a model by **the cost of being wrong**, not by how tedious the work looks. Reserve the strongest model for the step where a mistake is expensive; route mechanical steps to a cheap model. A single task legitimately mixes tiers — the orchestrator does not need to match the worker.

## Host compatibility

The routing policy is shared, but `agents/*.md` frontmatter and the model aliases below are Claude Code configuration. In Codex, use the same role charters with fresh subagents and let the active Codex model/configuration choose the tier; MeoLoom does not claim an unverified Codex model-routing schema. The build-loop's reviewer fallback remains mandatory in both hosts.

## What MeoLoom can actually set

An agent's `model:` frontmatter field (see `agents/*.md`) accepts the tier aliases `haiku`, `sonnet`, `opus`, `fable`, a full model ID (e.g. `claude-opus-4-8`), or `inherit`; omitted, it defaults to `inherit`. Prefer aliases over model IDs — an alias always resolves to whatever Anthropic currently ships at that tier, an ID goes stale. Claude Code resolves a dispatch's model in this order: `CLAUDE_CODE_SUBAGENT_MODEL` env var → the per-invocation `model` parameter → the agent file's frontmatter → the main conversation's model. The per-invocation parameter beating frontmatter matters: an orchestrator can raise (or lower) one specific dispatch without touching the agent file.

| Tier alias | Use for |
|---|---|
| `haiku` | Scouting, file-finding, read-and-list, mechanical bulk edits (rename across files, reformat) — independent, low-risk, high-volume steps. |
| `sonnet` | Implementation inside a clearly bounded file set, following an established pattern — most `build-loop` phase work. |
| `opus` | Judge/verify roles: adversarial QA, code review, security audit, the final go/no-go on a phase. Also implementation that requires real architectural judgment, not just pattern-following. |
| `fable` | The top tier. Don't pin it in a reusable agent file — availability varies by plan and it's the most expensive; when one dispatch genuinely needs judgment beyond `opus`, raise that dispatch with the per-invocation `model` parameter instead. |
| `inherit` (default when unset) | Anything without a clear reason to diverge — the subagent runs at whatever tier the main session is on. Only override when a tier mismatch is a known, named risk. |

## Rule of thumb

- **Don't** set `haiku` for a step that needs real reasoning — cheap but wrong costs more than the tier upgrade would have.
- **Don't** set `opus` for a step Haiku already does correctly — no speed or quality gain, just cost.
- **Default to unset (`inherit`)** unless you're confident a different tier is clearly better for that specific role.
- The controller (the session running the loop, dispatching subagents) should be the highest-tier model in play; workers doing mechanical steps should be the cheapest one that doesn't sacrifice correctness.

## Where this applies in MeoLoom

- **`agents/plan-reviewer.md`, `agents/qa-agent.md`, `agents/code-reviewer.md`, `agents/security-reviewer.md`, `agents/prior-art-auditor.md`, `agents/premise-challenger.md`** — all judge/verify/audit roles per the table above, so they set `model: opus`. The last two are plan-stage roles (see `domains/software-dev/reviewers.md`) and warrant the same tier: one has to search exhaustively enough to prove absence, the other has to find the framing error nobody else did. Known trade-off: frontmatter pins, it doesn't set a floor — a main session on a higher tier (e.g. Fable) runs these reviewers *below* itself. That's accepted for predictable cost and availability; for a review that genuinely warrants the session's tier, raise that one dispatch with the per-invocation `model` parameter.
- **`build-loop`'s delegated-build mode** — the orchestrator dispatches a fresh builder subagent per task. Apply the same table when choosing that dispatch's model: a task that's pure scaffolding from a clear brief can run `sonnet`; a task requiring real design judgment can run `opus`. The two-stage review (spec compliance, then `code-reviewer`) still runs regardless of which tier built the code — it is what catches a wrong tier choice.
- If the user is running the main session below the tier a step actually needs (e.g. auditing security on Sonnet), say so and suggest they raise it with `/model` — don't silently degrade the audit, and don't silently second-guess their choice either.

## Escalation — the consult dispatch

The table above covers difficulty you can see up front. For **surprise** difficulty — a cheap builder failing its gates, a diagnosis running out of hypotheses — escalate with a **consult dispatch**: ONE read-only subagent raised to `opus` (or `fable`) via the per-invocation `model` parameter, returning a plan for the cheap tier to execute. Rules that keep it honest:

- **Objective triggers only** — a failed review round, gates still red after a retry, an exhausted hypothesis list. Never "the builder feels stuck" (cheap models are confidently wrong far more often than they are self-aware), and never a severity-rubric STOP — those are authority questions only the user can answer, at any tier.
- **Feed it a failure bundle**, not a summary: the original brief, the diff so far, verbatim gate/review output, approaches already tried — plus the constraint that the plan must build on the partial work, never restart it.
- **Verdict is `PLAN` or `TAKE_OVER`.** `PLAN` → the final retry runs on the normal tier with the consult's plan added to the brief. `TAKE_OVER` (the failure is execution skill, not planning) → the final retry itself runs at the consult's tier. One consult per task; still failing after it → STOP per the loop's existing rules.
- **Log each consult** as one JSON line in `benchmarks/escalations.jsonl`: `{task, trigger, consult_model, verdict, outcome}`. Separate file on purpose — `scorecard.jsonl` is one-line-per-task and `scripts/scorecard.py` aggregates every line it sees. Caveat: `CLAUDE_CODE_SUBAGENT_MODEL` overrides the per-invocation parameter, so ask the consult to state which model it actually ran on and log that.
- **Escalation complements static routing, never replaces it** — a task known up front to need `opus` goes straight there; fail-then-consult on a known-hard task is the expensive path.
