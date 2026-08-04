# Host Adapter — Codex

Registry descriptor: `registry/adapters.json#adapter_id=codex`. Lifecycle:
`repo_only` (no project artifact exists or is emitted). Contract:
`docs/contracts/host-adapter.md`.

This document also carries the Codex host guide and the brownfield migration
reference formerly published as `docs/codex.md` (now a redirect stub).

## Pointer semantics

Codex reads `AGENTS.md` natively — the canonical contract needs no pointer
file, so this adapter owns **zero** project artifacts. Missing `AGENTS.md`
degrades to documented host-default behavior (`documented-degradation`).

## Repository artifacts

`.agents/plugins/marketplace.json` and `.codex-plugin/plugin.json`
(host-mandated, repo root; `skills: ./skills/`).

## Official facts (dated; re-verify before the affected RC)

See descriptor `official_facts`: native AGENTS.md discovery (verified
2026-07-18, learn.chatgpt.com/docs/agent-configuration/agents-md); plugins
install via local marketplace and need a fresh session after install/update.
Phase 0B live spike on Codex CLI 0.144.4: installed plugin materialized and
read a file outside `skills/` (decision 0001) — the previously UNVERIFIED
claim in the plan's factual footer is now verified evidence.

## Conformance

- Fixture `ADAPTER-CODEX-01` + `test_adapter_conformance.py`: no project
  artifacts, no duplicate policy surface, rollback owns only the two
  manifests.
- Host smoke (host available to maintainer): reinstall plugin, fresh
  `codex exec` run, invoke thin trigger, confirm pack read.

## Rollback

Remove the two manifests only; project trees are untouched by definition.

---

# Codex host guide

## Install

For published releases, add the repository marketplace and install `meo-loom`
from it:

```bash
codex plugin marketplace add datmaiba/meo-loom
codex plugin add meo-loom@meo-loom
```

Start a new Codex task after installing or updating so skill metadata is
refreshed. In the desktop app, the repository marketplace is also
discoverable from the plugin directory.

## Project scaffolding and migration

`project-init` creates a canonical `AGENTS.md` (revision `MeoLoom 3.0`),
shared `docs/agent-*.md`, and pointer-only compatibility files (`CLAUDE.md`,
`.claude/CLAUDE.md`). All hosts read `AGENTS.md` first; no adapter may
duplicate its policy.

Brownfield scaffolding is two-pass and fail-closed. `init.sh --here` requires
Python and runs `scripts/contract_check.py --target .` before any mutation. A
competing `AGENTS.md`, substantive runtime pointer, legacy contract, unsafe
symlink, or incompatible partial install produces a named diagnostic and
leaves the complete destination unchanged. `dat-kit 2.0` and `dat-kit 1.16.0`
projects are recognized migration sources and fail closed with
`CONTRACT_MIGRATION_REQUIRED`. Generate the deterministic read-only plan:

```bash
python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target . --migration-plan
python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target . --migration-plan --format json
```

The plan exits non-zero while drift remains and never changes the target.
Review and approve it separately, then apply its steps and rerun the checker
until exit 0. See [`docs/releases/migration-2.0.md`](../../docs/releases/migration-2.0.md) for a
full walkthrough with proven-transcript examples and the exact fail-closed
diagnostics (`CONTRACT_MIGRATION_REQUIRED`, `COMPETING_AGENTS`,
`BROWNFIELD_CONTRACT_CONFLICT`) you may see.

### Contract file ownership (migration planner classification)

| Class | Files | Migration rule |
|---|---|---|
| Static MeoLoom assets | `CLAUDE.md`, `.claude/CLAUDE.md`, `docs/agent-workflow.md` | Inventory any project additions, move them to project-owned policy, then replace from the exact shipped template. |
| Project-owned policy | `AGENTS.md`, `docs/agent-working-rules.md` | `AGENTS.md` is replaced from the MeoLoom 3.0 template; customized policy is semantically merged into `docs/agent-working-rules.md` under a provenance heading — never byte-replaced or discarded. |
| Legacy artifacts | `.cursorrules` | Typed `RETIRE_LEGACY`: retired and replaced by the `.cursor/rules/meo-loom.mdc` pointer, only inside an approved migration plan. |
| Runtime adapters | `.codex/config.toml`, `.codex/hooks.json` | Inspect tracking, routing, commands, and workflow dependencies manually before removal. |

The package version and project-contract revision are independent: MeoLoom
3.0.0 ships with `MeoLoom 3.0` as the only green revision and accepts
`dat-kit 2.0` and `dat-kit 1.16.0` solely as migratable sources (nonzero
diagnostic until the approved migration is applied).

## Host-specific behavior

| Capability | Claude Code | Codex |
|---|---|---|
| Plugin manifest | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` |
| Session bootstrap | Included through `hooks.json` | No shipped hook; skills plus `AGENTS.md` provide the workflow |
| Reviewer profiles | `agents/*.md` frontmatter and model routing | Fresh subagents use the same reviewer charters; no unverified model-routing schema |
| Token attribution | Exact session totals only when one session maps to one task | Parser unverified; new records keep `tokens: null` with `unsupported_provider` |

## Scorecard

Append through the helper instead of writing JSONL directly:

```bash
python3 scripts/scorecard.py --provider codex --project . --append-record record.json
```

`--provider codex` records `tokens: null` with the reason
`unsupported_provider`; it never estimates usage. Claude Code may use
`--provider claude`, but session totals are persisted only when exactly one
transcript session maps to the new task and no prior scorecard task maps to
the same session. Running the helper without `--append-record` may enrich a
report in memory; it never writes those display-only values back to history.

Scorecard lines use schema v2 and record `agent_runtime` (`claude-code`,
`codex`, `cursor`, or `other`), workflow, canonical-contract revision, and Git
state. Historical v1 lines remain append-only and valid only before the first
v2 record.

## Development checks

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate.py
python3 scripts/render.py --check
```

The validator checks both plugin manifests, both marketplaces, the shared
skill path, and the registry (including generated-projection byte checks). CI
also smoke-tests that scaffolding creates the Codex entrypoint without
overwriting existing project guidance.

## Optional companion tools

CodeGraph and Headroom are local, opt-in companions; neither is required for
MeoLoom. Keep `.codegraph/codegraph.db` machine-local and commit only its
generated `.codegraph/.gitignore`. Restart Codex after changing a global MCP
entry. A configured Headroom MCP server exposes tools but does not activate
proxy routing; `headroom wrap codex` is the explicit opt-in route. Do not run
`specify init --here --force` in an existing MeoLoom repository without an
approved file-by-file migration plan.

## Local adapter cleanup

`.codex/config.toml` and `.codex/hooks.json` are intentionally untracked. Keep
proxy URLs, absolute paths, MCP servers, and statuslines machine-local and
opt-in. This repository also ignores `.claude/settings.local.json`; if it
still contains a Headroom SessionStart hook, remove that hook manually and
verify with `git check-ignore .claude/settings.local.json` plus a fresh
session. Do not edit the ignored file as part of a repository migration.

The Claude SessionStart adapter calls `node` only to print a neutral pointer
to root `AGENTS.md`. If the hook or `node` is unavailable, startup remains
safe: supported runtimes read `AGENTS.md` directly, and no unique policy lives
in the adapter.

Installed plugins and already-open sessions retain prior metadata until the
plugin is updated/reinstalled and a fresh session starts. The no-drift claim
applies only after `contract_check.py` validates the canonical installation;
unmigrated brownfield repositories may still contain competing policy.
