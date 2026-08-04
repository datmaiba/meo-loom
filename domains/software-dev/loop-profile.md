# build-loop — loop profile (advisory)

> Advisory only. This documents which of MeoLoom's four loops each build-loop task fits, and why. It drives nothing at runtime; the operative surface is the work-loop engine composed with this pack (loaded by the generated `build-loop` trigger). See `docs/loops.md` for the model.
>
> Domain: **software-dev.** build-loop *is* this domain's working loop. Its gate is the independent-reviewer chain (`qa-agent` → PHASE DONE, `code-reviewer` → APPROVE, `security-reviewer` when relevant) — a measurable, validated, but **human-/reviewer-anchored** gate, which is why this domain tops out at **Goal**.

## Per-task loops

| Task | Loop | Trigger | Ends when |
|---|---|---|---|
| Build a phase from spec (`build phase N`) | **Goal** | user | `qa-agent` reports PHASE DONE **and** `code-reviewer` reports APPROVE (+ `security-reviewer` clean on security-relevant surfaces) |
| PREFLIGHT questionnaire | **Turn** | user | user has answered every open decision once; written to `spec/08-decisions.md` |
| Autopilot (multi-phase, hands-off) | **Goal** | user | all phases pass their inner review loop; stops early only for high-severity questions (secrets, destructive ops, spec deviation, cost, public contracts) |
| Delegated build (orchestrator + builder subagents) | **Goal** | user | each dispatched task clears two-stage review (spec compliance → code quality) |
| Resume an interrupted build | **Turn → Goal** | user | newest `handoffs/` file read; resumes the phase's Goal loop |
| Plan review before the approval gate | **Turn** (inside a Goal run) | the PLAN phase | `plan-reviewer` returns; user approves at the gate |

## Loop ceiling for software-dev

**Goal.** No build-loop task safely unlocks Time or Proactive yet:

- The gate is real and measurable (tests/lint/build green + reviewer verdicts), but "APPROVE" is a reviewer judgement, not a fully mechanical signal.
- A candidate *automatable* gate exists — running `scripts/validate.py` / the test suite on a schedule (a Time-based repo health check) — but that is repo maintenance, not feature building, and belongs to the deferred `runners/` work, not build-loop.

Building code is inherently user-initiated and judgement-gated. Keeping software-dev at Goal is the correct outcome of the capability ladder, not a limitation to fix.
