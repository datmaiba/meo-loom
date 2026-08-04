# Host Adapter — Cursor

Registry descriptor: `registry/adapters.json#adapter_id=cursor`. Lifecycle:
`migration_ready` (fresh MeoLoom projects rely on native `AGENTS.md` discovery;
legacy `.cursorrules` is handled only by an approved migration).
Contract: `docs/contracts/host-adapter.md`.

## Pointer semantics

Cursor reads root `AGENTS.md` natively; the emitted `.cursorrules` is a
legacy-compatible thin pointer (template `templates/common/.cursorrules`)
kept byte-identical to dat-kit 1.16 scaffolding. It selects policy only. The
current migration destination is `.cursor/rules/meo-loom.mdc`.

## `.cursorrules` retirement path (Phase 3)

Official docs mark `.cursorrules` deprecated-but-supported. Phase 3 gives it
typed `RETIRE_LEGACY` semantics: recognized, inventoried, and replaced by a
`.cursor/rules/*.mdc` pointer **only inside an approved migration plan**.
Retirement is based on the dated official deprecation fact retained in
`registry/adapters.json` — MeoLoom does not claim Agent mode ignores the file.
MeoLoom 3.0 ships the migration-only `.cursor/rules/meo-loom.mdc` source.

## Official facts (dated; re-verify before the affected RC)

See descriptor `official_facts` (verified 2026-07-18, docs.cursor.com): CLI
reads root `AGENTS.md` and `CLAUDE.md`; project rules live in
`.cursor/rules`; `.cursorrules` legacy/deprecated.

## Conformance

- Fixture `ADAPTER-CURSOR-LEGACY-01` + `test_adapter_conformance.py`: both the
  legacy pointer and MeoLoom migration destination target `AGENTS.md`, remain
  policy-free, and are explicitly rollback-owned.
- Host smoke: no scriptable headless Cursor available — manual evidence
  checklist: Cursor version, project open with scaffolded tree, confirmation
  AGENTS.md is loaded as context, `.cursorrules` produces no conflicting
  instruction.

## Rollback

Remove `.cursorrules` after exact-hash check; `AGENTS.md` untouched.
