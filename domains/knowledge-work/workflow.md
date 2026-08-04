# knowledge-work — workflow

This is a MeoLoom Domain Pack slot: it teaches the work-loop engine what
"knowledge work" — research, writing, analysis, synthesis, documentation —
means. Engine mechanics (the phase sequence, approval stops, retry bounds,
hands-off mode, recovery protocol) live in `engine/work-loop/ENGINE.md` and
are not restated here — this file binds them to research and writing.

**Phase-name correspondence (engine deletion test):** this pack presents the
loop as **A Clarify → B Decompose → C Ground truth → D Execute → E Verify →
F Report → G Harvest**. The binding correspondence, by mechanism:

| Engine phase | This pack |
|---|---|
| LOAD | A Clarify (brief intake) + C Ground truth (source intake) |
| SELF-QUESTION | A Clarify (assumptions and open questions) |
| PLAN | B Decompose |
| EXECUTE | D Execute |
| VERIFY | E Verify (gate runs) |
| REVIEW | E Verify (independent review) |
| REPORT | F Report |
| HARVEST | G Harvest |

**The engine's PLAN approval stop lands at B.** The outline is this pack's
plan artifact: in attended mode it is presented — verification step included —
and approved before drafting begins, and it is never bundled with the draft
in one approval. This pack declares **no plan reviewer** (that engine binding
is pack-optional); the independent review of this domain is the phase-E
fact-check. In hands-off mode the engine's single up-front approval stop
governs instead.

## Entry assumptions

A brief exists or is nailed in phase A. The governing spec/brief of the
engine's hard rules is the agreed brief; no repository, spec/ directory, or
toolchain is assumed. When the work lives inside a project with a canonical
contract, the engine's LOAD reads that contract first as always.

## Engine bindings (what this pack declares)

- **Question lenses:** brief (audience, purpose, scope, length,
  jurisdiction/standard, deadline) · sourcing (which primary source grounds
  each intended claim) · currency (which facts are time-sensitive) · coverage
  (which brief items risk stub treatment) · consistency (which numbers and
  claims must reconcile).
- **Decision log:** the deliverable's `> Brief:` block plus its stated
  assumptions (phase A writes them). An answer or assumption recorded there
  is used silently and never re-asked.
- **Escalation triggers (severity rubric):** any change to audience, purpose,
  scope, jurisdiction/standard, or deadline; publishing or sending the
  deliverable anywhere external; dropping or stubbing a brief item; a claim
  contradicting a source the user supplied. Auto-decide the rest — structure,
  wording, ordering, choice among equally reliable primary sources — and log
  them as stated assumptions.
- **Smallest self-contained unit of work:** one fully drafted outline section
  with its claims cited.
- **Deliverables, gates, reviewers, ceiling:** declared in `deliverables/`,
  `gates.md`, `reviewers.md`, `loop-profile.md`.

## Running the loop

**A — Clarify.** Nail the brief before researching: audience, purpose, scope,
length, required sources or jurisdiction, deadline. Underspecified research
wastes whole runs. State assumptions in one line and proceed.

**B — Decompose.** Any deliverable with 3+ distinct claims or sections gets a
visible outline that ends with an explicit **verification step** — the
fact-check that deadline pressure deletes first.

**C — Ground truth.** Read `ground-truth.md`. Never write from memory when a
source is checkable. Primary over summary, current over remembered, a fresh
search for anything time-sensitive.

**D — Execute.** Draft against the outline. Attach a source to every
non-trivial factual claim *as you write it*, not afterward — retrofitting
citations is how unsupported claims survive. Use the templates in
`deliverables/`.

**E — Verify against the gates.** Run every gate in `gates.md`. Then hand the
draft to an independent fact-check per `reviewers.md` — you do not grade your
own claims. Loop D→E until the gates pass.

**F — Report honestly.** State what was verified and how ("12 claims, all
cited; 3 currency-checked against 2026 sources; 1 claim could not be sourced —
flagged inline"). Never "fully researched." Surface every claim you could not
source rather than hiding it.

**G — Harvest.** A wrong citation caught, a source that looked authoritative
but wasn't — each becomes a lessons-learned entry so the next run doesn't
repeat it.
