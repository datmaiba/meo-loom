# Host Adapter — Claude Code

Registry descriptor: `registry/adapters.json#adapter_id=claude-code` (the
single source of truth; this document explains, it does not redefine).
Lifecycle: `scaffold_active`. Contract: `docs/contracts/host-adapter.md`.

## Pointer semantics

Project artifacts `.claude/CLAUDE.md` and `CLAUDE.md` are thin pointers that
import the canonical `AGENTS.md` (relative import, per the memory-import
mechanism). They select policy; they never carry it. Missing `AGENTS.md` is a
clear failure surfaced by the pointer text itself.

## Repository artifacts

`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json` (host-mandated,
repo root), the registry-owned `hooks.json` SessionStart bootstrap, and the two
pointer templates under `templates/common/`.

## Official facts (dated; re-verify before the affected RC)

See descriptor `official_facts`: CLAUDE.md → AGENTS.md import (verified
2026-07-18, code.claude.com/docs/en/memory); plugins copied to a versioned
cache, paths must stay inside the plugin root; SessionStart hooks supported.
Phase 0B live spike: installed plugin read `pack/probe.txt` outside `skills/`
in a fresh session (decision 0001, Option A).

## Conformance

- Fixture `ADAPTER-CLAUDE-LEGACY-01` plus `scripts/tests/test_adapter_conformance.py`:
  pointer targets `AGENTS.md`, no policy blocks in pointer templates, rollback
  owns only adapter-owned paths.
- Host smoke (host available to maintainer): install plugin from this branch,
  fresh session, invoke a thin trigger, confirm pack file read. Record
  transcript reference in the phase evidence bundle.

## Rollback

Remove only descriptor-listed owned paths after exact-hash check; canonical
`AGENTS.md` and docs are never adapter-owned. Verify with
`python scripts/validate.py`.
