# Migrating a project from dat-kit 1.16 to dat-kit 2.0

This guide covers moving an existing dat-kit-scaffolded project from contract
revision `dat-kit 1.16.0` to `dat-kit 2.0`. It is written entirely from proven
migration runs performed against real fixtures and a real project during the
v2.0.0 release train — every claim below cites the run that proved it. It does
not describe untested behavior.

`dat-kit 1.16.0` is a **recognized migration source, never a green revision**.
Tooling on `dat-kit 2.0` fails closed against a 1.16 project with a named
diagnostic; it never silently treats an old project as current.

## Before you start

1. **Commit or stash outstanding work.** The migration planner runs read-only
   and never mutates your tree by itself, but the *apply* step edits files —
   don't mix migration changes into unrelated WIP.
2. You need the `dat-kit 2.0` tooling checked out (this repo, or an installed
   `dat-kit` plugin at 2.0) and Python 3 available to run
   `scripts/contract_check.py`.

## Step 1 — generate the plan (read-only)

```bash
python "<DAT_KIT_ROOT>/scripts/contract_check.py" --target . --migration-plan
```

This never writes anything. It reads your project's `AGENTS.md` and legacy
runtime files and reports what it finds.

**What to expect, from actual runs:**

- A **clean 1.16 project** (no local edits to the shipped template) produces a
  plan with three steps: `AGENTS.md` `MIGRATE_REPLACE` (replaced with the 2.0
  template, project name preserved), `.cursorrules` typed `RETIRE_LEGACY`, and
  `.cursor/rules/dat-kit.mdc` `ADD` (the new pointer). Verified against the
  `scaffold_v116_contract` fixture and, separately, against a real project
  (the owner's blog repo, verified via an isolated clone so the live working
  tree was never touched): the plan proposed exactly `AGENTS.md`
  `MIGRATE_REPLACE`, `.cursorrules` `RETIRE_LEGACY`, `.cursor/rules/dat-kit.mdc`
  `ADD` — nothing else, and the project-owned
  `docs/agent-working-rules.md` (real stack rules, ~140 lines) was correctly
  **absent from the plan entirely**, because the tool recognized it as
  project-owned content, not shipped template. The planner neutralizes the
  rendered project name only when it matches the target directory name, then
  compares `AGENTS.md` with the immutable 1.16 template hash; a renamed target
  or any other difference fails closed as customization.
- A **customized 1.16 project** (local edits to `AGENTS.md` or
  `docs/agent-workflow.md`, plus user-authored spec content) adds a
  `MERGE_CANONICAL_POLICY` with a `PRESERVATION` destination. The customized
  `AGENTS.md` regression fixture proves the planner is deterministic,
  read-only, and names that preservation step. The separately applied
  customized-workflow fixture restored the canonical workflow bytes and
  appended its customized policy to `docs/agent-working-rules.md` under a
  **provenance heading**.

Read the plan before applying anything. It is deterministic — the same project
state always produces the same plan.

## Step 2 — apply

Applying is manual, on purpose: the checker plans, it does not execute
unattended changes to your policy files. Follow the exact steps the plan
printed. The approved order is:

1. For a clean `AGENTS.md` `MIGRATE_REPLACE` step, replace it with the 2.0
   template (project name substituted). If the plan instead reports
   `MERGE_CANONICAL_POLICY`, preserve its user-authored policy in
   `docs/agent-working-rules.md` under the provenance heading before replacing
   the canonical shell.
2. Remove `.cursorrules` (`RETIRE_LEGACY`).
3. Add `.cursor/rules/dat-kit.mdc` (the new pointer artifact).

## Step 3 — verify

```bash
python "<DAT_KIT_ROOT>/scripts/contract_check.py" --target .
```

Expect **exit 0** after a correct apply. In the real-project run (isolated
clone), `git status --porcelain` showed exactly the three predicted changes
and nothing else, and `sha256sum docs/agent-working-rules.md` was
byte-identical before and after — project-owned policy is preserved, not
touched, by a clean-case migration.

## What preservation guarantees, and what it doesn't

- **Project-owned files are never silently overwritten.** `AGENTS.md`
  customizations beyond its rendered project name and
  `docs/agent-working-rules.md` are recognized and preserved by semantic merge
  with a provenance heading — never byte-replacement.
- **A failed or partial migration never corrupts your tree.** In the rollback
  rehearsal (below), every fail-closed path left the target directory
  byte-identical to its pre-attempt state.
- **The plan step order matters** — apply in the order printed, since later
  steps (like the merge) assume the earlier ones landed.

## The three failure modes you'll actually see

These are the real diagnostics from proven runs, not a theoretical list.

- **`CONTRACT_MIGRATION_REQUIRED`** — the project's `AGENTS.md` declares
  `dat-kit 1.16.0`. This is expected on every 1.16 project before migration;
  it is what tells you to run `--migration-plan`. It also reappears if you
  deliberately roll a project back to 1.16-era tooling afterward (confirmed in
  the rollback rehearsal, run E: a 1.16 project stays a clean migration
  source after a round trip through rollback).
- **`COMPETING_AGENTS`** — the current-revision checker finds an `AGENTS.md`
  it does not recognize as its own canonical contract (for example, running
  **1.17.1-era tooling** against a **2.0-scaffolded** project). This is the
  fail-closed signal that you're pointing tooling at a project whose contract
  it doesn't own — proven here for old tooling against a newer project; a 2.0
  checker against an unmigrated 1.16 project instead produces
  `CONTRACT_MIGRATION_REQUIRED` (see above), not this diagnostic. Verified in
  the rollback rehearsal: v1.17.1 `contract_check.py`
  against a 2.0 project produced `COMPETING_AGENTS: AGENTS.md is not the
  current dat-kit canonical contract` — no traceback, and the target
  directory was untouched.
- **`BROWNFIELD_CONTRACT_CONFLICT`** — attempting a plain re-scaffold
  (`init.sh --here`) against a project whose contract the running tooling
  doesn't own. Verified in the same rehearsal: v1.17.1 `init.sh --here`
  against a 2.0 project failed closed with `COMPETING_AGENTS` plus
  `BROWNFIELD_CONTRACT_CONFLICT: migrate manually; see …/docs/codex.md`, and
  the directory was byte-identical afterward (2.0 `AGENTS.md`, user notes, and
  spec content all intact).

## Rollback path (if you need to go back to 1.17.1)

dat-kit 2.0 does not remove the ability to run 1.17.1-era tooling; the two
eras simply refuse to operate on each other's projects (see the diagnostics
above). A live rehearsal proved the round trip is safe:

- v1.17.1 tooling against a v1.17.1-era project: **exit 0**, silent success,
  idempotent rerun (`init.sh --here` rerun produced a byte-identical
  directory).
- v1.17.1 tooling against a 2.0 project: fails closed (`COMPETING_AGENTS` /
  `BROWNFIELD_CONTRACT_CONFLICT`), every byte preserved.
- A 1.16-era project that lived through a rollback remains a clean
  `CONTRACT_MIGRATION_REQUIRED` source for 2.0 tooling afterward — nothing
  about the round trip corrupts forward migratability.

If you roll back, note that v1.17.1's own error text points at
`docs/codex.md`. That file is kept as a load-bearing redirect stub in this
repo for exactly this reason — do not delete it while any project might still
run 1.17.1 tooling.

## See also

- [`adapters/codex/ADAPTER.md`](../../adapters/codex/ADAPTER.md) — host-specific
  migration reference and contract file ownership table.
- [README Quick start](../../README.md#quick-start) — the same commands in
  context with the rest of the install flow.
- [`docs/contracts/registry.md`](../contracts/registry.md) — current registry,
  snapshot, and migration invariants.
