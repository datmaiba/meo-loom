---
name: improve-codebase-architecture
description: Surface architectural friction in a codebase and propose deepening refactors — turning shallow modules into deep ones for testability and AI-navigability. Invoke when the user wants to improve architecture, find refactoring opportunities, consolidate tightly-coupled modules, reduce a "ball of mud", or make code easier to test and for an agent to navigate. Also the handoff target when diagnosing-bugs finds a bug that can't be locked down because no clean test seam exists. Explores with a subagent, presents ranked candidates using a fixed depth/seam vocabulary, then grills the chosen one into a concrete design — recording new terms in CONTEXT.md and rejected directions in spec/08-decisions.md. Not for greenfield design (use project-init) or feature work (use build-loop).
---

# improve-codebase-architecture — make shallow modules deep

Find **deepening opportunities**: refactors that put a lot of behaviour behind a
small interface. Deep modules give callers **leverage** and maintainers
**locality** — change, bugs, and knowledge concentrated in one place. The payoff
is a codebase that is easier to test and easier for an agent to navigate.

## Vocabulary — use these words exactly, don't drift

Consistency is the point. Do not slide into "component", "service", "boundary".

- **Module** — anything with an interface and an implementation (function, class, package, slice).
- **Interface** — everything a caller must know to use it: types, invariants, error modes, ordering, config. Not just the signature.
- **Implementation** — the code inside.
- **Depth** — leverage at the interface. **Deep** = lots of behaviour, small interface. **Shallow** = interface nearly as complex as the implementation.
- **Seam** — where an interface lives; a place behaviour can change without editing in place. (Use this, not "boundary".)
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** — what callers gain from depth. **Locality** — what maintainers gain.

Two rules of thumb:

- **Deletion test** — imagine deleting the module. If complexity vanishes, it was
  a pass-through. If complexity reappears smeared across N callers, it earned its keep.
- **One adapter = hypothetical seam. Two adapters = real seam.** Don't build a seam
  for a second implementation that will never exist.

The **interface is the test surface** — deepening a module and testing through its
interface are the same move.

## Process

### 1. Explore

Read `CONTEXT.md` (domain terms) and the relevant rows of `spec/08-decisions.md`
first — decisions recorded there are settled; don't re-litigate them.

Then dispatch a subagent (Agent tool, `subagent_type=Explore`) to walk the code.
Don't follow rigid heuristics — explore organically and note where *you* feel
friction:

- Understanding one concept requires bouncing between many small modules.
- Modules are **shallow** — interface almost as complex as the implementation.
- Pure functions were extracted only for testability, but the real bugs hide in
  how they're wired together (no **locality**).
- Tightly-coupled modules leak across their seams.
- Parts that are untested, or hard to test through their current interface.

Apply the deletion test to anything you suspect is shallow.

### 2. Present ranked candidates

A numbered list. For each:

- **Files** — which modules are involved.
- **Problem** — why today's shape causes friction.
- **Solution** — plain English; what would change.
- **Payoff** — in terms of **locality**, **leverage**, and how tests would improve.

Use `CONTEXT.md` vocabulary for the domain and the vocabulary above for the
architecture: "the Order intake module", not "the FooBarHandler". If a candidate
contradicts a decision in `spec/08-decisions.md`, surface it only when the friction
is real enough to reopen that decision, and mark it clearly
(*"reopens decision D-07 because…"*). Don't list every refactor a decision forbids.

Do **not** propose interfaces yet. Ask: "Which of these do you want to explore?"

### 3. Grill the chosen candidate

Drop into a grilling conversation. Walk the design tree with the user —
constraints, dependencies, the shape of the deepened module, what sits behind the
seam, which tests survive. Side effects happen inline as decisions crystallise:

- Naming a deepened module after a concept **not in `CONTEXT.md`**? Add the term
  there now (create the file lazily if missing).
- Sharpening a fuzzy existing term? Update `CONTEXT.md` on the spot.
- User rejects a candidate for a **load-bearing** reason a future explorer would
  need? Offer to record it in `spec/08-decisions.md` so architecture reviews stop
  re-suggesting it. Skip ephemeral ("not worth it now") and self-evident reasons.

### 4. Hand off to build

The output of this skill is a *design*, not a diff. Once a candidate is grilled
into a concrete plan, hand it to **build-loop** to implement behind its plan gate
and reviewer agents — the builder never grades its own refactor. For a large
multi-module deepening, write a **handoff** first so the refactor survives a fresh
session.

Run this on a codebase periodically, not just when it hurts — architecture debt
compounds quietly.
