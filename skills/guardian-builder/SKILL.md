---
name: guardian-builder
description: >-
  Generate a project-specific "guardian" skill — a mandatory pre-coding checklist
  distilled from a repo's real conventions, lessons-learned, and known traps.
  Invoke when the user says "create a guardian for this repo", "build a pre-coding
  checklist", "make Claude respect this codebase's conventions", "generate project
  rules skill", or complains that AI keeps repeating the same mistakes in a codebase.
  The generated guardian enforces reading lessons-learned first, observed
  naming/architecture conventions, scope declaration before editing, plan-gated
  execution, self-review before presenting, duplication flagging, and a ban on
  ticket/scaffolding comments. Works for any language or stack — conventions are
  scanned from the actual codebase, never assumed.
---

# guardian-builder — generate a guardian skill for any repo

A **guardian** is a mandatory pre-coding checklist for one specific repo: the things an AI must check before writing any code there, distilled from how that codebase actually works and the mistakes already made in it. This skill builds that guardian. You are writing rules another AI session will follow blindly — be concrete, cite real examples from the repo, and never invent conventions the code doesn't show.

## Process

### 1. Scan the repo (evidence, not assumptions)

Establish each convention from at least 2–3 real examples in the code:

- **Naming**: folder casing, file suffixes, function/hook/component prefixes, test file placement.
- **Architecture**: layer boundaries and direction (what imports what), where shared code lives, entry-point patterns.
- **Styling** (if frontend): token system vs raw values, class naming scheme, where styles live.
- **Testing & gates**: which runners exist, how they're invoked (docker? npm scripts? make?), what "green" means here.
- **Lessons-learned**: read `lessons-learned/` or any equivalent (`docs/mistakes.md`, ADRs with regrets). Every entry becomes a guardrail candidate.
- **Traps**: paging conventions, validator quirks, framework foot-guns already encountered.

Where the codebase is inconsistent, note the dominant pattern and the exceptions — the guardian should enforce the dominant one and name the legacy exceptions so the AI doesn't "learn" from them.

### 2. Draft the guardrails

Standard set — keep the numbering, drop what doesn't apply, add repo-specific ones:

1. **Lessons first** — read the repo's lessons-learned file(s) before any code; never reintroduce a documented mistake.
2. **Naming & structure** — the conventions from step 1, with concrete ✅/❌ examples from this repo.
3. **Scope discipline** — declare files to touch before editing; ask before crossing into shared/core areas (name the actual directories).
4. **Styling rules** (frontend) — tokens/variables only, no raw values; cite the token file path.
5. **Known traps** — the specific silent failures from step 1, each with the symptom and the correct pattern.
6. **Self-review** — before presenting, re-check the work against every guardrail; list violations found and fixed.
7. **Duplication flag** — when reviewing or adding code, flag copy-paste blocks and near-duplicates; propose the extraction or warn if out of scope.
8. **Plan gate** — when the prompt asks for a plan, present the plan and stop; no mutations until explicit approval.
9. **No scaffolding comments** — no ticket IDs, design-node refs, "old X"/"new X" markers, or commented-out code; comments explain *why* only.

### 3. Confirm with the user

Present the draft as numbered findings: each guardrail + the evidence it's based on. Ask about anything ambiguous (dominant-vs-legacy calls, directories that count as "shared"). One round — don't interrogate.

### 4. Write the guardian

Create `<target-repo>/.claude/skills/<repo-name>-guardian/SKILL.md`:

- Frontmatter description MUST be pushy and repo-specific: "Mandatory pre-coding checklist for <repo>. Invoke before writing, editing, or planning ANY code here…" and list trigger phrases. Keep it under 1024 characters.
- Body: the guardrails with the repo's real paths and examples. Target under 150 lines — a guardian is a checklist, not documentation.
- If the repo has no lessons-learned file yet, create an empty `lessons-learned/lessons-learned.md` with the entry format (date · context · mistake · correct pattern) and wire guardrail 1 to it.

### 5. Hand over

Tell the user: how to verify it triggers (open a session in the repo, ask for a small code change, the guardian should activate), and that the guardian should be updated whenever a new lesson lands — the pairing that makes it compound over time.

## Rules for the generated guardian

- Every rule must be checkable — "write clean code" is not a guardrail; "SCSS uses `var(--token)`, never raw hex — tokens live in `src/styles/tokens.scss`" is.
- Prefer explaining *why* a rule exists (one clause) over bare commands — future models follow understood rules better than arbitrary ones.
- The guardian never duplicates what the repo's canonical `AGENTS.md` contract already enforces — it references and extends, or the two will drift apart.
