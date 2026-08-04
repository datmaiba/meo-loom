---
name: terse-mode
metadata:
  version: "1.0"
description: >-
  Native output-compression toggle — cut filler from replies while keeping every
  load-bearing detail, no external plugin required. Invoke when the user wants
  shorter answers ("talk terse", "terse mode", "be concise", "stop the preamble",
  "caveman mode", "trim the output"). Accepts an optional level: "lite" (drop
  filler only) or "full" (telegraphic fragments); default lite. Compresses PROSE
  ONLY — it never compresses evidence, gate results, error strings, repro commands,
  approval stops, or reviewer verdicts, because those are MeoLoom's whole point.
  Stays active until the user says "normal mode". Not for reviewer subagent output
  (qa/code/security agents stay full — their reports are an audit trail for humans).
---

# terse-mode — say less, keep the substance

A MeoLoom-native way to spend fewer output tokens without losing accuracy. Inspired
by the caveman skill, but built in so there is no extra plugin, no second
SessionStart hook, no statusline contention, and — critically — a hard carve-out
around the evidence MeoLoom exists to produce. Brain stays big. Mouth gets small.

> This shrinks what the agent **says**, never what it **checks**. Verification depth,
> gate runs, and reasoning are untouched. If anything, brevity sharpens them —
> constraining a reply to its substance forces the substance to be correct.

## 0. Pick a level

If the user passed one, use it. Otherwise default **lite**.

| Level | Style | Use when |
|---|---|---|
| **lite** | Normal sentences, filler removed. No "Sure!", no "I'd be happy to", no restating the question, no summary of what you just did. | Default. Safe everywhere. |
| **full** | Telegraphic fragments. Drop articles/pronouns where meaning survives. Lead with the answer; cut every word that can go without changing meaning. | User wants maximum brevity, or a long back-and-forth where context is already shared. |

Announce the switch in one short line the first time only ("Terse mode: lite"), then stop mentioning it.

## 1. What to cut (both levels)

- Openers and acknowledgements: "Great question", "Sure, let me help", "Absolutely".
- Restating the user's request back to them before answering.
- Post-hoc narration: "I've now done X and Y" when the diff/result already shows it.
- Hedging chains and apology padding. State the fact once.
- Repetition — say each point once, do not re-summarise at the end.

## 2. What to NEVER cut — the load-bearing carve-out

terse-mode compresses **prose**. It must pass the following through at full fidelity,
regardless of level. These are exactly the things MeoLoom treats as non-negotiable
("evidence over claims"):

- **Gate results** — `pest 24/24 ✓`, `tsc ✓`, `eslint 0`. Never abbreviate to "tests pass".
- **Error strings and repro commands** — quote the decisive line verbatim; keep the exact command that reproduces.
- **Approval stops** — the plan-only / one-approval gate. A terse plan is still a full plan; the STOP is never trimmed away.
- **Review verdicts** — a reviewer's pass/fail and its reasons.
- **Code, paths, URLs, commands, identifiers** — byte-for-byte. Never "caveman-ise" a code block.
- **Spec content** — never compress the spec; it is law and human-authored.

If terseness and evidence conflict, evidence wins. Drop the adjective, keep the number.

## 3. Where terse-mode does NOT apply

- **Reviewer subagents** (`qa-agent`, `code-reviewer`, `security-reviewer`, `plan-reviewer`).
  Their output is an audit trail read by a human; brevity there erodes the value.
  Run them full even while the main session is terse.
- **The spec and AGENTS.md contract** as written artifacts — see caveman-compress (optional companion)
  if you want to shrink *memory* files, and even then never the spec.
- **Handoff documents** — a handoff must survive a cold read by another session; keep it complete.

## 4. Interaction with caveman (the companion)

terse-mode and the external `caveman` plugin do the same job. Do **not** run both —
pick one. terse-mode is the zero-dependency default; caveman is the opt-in for its
extras (multi-level incl. `wenyan`, `/caveman-commit`, `/caveman-review`, cross-agent
support, lifetime-savings badge). If caveman is installed and active, defer to it and
say so once; the carve-outs in §2 still apply either way.

## 5. Turn it off

"normal mode" (or "verbose", "stop terse") → resume normal prose from the next reply.
