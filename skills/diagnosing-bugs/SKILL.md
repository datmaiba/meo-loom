---
name: diagnosing-bugs
description: A disciplined diagnosis loop for hard bugs and performance regressions — the counterpart to build-loop's forward motion. Invoke when the user says "diagnose", "debug this", "why is this broken/slow", "find the root cause", or reports something throwing, failing, flaky, or regressed. Enforces feedback-loop-first debugging - build a tight red/green signal BEFORE theorising, reproduce and minimise, generate ranked falsifiable hypotheses, instrument one variable at a time, fix behind a regression test, then post-mortem into lessons-learned. Use standalone or when a build-loop phase surfaces a defect its checks can't localise. Not for trivial one-line typos with an obvious cause.
---

# diagnosing-bugs — find the root cause, not a plausible story

build-loop moves forward from a spec. This skill moves *backward* from a symptom
to its cause, with the same discipline: **evidence over claims**. The failure
mode this skill exists to prevent is reading code to build a theory before you
can even reproduce the bug. Don't.

If the repo has a `CONTEXT.md`, read the terms for the modules involved before
exploring — it is faster to reason in the project's own language.

## Phase 1 — Build a feedback loop (this is the whole skill)

Everything else is mechanical. With a **tight** pass/fail signal that goes red on
*this* bug, you will find the cause. Without one, no amount of staring saves you.
Spend disproportionate effort here. Be aggressive, be creative, refuse to give up.

Ways to build one, roughly easiest-first:

1. **Failing test** at whatever seam reaches the bug (unit → integration → e2e).
2. **curl / HTTP script** against a running dev server.
3. **CLI invocation** on a fixture, diffing stdout against known-good.
4. **Headless browser** (Playwright/Puppeteer) asserting on DOM/console/network.
5. **Replay a captured trace** — save a real payload/event log, replay it in isolation.
6. **Throwaway harness** — minimal subset of the system, one function call.
7. **Property/fuzz loop** for "sometimes wrong output" — 1000 random inputs.
8. **Bisection harness** — automate "boot at state X, check, repeat" for `git bisect run`.
9. **Differential loop** — same input through old vs new (or two configs), diff.

Then **tighten** it: faster (cache setup, narrow scope), sharper (assert the exact
symptom, not "didn't crash"), more deterministic (pin time, seed RNG, freeze
network). A 2-second deterministic loop is a superpower; a 30-second flaky one is
barely better than nothing.

**Non-deterministic bugs:** the goal isn't a clean repro, it's a *higher
reproduction rate*. Loop the trigger 100×, parallelise, add stress, inject sleeps.
50% flake is debuggable; 1% is not — raise the rate until it is.

**Completion gate — do not enter Phase 2 without this.** Name **one command** you
have **already run** (paste the invocation and its output) that is: red-capable
(drives the real code path, asserts the user's *exact* symptom), deterministic,
fast, and runnable unattended. No red-capable command → no hypotheses.

**Genuinely can't build a loop?** Stop and say so. List what you tried, then ask
the user for: access to the environment that reproduces it, a captured artifact
(HAR, log dump, core dump, timestamped recording), or permission to add temporary
instrumentation. Do not proceed to guess.

## Phase 2 — Reproduce + minimise

Run the loop, watch it go red. Confirm it's the failure the **user** described —
not a lookalike nearby (wrong bug = wrong fix) — and that it's repeatable.

Then shrink to the **smallest scenario that still goes red**: cut inputs, callers,
config, data, and steps **one at a time**, re-running after each cut. Done when
every remaining element is load-bearing — removing any one makes it go green. A
minimal repro shrinks the hypothesis space and becomes your regression test.

## Phase 3 — Hypothesise

Generate **3–5 ranked hypotheses before testing any**. One hypothesis anchors you
on the first plausible idea. Each must be **falsifiable** — state its prediction:

> "If X is the cause, then changing Y makes the bug vanish / changing Z makes it worse."

Can't state the prediction? It's a vibe — sharpen or discard. Show the ranked list
to the user before testing: they often re-rank instantly ("we just deployed #3").
Cheap checkpoint; don't block on it if they're away.

**Hypotheses exhausted?** Every ranked hypothesis falsified and the evidence
suggests no new ones: before giving up, dispatch ONE read-only consult at a higher
tier (per-invocation `model: opus` — see `docs/model-selection.md` → Escalation),
feeding it the repro command + output, the minimised case, and every probe result
so far. It must return new **falsifiable hypotheses with predictions** — a theory
it can't state a prediction for is discarded like any other vibe; this skill's
Phase 1 rule binds the consult too. Test them with your loop as usual, and log the
consult to `benchmarks/escalations.jsonl`.

## Phase 4 — Instrument

Each probe maps to a specific prediction. **Change one variable at a time.**

1. Debugger / REPL inspection if the env allows — one breakpoint beats ten logs.
2. Targeted logs at the boundaries that distinguish hypotheses.
3. Never "log everything and grep".

**Tag every debug log** with a unique prefix (e.g. `[DBG-a4f2]`) so cleanup is one
grep. For **performance** regressions, logs are usually the wrong tool: establish a
baseline measurement (timing harness, profiler, query plan), then bisect. Measure
first, fix second.

## Phase 5 — Fix behind a regression test

Write the regression test **before the fix** — but only if there is a **correct
seam** for it: one where the test exercises the real bug pattern as it occurs at
the call site. A too-shallow seam (unit test that can't replicate the triggering
chain) gives false confidence. **If no correct seam exists, that is itself the
finding** — note it; the architecture is preventing the bug from being locked down.

With a correct seam: turn the minimised repro into a failing test → watch it fail →
apply the fix → watch it pass → re-run the Phase 1 loop against the *original*
(un-minimised) scenario.

## Phase 6 — Cleanup + post-mortem

Before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop).
- [ ] Regression test passes (or the absence of a seam is documented).
- [ ] All tagged instrumentation removed (`grep` the prefix).
- [ ] Throwaway harnesses deleted or moved to a clearly-marked debug location.
- [ ] The winning hypothesis is stated in the commit / PR message.

Then ask: **what would have prevented this bug?** Append the answer as a
lessons-learned entry (the same file build-loop harvests into) so a future session
reads it first. If the answer is architectural — no good test seam, tangled
callers, hidden coupling — hand the specifics to the `improve-codebase-architecture`
skill. Make that recommendation *after* the fix lands: you know more now than when
you started.
