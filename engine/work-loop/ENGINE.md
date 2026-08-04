# work-loop — the invariant working loop (engine revision `work-loop/1`)

This is the MeoLoom **engine**: the host-neutral, domain-neutral mechanics of
the working loop. The invariant loop is the same in every domain:

**LOAD → SELF-QUESTION → PLAN → EXECUTE → VERIFY → REVIEW → REPORT → HARVEST**

A Domain Pack fills in what each phase means for its profession. The engine
owns only these mechanics (domain-pack contract DP2): it contains no software
terms, no repository operations, no test commands, no host model routing, and
no profession's standards of truth. Where a phase below says "the pack
declares…", that declaration is a binding slot obligation on every composed
Domain Pack.

## The loop (run in full for every task)

### 1. LOAD

Read the project's **canonical contract** first. Runtime-specific files are
compatibility adapters and pointers only — never treat them as a second policy
source. Then read the pack's declared **ground-truth sources**, the contract's
linked working rules, the lessons-learned record (if present), and the project
glossary (if present — use its terms verbatim in all outputs), plus the prior
work this task builds on. Surface lessons-learned hits relevant to this task
explicitly. A partial ground truth is workable — say what is missing and
proceed with what exists.

Follow the composed Domain Pack's declared LOAD obligations, and preserve any session
state that obligation declares for later phases. The engine supplies this binding slot;
the Pack owns the domain value, command shape, and evidence it requires.

### 2. SELF-QUESTION (the core of the loop)

Generate the questions, answer them yourself, and **escalate only the
genuinely unanswerable ones to the user.** Generate questions across all the
lenses the pack declares, then answer each one **from the pack's ground-truth sources**,
naming where the answer lives (source + location). Only questions the ground
truth cannot answer go to the user.

Output format:

```
SELF-Q&A (answered from ground truth): [numbered — question → answer → source reference]
OPEN QUESTIONS (for you): [only what the ground truth AND the decision log cannot answer — with my recommended default]
```

Before listing an open question, check the pack's declared decision log — a
decision recorded there is used silently, **never re-asked**. Apply the
severity rubric (below) to what remains: low severity → auto-decide and log;
high severity → ask and STOP. When the user answers, record the answer in the
decision log so it is never asked again.

**Severity rubric for new questions mid-run.** Score every question before
anything stops. **Ask the user (stop)** when the pack's declared escalation
triggers match — the engine floor, binding in every domain: anything
irreversible or destructive, anything that changes authority or external
commitments, and any deviation from the governing spec/brief. **Auto-decide
(never stop)** otherwise: pick the safest default consistent with the ground
truth, record it in the decision log marked as auto-decided, and list every
auto-decision in the task report.

### 3. PLAN

Draft the plan for the task; the pack's workflow declares what a complete plan
contains. When the pack declares a plan reviewer, delegate the draft to it for
an independent audit against the ground truth and fix blockers before
presenting. Present the plan — including the reviewer's verdict, when one ran
— and **stop for explicit approval** (attended mode). Never bundle plan and
execution in one approval.

### 4. EXECUTE

Carry out the approved plan following the pack's workflow: its declared
working order and conventions, progressing in the smallest self-contained
units of work the pack defines.

### 5. VERIFY

Run the pack's gates **exactly as the governing contract declares them** —
never substitute alternative commands or weaker equivalents. **A green gate
proves nothing until you have seen it fail:** whenever a task adds or changes
a gate itself, deliberately introduce one failure, confirm the gate reports
it, revert — only then trust its green. On failure: fix and re-verify, up to 3
rounds; still failing → stop and report. Never continue on red.

### 6. REVIEW

**Never grade your own work when an independent grader exists.** Delegate the
finished work to the pack's independent reviewers, per their charters, in the
pack's declared sequence. A return-to-builder verdict → fix the findings →
re-run the pack's regression verification and the reviewer; repeat until
approve. Re-review rounds are **findings-scoped**, never fresh full reviews. A
pack-declared conditional reviewer whose trigger conditions the task does not
meet may be skipped — the skip and its reason go in the report, never silently.

### 7. REPORT

Account honestly for the task: state concretely what was verified and how,
per gate — never "everything works". List every auto-decision logged this
task. State every skipped conditional reviewer or gate with its reason.
Surface anything that could not be verified rather than hiding it.

### 8. HARVEST

Run in this exact order — the mechanical step comes FIRST so no approval pause
can cut it off:

1. **Scorecard**: run the **scorecard** skill for this task and capture the
   appended line. This requires no approval and must never be placed after a
   step that can pause.
2. **Lessons**: propose lessons-learned entries for anything the user
   corrected or you caught yourself. Attended mode: write them only after the
   user approves. Hands-off mode: appending is auto-approved (append-only,
   trivially reversible — low severity per the rubric); list the appended
   entries in the wrap-up instead of stopping. When a new lesson strengthens
   or supersedes an earlier entry, add a one-line forward reference to that
   earlier entry — a reader landing on the old entry must not trust a stale
   rule.
3. **Glossary**: if a project glossary exists, propose one-line entries for
   any concept this task forced you to describe in a sentence more than once
   (attended: after approval; hands-off: auto-append like lessons and list in
   the wrap-up). No candidates → skip silently.
4. If the `lesson-miner` tool is installed, remind the user to run its scan
   after the session; if not, skip silently.
5. **Print the 5-part wrap-up** — all modes; the task is not reported until
   all five parts are present: (1) done/fixed, numbered · (2) left
   intentionally, with reason · (3) remaining for the user — exact steps, in
   dependency order · (4) the REPORT accounting: concrete verification results
   per gate (e.g. "gate X: 24/24 ✓") plus auto-decisions logged this task ·
   (5) the scorecard line from item 1. End by stating what the next task needs
   from this one.

## Hands-off mode ("autopilot")

Activated ONLY when the user's request contains the word **"autopilot"**.
Changes to the loop:

- **One up-front approval stop.** The run opens with a single questionnaire:
  every open decision across the whole run is generated, batched, and
  presented once; the answers are recorded in the pack's decision log. This is
  the only approval stop of the run.
- Phase 3 relaxes: present the plan, then **proceed without waiting** — UNLESS
  a high-severity open question is not covered by the decision log, or the
  plan deviates from the governing spec/brief (still stop).
- A task transition REQUIRES the pack's gates green and the pack's declared
  done-evidence verified; steps only the user can perform are listed and
  deferred, never skipped silently. An open critical finding from a
  pack-declared reviewer blocks the transition.
- Any check failure: fix, up to 3 attempts, then STOP and report — never
  continue on red.
- **Long-running work**: verify any wakeup/scheduling call actually SUCCEEDED
  before yielding the turn; if it errored, retry or fall back to a foreground
  wait. A yielded turn with no wakeup set kills the run silently.
- Every task still ends with the full HARVEST, including the 5-part wrap-up.
- Context hygiene: if the session grows long, finish the current task, print
  the wrap-up, and tell the user to resume in a fresh session — don't degrade
  quality to avoid a restart. If the ceiling arrives MID-task: finish the
  smallest self-contained unit of work the pack defines, run the **handoff**
  skill, and tell the user to resume from the handoff file.

## Interrupted-session recovery (on every task start)

Before SELF-QUESTION, determine whether this task was already started:

1. If a handoffs record exists, read the **newest** handoff first — it is the
   previous session's compacted state. Verify its claims against the working
   record rather than trusting blindly.
2. Compare what exists in the working record against the task's declared
   scope, and report a resume state: fresh · partially done (list what
   exists) · done but unverified.
3. NEVER redo what already exists and passes the pack's gates — continue from
   the first missing or failing item. Half-done work: review it against the
   plan, keep what conforms, fix what doesn't.
4. If prior context exists in the transcript, skip re-reading material already
   summarized there.

## Hard rules

- The governing spec/brief is law; disagreement = propose an amendment, never
  silently deviate.
- The user approves plans and changes to the governing spec/brief (attended
  mode) — nothing else needs their time.
- A task is not done until the pack's gates pass and the pack's declared
  done-evidence exists — no exceptions, in any mode.

## Composition and contradiction rules

Composition follows domain-pack contract DP4:

```
canonical project contract → engine revision → descriptor + six slots
  → optional project profile → Host Adapter projection
```

- A pack composes with exactly the engine revision its descriptor declares
  (`required_engine_revision`). A mismatch **stops composition**
  (`DOMAIN_ENGINE_REVISION_MISMATCH`). This file is `work-loop/1`, declared in
  `engine.json` beside it.
- Later layers may narrow execution but may not contradict earlier policy; a
  contradiction stops composition.
- **Precedence (hands-off approval):** in hands-off mode the engine's
  single-up-front-approval rule overrides any per-step plan-approval gate
  declared by the project contract; in attended mode the project's gate
  applies unchanged.
- **What every pack must declare** for the engine to bind to: its question
  lenses; its ground-truth sources; its decision-log location; its reviewer
  team, sequence, charters, and any conditional reviewers' trigger conditions;
  its gates with their exact criteria; its escalation trigger list for the
  severity rubric; its smallest self-contained unit of work; its deliverable
  templates; its loop ceiling.

### Phase-name correspondence (declared for the deletion test)

Domain Packs may present the loop under domain phase names. The
knowledge-work pack's A→G names are this same sequence; the binding
correspondence is by mechanism:

| Engine phase | knowledge-work A→G |
|---|---|
| LOAD | A Clarify (brief intake) + C Ground truth (source intake) |
| SELF-QUESTION | A Clarify (assumptions and open questions) |
| PLAN | B Decompose |
| EXECUTE | D Execute |
| VERIFY | E Verify (gate runs) |
| REVIEW | E Verify (independent review) |
| REPORT | F Report |
| HARVEST | G Harvest |

A pack that renames or reorders its presentation must declare its
correspondence to these engine phases in its workflow slot, so conformance
checks can key on the engine sequence rather than domain vocabulary.
