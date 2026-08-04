---
name: project-init
description: >-
  Scaffold a spec-driven project the MeoLoom way — a canonical AGENTS.md contract,
  pointer-only runtime adapters, a spec/ skeleton (00-vision through 08-decisions),
  working rules, and a lessons-learned file. Invoke when the user wants to start a new project ("init a
  project", "scaffold my-app", "set up a new repo the MeoLoom way") or adopt the
  structure in an existing repo ("adopt MeoLoom here", "add a spec structure to this
  project"). Greenfield creates a fresh directory; brownfield (--here) only adds
  missing files and never overwrites. After scaffolding, guide the user to fill the
  spec and hand off to the build-loop skill.
---

# project-init — scaffold a spec-driven project

## 1. Gather inputs (ask only what's missing)

- **Project name** (directory-safe).
- **One-line description** — what it is, for whom.
- **Stack profile** — list what exists in `${CLAUDE_PLUGIN_ROOT}/templates/profiles/` and let the user pick; default `laravel-react`. If their stack has no profile yet, say so plainly: scaffold with `common/` only and tell them the architecture section of `docs/agent-working-rules.md` must be written by hand (offer to draft it from their description — but mark it unproven, unlike a battle-tested profile).
- **Greenfield or brownfield** — new directory, or `--here` into the current repo.

## 2. Run the scaffold

### Brownfield agent-tools checklist (before suggesting a command)

For an existing repository, inspect and report the presence of `AGENTS.md`,
`spec/`, `.codex/`, `.agents/`, `.codegraph/`, and `skills-lock.json` before
suggesting any scaffold or companion-tool command. These files can represent an
existing contract, runtime adapter, local index, or third-party skill install.
`project-init --here` remains additive, but another tool's initializer may not
be. Do not run an initializer that can merge or overwrite these files without a
file-by-file plan approved by the user.

### Package root (Claude Code and Codex)

Resolve `DAT_KIT_ROOT` before invoking the script. In Claude Code it is
`${CLAUDE_PLUGIN_ROOT}`. In Codex, start from the directory containing this
skill's `SKILL.md`, then go up two directories to the package root. The commands below use `DAT_KIT_ROOT` so neither
host depends on the other's environment variables.

```bash
bash "$DAT_KIT_ROOT/scripts/init.sh" <name> --profile <profile> --desc "<one-liner>"
# or, inside an existing repo:
bash "$DAT_KIT_ROOT/scripts/init.sh" --here --profile <profile>
```

Brownfield requires Python and runs `scripts/contract_check.py --target .` before
any filesystem mutation. It fails closed on competing policy, bad pointers,
unsafe symlinks, or incompatible partial installs. Legacy migration is manual;
follow the named diagnostic and generate a read-only, file-by-file plan with
`python "<DAT_KIT_ROOT>/scripts/contract_check.py" --target . --migration-plan`.
Present that plan for approval and stop. Plan generation is not migration: do
not transform, replace, or delete target files until the separate plan is
approved. See `docs/codex.md` for the static/project-owned file boundary.

If bash is unavailable, run the same read-only preflight first:
`python "<DAT_KIT_ROOT>/scripts/contract_check.py" --target .`. Only after it
returns zero may you copy files manually from the package templates. If Python
is also unavailable, manually inventory `AGENTS.md`, every pointer listed by
`contract_check.py --registry-json`, `docs/agent-*.md`, `.codex/` runtime config,
legacy `CLAUDE.md.tpl`/`rules/working.rules.md`, and symlinks; stop on any
existing conflict. Never copy first and inspect afterward.

## 3. After scaffolding — the part that actually matters

An empty spec skeleton has zero value until filled. Walk the user through it in this order, one file at a time, drafting content from their answers:

1. `spec/00-vision.md` — what, for whom, success, non-goals (non-goals are the highest-value 5 minutes of the whole setup).
2. `spec/01-features.md` — feature list with P0/P1/P2.
3. `spec/02-architecture.md` + `03-db-schema.md` — topology and data. Probe real constraints; don't let placeholders survive.
4. `spec/04-build-phases.md` — slice P0 features into phases with Scope + Demo each.
5. Skim `05`–`07` — fill what's known, leave honest TODOs for what isn't.
6. `CONTEXT.md` — seed the glossary with 3–5 domain terms that came up while filling the spec (one line each). It grows during build phases; it must not start empty of the terms you already used.

Adjust the gate commands in `docs/agent-working-rules.md` to the project's real service names before the first build phase.

## 4. Suggest companion tools (detect, don't install)

### Runtime adapters

When the scaffold script cannot run in Codex, use `$DAT_KIT_ROOT/templates/`
instead of the Claude-only environment-variable path mentioned above. The root
`AGENTS.md` is the project entrypoint for every host; `CLAUDE.md`,
`.claude/CLAUDE.md`, and `.cursorrules` remain pointer-only compatibility files.

MeoLoom is a methodology, not a package manager — it never installs anything for the user. But two optional, independent, local-first tools pair well with the build loop, and a fresh repo is the natural moment to point them out. **Detect, then suggest the exact command — never run a privileged install yourself.**

- **CodeGraph** (semantic code index → far fewer tool calls when exploring a repo). Two checks:
  - `command -v codegraph` missing → suggest it once with the one-time, per-machine install command (`npm install -g @colbymchenry/codegraph`; note a user npm prefix or `sudo` may be needed if the global dir isn't writable), then stop.
  - CLI present but the repo has no `.codegraph/` → suggest `codegraph init -i` to index this project.
  - Keep the database machine-local: commit only `.codegraph/.gitignore` when it
    is generated; never commit `.codegraph/codegraph.db`. After adding or
    changing a global Codex MCP entry, restart Codex before testing the tool.
- **Headroom** (local context compression → fewer tokens). Optional. In a
  Unix-like shell, if `command -v headroom` is missing, mention it once with
  `pip install "headroom-ai[all]"` and stop. On other hosts, tell the user to
  consult that runtime's installation method. Its failure-mining (`headroom
  learn`) only pays off once the repo has real session history, so don't push it
  on a fresh repo. Never generate or depend on a Headroom hook until that host's
  hook schema is verified. A configured Headroom MCP server only makes its tools
  available; it does **not** route Codex traffic through the proxy. Use
  `headroom mcp status` for MCP availability and `headroom doctor` for proxy
  state. Routing is opt-in: the user may explicitly run `headroom proxy` or
  `headroom wrap codex` after reviewing the effect.

- **Spec Kit** (optional spec workflow experiments). A user may install
  `specify-cli` globally, but never suggest or run `specify init --here --force`
  inside an existing MeoLoom project without an explicit, file-by-file migration
  plan: it can merge or overwrite scaffold files.

- **Third-party skills**. Never auto-enable an installed skill. If its installer
  reports a security risk level, surface the exact level to the user and record
  it in the handoff or upgrade log rather than burying it in terminal output.
- **caveman** (output compression → ~65% fewer *output* tokens, MIT). Optional. Orthogonal to MeoLoom: MeoLoom governs how the agent *works*, caveman governs how it *talks*. If the user wants the full ecosystem (multi-level incl. `wenyan`, `/caveman-commit`, `/caveman-review`, lifetime-savings badge), mention the installer once (`curl -fsSL https://raw.githubusercontent.com/JuliusBrussee/caveman/main/install.sh | bash`) and stop. **First point them at MeoLoom's own `terse-mode` skill** — zero dependency, no second SessionStart hook, no statusline contention, and it already carves out evidence/gates/approval stops. Only suggest caveman if they want more than terse-mode gives. Whichever they pick, run one, not both.
- **cavemem** (cross-agent memory, sibling of caveman). Optional and also orthogonal; mention only if the user raises cross-session memory. **Do NOT suggest `cavekit`** — it is a competing spec-driven build loop that overlaps MeoLoom's own build-loop; pulling it in creates two rival disciplines in one repo.

Rules: suggest each tool at most once per repo; if the user declines, or the tool is already set up, say nothing further. Never run `npm` / `pip` / `sudo` on the user's behalf — print the command and let them decide. These are independent projects with their own release cycles; MeoLoom only points at them, it does not wrap or version them.

## 5. Hand off

In every supported runtime, `AGENTS.md` is the entrypoint: it routes the agent
to the canonical shared project contract and the rest of the generated project
context.

Tell the user: run the **build-loop** skill for phase 0 (or "autopilot from phase 0" — PREFLIGHT will batch every open decision into one questionnaire, recorded in `spec/08-decisions.md`). The scaffold is done when an agent opened in the project reads `AGENTS.md` and can recite the rules on "verify rules".
