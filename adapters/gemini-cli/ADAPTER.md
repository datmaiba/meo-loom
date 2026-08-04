# Host Adapter — Gemini CLI

Registry descriptor: `registry/adapters.json#adapter_id=gemini-cli`.
Lifecycle: `repo_only` — conformance-tested in-repo, **never emitted** until
activation gates pass on a live host. Contract: `docs/contracts/host-adapter.md`.

## Pointer semantics

A project `GEMINI.md` (template: `templates/adapters/gemini-cli/GEMINI.md`)
is a thin pointer importing `AGENTS.md` via the context-file `@` import.
It selects policy; it never carries it. Missing `AGENTS.md` is a clear
failure (broken import is visible in the context file).

## Repository artifacts

`adapters/gemini-cli/ADAPTER.md` and the pointer template. No
`gemini-extension.json` is committed yet: the extension manifest becomes a
repository artifact only when the adapter leaves `repo_only`.

## Official facts (dated; re-verify before activation AND the affected RC)

See descriptor `official_facts` (verified 2026-07-18 against
github.com/google-gemini/gemini-cli docs): extensions are copied on install
with root `gemini-extension.json`; `contextFileName` defaults to `GEMINI.md`;
context files support relative `@file` imports; changes require
update/restart. No live-host run has been performed — that is exactly why
this adapter stays `repo_only`.

## Activation gates (all required before `migration_ready`)

1. Live Gemini CLI session: install extension, fresh session, confirm the
   context import of `AGENTS.md` resolves and a pack file outside `skills/`
   is readable (Option A assumption re-verified per host).
2. Clean + customized brownfield fixtures for `GEMINI.md`.
3. Personal-info gate green on all emitted artifacts.
4. Rollback fixture removes only `GEMINI.md`.

## Manual evidence checklist (host unavailable in CI)

Record in the phase evidence bundle: CLI version, install command, fresh
session proof, `@AGENTS.md` resolution proof, pack-read proof, failure
behavior with `AGENTS.md` removed, uninstall/rollback proof.
