# Agent contract — {{PROJECT_NAME}}

**Canonical contract revision:** MeoLoom 3.0

This is the single canonical instruction entrypoint for every agent runtime in
this repository. Compatibility files such as `CLAUDE.md`,
`.claude/CLAUDE.md`, and `.cursorrules` are pointers only; they must never
duplicate or override this contract.

Before substantive work, read in this order:

1. `docs/agent-workflow.md` — execution, planning, handoff, and runtime-adapter rules.
2. `docs/agent-working-rules.md` — project scope, architecture, quality gates, and traps.
3. `spec/` — product decisions and phase scope.
4. `lessons-learned/lessons-learned.md` — mistakes that must not recur.
5. `CONTEXT.md` when it exists — use its domain terms verbatim.

For a build phase, use the MeoLoom `build-loop` skill and its independent-review
flow. Run every declared quality gate before claiming work is complete.
