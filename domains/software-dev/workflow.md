# software-dev — workflow

This slot teaches the work-loop engine what building software from a spec
means. You are building a production project from a spec: think like the
senior engineer who wrote that spec. Engine mechanics (the phase sequence,
approval stops, retry bounds, hands-off mode, recovery protocol) live in
`engine/work-loop/ENGINE.md` and are not restated here — this file binds them
to software.

**Phase-name correspondence (engine deletion test):** this pack uses the
engine phase names directly, in engine order, with one rename: the engine's
EXECUTE phase is called **BUILD** here. "Phase" in this pack means one phase
of the project's build-phases spec — the pack's task unit.

## Entry assumptions

The project has an `AGENTS.md` canonical contract (architecture rules +
quality-gate commands through its linked docs) and a `spec/` directory (see
`ground-truth.md` for the layout and the partial-spec rule). Missing both?
Suggest running `/meo-loom:project-init` first.

## LOAD telemetry obligation

At LOAD, start the software-development task and carry its returned `task_id` and
`event_id` through the session:

```
python3 scripts/telemetry.py --repository-root <repo-root> start --workflow build-loop
```

`--repository-root` is a required global and comes before `start`. The registered
`software-dev` trigger is `build-loop`; do not substitute the Domain Pack id. Record the
ids in a handoff's `## Telemetry` section.

- **Fresh task:** emit and retain both ids.
- **Resuming:** reuse the `task_id` in the newest software-dev handoff; never emit a
  second `task_started` for the task.
- **Telemetry disabled:** when `DAT_KIT_TELEMETRY=off`, record `disabled:` and its reason
  in `## Telemetry`; do not work around it.

## PREFLIGHT — one-time whole-project questionnaire (before phase 0)

Goal: the user answers ALL decisions ONCE, up front — no mid-build
interruptions. This is the engine's single up-front approval questionnaire,
instantiated for spec-driven builds.

**Trigger**: the user asks for preflight, OR an autopilot run starts and
`spec/08-decisions.md` is missing or still marked `PREFLIGHT NOT RUN` (then
preflight runs automatically first).

**Incremental preflight**: if `spec/08-decisions.md` exists but its `covers
phases` range doesn't include the phases about to run, run preflight ONLY for
the uncovered phases — one batch of new questions, append answers, update the
range. Never re-ask what's already logged.

1. **Scan everything**: `AGENTS.md`, its linked `docs/agent-*.md`, ALL `spec/`
   files, `lessons-learned/`, and existing code state (`git log`, tree).
   Resolve `DAT_KIT_ROOT` from this pack and run
   `python "$DAT_KIT_ROOT/scripts/contract_check.py" --target .` to inventory
   every registered instruction entrypoint and runtime adapter. Stop PREFLIGHT
   on any named diagnostic (duplicate policy, missing/wrong-cased pointer,
   legacy contract, unsafe link, or dependency on a runtime adapter). Generate
   `python "$DAT_KIT_ROOT/scripts/contract_check.py" --target . --migration-plan`,
   present its read-only file-by-file output for approval, and stop. A
   generated plan is evidence of unresolved drift, not proof that migration
   happened.
2. **Run the question lenses (below) across EVERY phase** in the build-phases
   spec — not just the next one. Answer everything answerable from spec (with
   citations); keep only the genuinely unanswerable.
3. **Present ALL open questions in ONE batch**, grouped by phase. Each
   question gets: a numbered ID (`D-001`…), 2–3 concrete options, a
   recommended default, and one line on the consequence of each option. Wait
   for answers — this is the ONLY approval stop of the whole run.
4. **Write `spec/08-decisions.md`**: one row per decision — `ID | question |
   decision | rationale | source (user/auto) | date` — and set the status line
   to `PREFLIGHT DONE <date>, covers phases <range>`. This file is spec: later
   steps consult it before ever asking the user.

Preflight MUST also cover **taste choices** the spec leaves open — library
picks, UI patterns, tooling — since autopilot won't stop at plan gates, this
is the user's only chance to steer them.

## Escalation triggers and decision log (engine severity rubric)

This pack's **decision log** is `spec/08-decisions.md`; auto-decisions are
appended there with `source: auto`.

This pack's **escalation trigger list** — ask the user (stop) if ANY of:
secrets/credentials/auth policy · irreversible or destructive data operations
· deviation from spec · external services, cost, or sign-ups · public API
contract or URL structure · production/deploy impact. Everything else —
internal naming, file layout, dev-only tooling, anything reversible in
<15 minutes — is auto-decide territory: pick the safest spec-consistent
default.

## Question lenses (SELF-QUESTION)

Generate questions across ALL these lenses and answer them from the ground
truth (see `ground-truth.md`) with a citation (file + section):

| Lens | Example questions to generate |
|---|---|
| Data | Which tables/entities/invariants does this phase touch? What cascades? What's nullable? |
| Contracts | Which endpoints/interfaces? Request/response shapes? Pagination contract? Versioning? |
| UX states | For every screen/surface: loading, empty, error, success? What happens on double-submit? |
| Domain invariants | Project-specific rules that must always hold (i18n fallbacks, currency rounding, tenancy isolation…) |
| Security | Auth? Rate limits? Sanitization of user content? Mass-assignment? Injection surfaces? For every new public endpoint that WRITES data, ask two SEPARATE questions: does it have its own rate limit, AND does the data it accumulates need a retention policy? (A rate limiter caps request speed, not unbounded storage growth.) |
| Edge cases | Collisions? Time-based state whose moment passes? Deleting a parent with children? |
| Reuse | Before writing a new data access/helper, does an existing method with the same purpose already exist (grep by domain)? When reusing one written for another feature, read its actual contract — never trust the name (it may carry looser assumptions, e.g. no status filtering). |
| Traps | Which known silent-failure traps apply (from `lessons-learned/` and the stack profile's traps file)? |
| Scope | What is explicitly OUT of this phase? |

## PLAN — what a complete plan contains

Files to create/modify (grouped by area), endpoints with shapes, components
with paths, test list, risks, demo steps (template:
`deliverables/phase-plan.template.md`). Delegate the draft to
`plan-reviewer` (see `reviewers.md`) for an independent audit against the
spec; fix BLOCKERs before presenting the plan with the reviewer's verdict.

## BUILD (the engine's EXECUTE phase)

Follow the architecture rules linked by the project's `AGENTS.md` exactly.
Work dependencies-first (data layer → domain → interfaces → tests, or the
order the stack profile prescribes). This pack's **smallest self-contained
unit of work is the commit-sized chunk**, committed with a
conventional-commit message.

## VERIFY

**Delegate to `qa-agent`**: it runs ALL quality gates defined by the
project's canonical `AGENTS.md` contract per SW-G1 in `gates.md` (exact
commands, no substitutes) — AND attacks the feature with spec edge cases. Verdict `RETURN TO BUILDER` →
fix the failing list → send back; **repeat until `PHASE DONE`** (the engine's
retry bound applies). Then walk the phase's demo step from the build-phases
spec yourself. Gate definitions, worked cases, and the red-green proof
evidence contract live in `gates.md`.

## REVIEW

**Delegate to `code-reviewer`**: independent diff audit against the canonical
`AGENTS.md` contract and the stack profile. Verdict `RETURN TO BUILDER` → fix
findings → re-run **both** qa-agent (regression) and code-reviewer; repeat
until `APPROVE`. Reviewer team, sequence, security-reviewer trigger surfaces,
and review-cost rules live in `reviewers.md`. LESSON CANDIDATES from
reviewers feed the engine's HARVEST.

## Autopilot bindings (hands-off mode)

Engine hands-off mechanics apply unchanged; this pack binds them as follows:

- **Preflight first**: if `spec/08-decisions.md` doesn't exist, run PREFLIGHT
  (the single approval stop), then proceed through all phases.
- **Phase transition REQUIRES**: all gates green + the phase's demo verified
  (describe how; browser-only steps the user must do are listed and deferred,
  never skipped silently) + security-reviewer APPROVE when its trigger
  surfaces were touched (an open CRITICAL/HIGH finding blocks the transition).
- End of each phase: **commit**, then the engine's full HARVEST.

## DELEGATED-BUILD MODE (orchestrator + fresh builder per task)

Activated when the user asks for it ("delegated build", "delegate the
build"), or during **autopilot** when a phase's plan exceeds ~5 tasks or the
session is past roughly half its context — delegation is what keeps long runs
from hitting the ceiling.

Changes to the loop — LOAD through PLAN and HARVEST are unchanged; BUILD
through REVIEW become:

- **The main session is the orchestrator and writes NO code.** After plan
  approval it splits the phase into commit-sized tasks (≤ ~30 min each, exact
  file paths, dependency order) and dispatches a **fresh builder subagent per
  task**.
- **Each task gets a builder brief** in the handoff-skill format (Goal /
  State / Decisions in effect / Files / Gates / Next steps / Traps /
  Glossary). The brief is the builder's ONLY context — write it so a cold
  reader succeeds; a vague brief is the orchestrator's failure, not the
  builder's.
- **Model per dispatch** (see `docs/model-selection.md`): default to leaving
  `model` unset so the builder inherits the orchestrator's tier. Set
  `model: sonnet` for a task that's pure scaffolding/pattern-following from a
  clear brief, or `model: opus` for a task that needs real architectural
  judgment — never `haiku` for a builder (implementation, unlike scouting,
  isn't mechanical enough). The review agents already run `model: opus`,
  matching their judge/verify role.
- **Two-stage review per task, in this order**: (1) **spec compliance** — the
  orchestrator checks the diff against the brief: everything asked, nothing
  beyond scope; (2) **code quality** — `code-reviewer` on the diff.
  Compliance first: quality-polishing the wrong thing wastes a round. Either
  stage fails → return to a FRESH builder with the brief plus the findings
  (max 2 retries per task, then STOP and report).
- **Consult before the final retry** (`docs/model-selection.md` →
  Escalation): when a task's first retry also fails, dispatch ONE read-only
  consult raised per-invocation to `opus`, with the failure bundle (brief,
  diff, verbatim gate/review output, approaches tried). Verdict `PLAN` →
  final retry runs the normal builder tier with the plan added to the brief;
  `TAKE_OVER` → final retry runs at the consult's tier. The consult does not
  consume a retry. Severity-rubric STOPs still go to the user — no consult
  answers an authority question. Log one line per consult to
  `benchmarks/escalations.jsonl`.
- **Gates still run per task** (builder runs them, orchestrator spot-checks
  the claim) and **qa-agent still runs once at phase level** after all tasks
  land — per-task green does not prove the tasks compose.
- Builders inherit the escalation trigger list: a HIGH-severity question
  inside a task bubbles up to the orchestrator, which applies the engine's
  severity rubric (ask/stop or auto-decide + log).

## Recovery bindings (interrupted phase)

The engine's recovery protocol applies; its working-record checks are, for
this pack:

1. `git log --oneline -10` and `git status` — look for this phase's commits
   and uncommitted work.
2. Compare what exists on disk against the phase's scope in the build-phases
   spec.
3. Report a RESUME STATE: `fresh | partially built (list what exists) | built
   but unverified`. Half-done uncommitted work follows the engine's
   keep-or-fix recovery rule.
