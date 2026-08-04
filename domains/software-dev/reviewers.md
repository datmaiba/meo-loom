# software-dev — reviewers

You are the **builder**. Independent reviewers keep you honest. MeoLoom ships
six reviewer subagents; their operative charters live at the MeoLoom root in
`agents/*.md` (projected to hosts by the adapters). **This file is the binding
surface**: it declares the team, the sequence, and the review-cost rules the
orchestrating session must enforce. If a named subagent is unavailable in
this environment, substitute a fresh subagent with the same charter, or as a
last resort a separate fresh-eyes pass — and say which substitution you made.

## The team

| Agent | Role | When |
|---|---|---|
| `plan-reviewer` | audits plans against spec (read-only) | PLAN, before the approval gate |
| `qa-agent` | runs gates + attacks with edge cases | VERIFY, loops until PHASE DONE |
| `code-reviewer` | audits the diff against the rules | REVIEW, loops until APPROVE |
| `security-reviewer` | attacker's-eye audit of the diff (read-only) | conditional — see trigger surfaces below |
| `prior-art-auditor` | for every item the plan says to build, proves it does not already exist (read-only) | PLAN, before drafting — see below |
| `premise-challenger` | argues the strongest case that the goal or framing is wrong (read-only) | PLAN, before drafting — see below |

Inner loop per phase: **build → qa-agent → fix → qa-agent → code-reviewer →
fix → (regression qa) → done**. Applies in BOTH normal and autopilot modes.

## The two plan-stage roles (added 2026-07-25)

`plan-reviewer`'s mandate is **fidelity** — plan versus spec. Two things sit
outside it by construction: whether the item already exists, and whether the
goal is well-formed. Adding more passes of the same mandate deepens a frame
instead of testing it. Both roles are read-only and neither replaces
`plan-reviewer`.

- **Trigger:** run both **before drafting**, and always before a third plan
  revision. Adversarial capacity pays off early; late passes find only
  mechanical defects.
- **R5 — parallel and blind (the one exception to R1):** these two run
  concurrently and neither sees the other's output, nor prior findings.
  Sequential review with findings passed in produces convergence, not
  independence — which is exactly the failure that made them necessary.
  Ratified in `docs/decisions/0005-plan-stage-adversarial-roles.md`, which also
  records the measurement that justified it.
- Their findings are folded or explicitly declined with a reason, same
  discipline as `plan-reviewer`.
- Charters live with the rest of the team at `agents/prior-art-auditor.md` and
  `agents/premise-challenger.md`.

These two are read-only and close no gate, so no Class C closer seat moves.
Appointment of reviewers that *do* close gates remains governed by
`docs/decisions/0002-authority-appointments.md` — this table declares the team
and the sequence, and does not create a second appointment register.

## security-reviewer trigger surfaces (conditional reviewer)

Trigger when the phase's diff touches ANY of: auth/session logic ·
user-supplied content (forms, markdown, comments) · file uploads or path
handling · new public endpoints · permission changes · payment/money.
security-reviewer runs after code-reviewer approves; verdict
`RETURN TO BUILDER` (any CRITICAL/HIGH finding) → fix → re-run qa-agent
(regression) + security-reviewer. Phases touching none of those surfaces skip
it — per the engine, the skip and its reason go in the report, never
silently.

## Review-cost rules (hard public contract)

- **R1 — sequential only:** qa-agent → code-reviewer → security-reviewer is a
  strict sequence; never parallel.
- **R2 — diff-scoped + pasted gates:** Reviewer reads the phase diff, touched
  files, directly referenced contract/spec sections only; dispatch prompt
  names the changed-file list and pastes gate outputs.
- **R3 — findings-scoped re-reviews:** Round 2+ verifies previous findings
  against the new diff only.
- **R4 — charter: static-only + capped reports:** code/security reviewers:
  static analysis, no PoC — runtime belongs to qa-agent alone. Findings
  ≤ ~30 lines.

## Independence and conflicts

A proposer cannot close its own proposal — the builder-vs-grader rule itself
is engine REVIEW policy; this pack binds it to the team above. Reviewer
verdict schemas (`PHASE DONE`, `APPROVE`, `RETURN TO BUILDER`) and retry
behavior are declared in each charter; the escalation path for repeated
failure is the engine's retry bound, then STOP and report.
