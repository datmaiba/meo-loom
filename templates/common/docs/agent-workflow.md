# Agent workflow

This document is part of the canonical `AGENTS.md` contract. It defines shared
execution behavior; runtime configuration is an adapter, never a second policy
source.

## Runtime adapters

- Read the root `AGENTS.md` regardless of host. `CLAUDE.md`,
  `.claude/CLAUDE.md`, and `.cursorrules` only route to it.
- Host hooks, statuslines, model-routing files, and local companion tools may
  improve a runtime but must not carry unique workflow policy.
- Do not rely on a runtime configuration format until its schema is verified.
  In particular, no generated project depends on `.codex/hooks.json`.
- Optional tools stay opt-in adapters. A configured Headroom MCP server does not
  imply proxy routing; use `headroom wrap codex` only when the user explicitly
  opts into routing. Treat `specify init --here --force` as destructive in a
  brownfield project until an approved file-by-file plan exists.

## Build workflow

For every `build phase N` request, run the MeoLoom `build-loop` skill: load
context, self-question, plan, stop for approval, build, verify with the
declared gates, independently review, then harvest lessons. Autopilot mode is
defined by that skill and has its own PREFLIGHT approval gate.

## Rule verification

On `verify rules`, list the files loaded from this contract and recite the
architecture rules, quality gates, plan gate, and decisions rule from
`spec/08-decisions.md`. Do not edit files.

## Handoffs

Use the MeoLoom `handoff` skill for a paused substantive task. Its document
must record runtime, canonical-contract revision, Git state, decisions, and
verified gates so a cold reader can continue safely.

## When MeoLoom skills are unavailable

Execute the loop inline from this contract: load context → self-question against
the spec and decisions → plan and obtain approval → build dependency-first → run
all declared gates → perform a fresh QA/code review (plus security review for
paths, permissions, public input, or writes) → harvest lessons. For a pause,
manually create `handoffs/HANDOFF-<date>-<slug>.md` with Goal, Runtime, Workflow,
Canonical contract, Git state, State, Decisions, Files, Verified gates,
Third-party risks, Next steps, Traps, and Glossary.
