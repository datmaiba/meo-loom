---
name: git-worktrees
description: Set up an isolated git workspace before feature work or executing a build-loop plan, so changes never touch the branch you're standing on. Invoke when the user wants to work on a feature in isolation, run multiple branches or agents in parallel, try something risky without disturbing the current checkout, or says "worktree", "isolate this", "new branch in its own folder". Detects existing isolation first, prefers the harness's native worktree tool, falls back to `git worktree` only when none exists, verifies the worktree dir is gitignored, runs project setup, and confirms a clean test baseline before work starts. Not needed when you're already in a linked worktree or the user explicitly wants to work in place.
---

# git-worktrees — an isolated workspace before you touch anything

**Core principle:** detect existing isolation → use native tools → fall back to
git → never fight the harness. A worktree protects the branch you're on from
half-finished work, and lets several branches (or agents) run at once.

## Step 0 — Detect existing isolation (always first)

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

`GIT_DIR != GIT_COMMON` usually means you're already in a linked worktree — but it
is *also* true inside a **submodule**. Guard against that:

```bash
git rev-parse --show-superproject-working-tree 2>/dev/null   # prints a path ⇒ submodule, treat as normal repo
```

- **Already in a worktree** (and not a submodule): skip to Step 2. Report the path
  and branch. Never nest a worktree inside a worktree.
- **Normal checkout:** if the user hasn't already stated a preference, ask consent —
  *"Set up an isolated worktree? It keeps your current branch clean."* If they
  decline, work in place and skip to Step 2.

## Step 1 — Create the workspace

### 1a. Native tool (preferred)

If the harness offers a worktree mechanism — a tool named like `EnterWorktree` /
`WorktreeCreate`, a `/worktree` command, or a `--worktree` flag — **use it** and
skip to Step 2. It handles placement, branch creation, and cleanup. Using
`git worktree add` when a native tool exists creates phantom state the harness
can't see. This is the #1 mistake.

### 1b. Git fallback (only if no native tool)

Pick the directory by priority: explicit user preference → an existing
`.worktrees/` (wins over `worktrees/`) → default `.worktrees/` at repo root.

**Verify it's ignored before creating anything** — otherwise worktree contents get
committed:

```bash
git check-ignore -q .worktrees 2>/dev/null || { echo ".worktrees/" >> .gitignore && git add .gitignore && git commit -m "chore: ignore worktrees"; }
git worktree add ".worktrees/$BRANCH_NAME" -b "$BRANCH_NAME"
cd ".worktrees/$BRANCH_NAME"
```

**Sandbox fallback:** if `git worktree add` fails with a permission error, tell the
user the sandbox blocked it and you're working in place instead — then continue.

## Step 2 — Project setup

Auto-detect and run the right install:

```bash
[ -f package.json ]     && npm install
[ -f Cargo.toml ]       && cargo build
[ -f requirements.txt ] && pip install -r requirements.txt
[ -f pyproject.toml ]   && (poetry install 2>/dev/null || pip install -e .)
[ -f go.mod ]           && go mod download
```

## Step 3 — Verify a clean baseline

Run the project's test / gate command. **Tests fail?** Report the failures and ask
whether to proceed or investigate — a dirty baseline means you can't tell your new
bugs from pre-existing ones. **Tests pass?** Report ready:

```
Worktree ready at <full-path>, branch <name>
Baseline green (<N> tests, 0 failures)
```

Now hand off to build-loop (or start the feature). At the end, use build-loop's
`finishing` flow or merge/PR the branch, then remove the worktree:
`git worktree remove <path>`.

## Red flags — never

- Create a worktree when Step 0 already found isolation.
- Use `git worktree add` when a native worktree tool exists.
- Skip the `git check-ignore` verification for a project-local dir.
- Start work on a red baseline without asking.
