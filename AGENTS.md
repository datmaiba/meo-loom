# Agent contract — MeoLoom maintainers

**Canonical contract revision:** MeoLoom 3.0

This is the single canonical instruction entrypoint for maintaining MeoLoom.
Runtime-specific files and hooks are compatibility adapters only and must not
duplicate or override this contract.

Before substantive work, read:

1. `docs/agent-workflow.md` — execution, review, migration, and handoff workflow.
2. `docs/agent-working-rules.md` — repository architecture, quality gates, and traps.
3. The approved plan or issue defining the change.
4. `lessons-learned/lessons-learned.md` — failures that must not recur.

Generated-project policy lives under `templates/common/`; maintainer policy lives
in the root documents above. Never use one as a substitute for the other.
