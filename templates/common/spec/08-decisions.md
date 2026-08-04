# 08 — Decisions log

Single source of truth for every decision the spec leaves open. Written by PREFLIGHT (batch, `source: user`) and by mid-run auto-decisions (`source: auto`, low-severity only — see the build-loop rubric). **Consult this file before asking the user anything.** Appending here never requires approval; editing an existing row does (it's a decision change).

Status: `PREFLIGHT NOT RUN` — the next autopilot run must execute preflight first and replace this line with `PREFLIGHT DONE <date>, covers phases <range>`.

| ID | Question | Decision | Rationale | Source | Date |
|----|----------|----------|-----------|--------|------|

<!-- Example row:
| D-001 | Commit `.env` or only `.env.example`? | Only `.env.example`; real `.env` gitignored | Never commit secrets | user | 2026-01-01 |
-->
