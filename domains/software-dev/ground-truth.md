# software-dev — ground truth

What counts as authoritative when building software from a spec, in priority
order. The engine's LOAD phase reads these; SELF-QUESTION answers from them
with a citation (file + section).

## Source priority

1. **The project's canonical `AGENTS.md` contract** and its linked
   `docs/agent-*.md` (architecture rules, quality-gate commands). Runtime
   files (`CLAUDE.md`, `.cursorrules`, hooks) are compatibility pointers,
   never a second policy source.
2. **The `spec/` directory** — vision, features, architecture, build phases,
   decisions. The numbering convention from MeoLoom's `project-init`:
   `00-vision` … `08-decisions`. `spec/08-decisions.md` is this pack's
   decision log and is spec: a decision recorded there outranks re-asking.
3. **`lessons-learned/lessons-learned.md`** — paid-for failures; surface hits
   relevant to the phase explicitly.
4. **`CONTEXT.md`** (if present) — the project glossary; use its terms
   verbatim in code, commits, and reports.
5. **The previous phase's code** — evidence of convention, not of policy.

## Conflict and currency rules

- The spec outranks existing code: code showing a different pattern than the
  spec is a candidate amendment or a bug, never a silent precedent.
- An existing helper's *name* is not its contract — read the implementation
  before reusing it (it may carry looser assumptions than the name implies).
- Memory of the codebase is stale the moment the tree changes: re-check with
  `git log`/`grep` rather than recalling.
- A partial spec is workable — state what's missing and proceed with what
  exists; never invent the missing sections silently.

## LOAD read-list (per phase)

`AGENTS.md`, its linked `docs/agent-*.md`, the relevant `spec/` files for
this phase, `lessons-learned/lessons-learned.md` (if present), `CONTEXT.md`
(if present), and the previous phase's code.
