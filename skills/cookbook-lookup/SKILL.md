---
name: cookbook-lookup
description: Source a proven Claude recipe from the official anthropics/claude-cookbooks when the local repo has no template for a Claude-API or agent pattern, then hand it to build-loop to adapt and verify. Invoke when the user says "look it up in the cookbook", "find a recipe in the cookbook", "is there a cookbook example for this", or when a dev task needs a Claude-API/agent pattern (RAG, classification, summarization, tool use, structured/JSON output, prompt caching, sub-agents, evals, PDF/vision, extended thinking, Agent SDK) and no spec template, stack profile, or lessons-learned entry covers it. The cookbook recipe is a starting point, never trusted output — this skill only sources and vets it; adaptation and verification run through build-loop. Not for prose/research writing (use knowledge-work), not a way to skip existing local templates, and not for patterns the codebase already has.
---

# cookbook-lookup — borrow a proven recipe, then earn it through the loop

The [anthropics/claude-cookbooks](https://github.com/anthropics/claude-cookbooks)
repo (MIT-licensed) is a library of *API-level* recipes — how to call the Claude
API and structure agents for a known pattern. This skill turns "MeoLoom has no
template for this" into "start from a vetted recipe, then run it through the same
discipline as any other build."

The failure mode this skill exists to prevent: treating a copied cookbook cell as
finished, trusted code instead of an unvetted draft. It is not. A copied cell is
untrusted input — exactly like code a stranger pasted — until build-loop's checks
and an independent reviewer clear it. This skill only *sources and vets*; it hands
the recipe to `build-loop` and never bypasses a gate.

**Not for:** prose/research/analysis (that's `knowledge-work`); skipping local
templates (Phase 1 exhausts those first); a pattern the codebase already solves
(copy the codebase, not the web); a general web search (this is Claude-API recipes
only).

## Phase 1 — Exhaust local first (do not skip)

The cookbook is the *last* place to look, not the first. In order, check:

1. **Spec** — does `spec/` already answer the design question? Spec is law.
2. **Stack profile / templates** — `templates/profiles/<stack>/` and
   `templates/common/` may already encode the pattern for this stack.
3. **CONTEXT.md** — reason in the project's own language before importing foreign terms.
4. **lessons-learned** — has a past session already solved (or been burned by) this?
5. **The codebase itself** — if a sibling module does this, mirror it. Consistency
   with the repo beats a generic recipe every time.

Only when all five come up empty, and the gap is a *Claude-API or agent pattern*,
continue. If the gap is ordinary application code (not Claude-specific), the
cookbook won't help — go straight to `build-loop`.

## Phase 2 — Locate the recipe

**Start from the repo's own index, not a hand-drawn map.** Fetch
`raw.githubusercontent.com/anthropics/claude-cookbooks/main/registry.yaml` — every
recipe listed with `title`, `path`, `description`, and `categories` — and grep it
for the pattern. It is the authoritative, current locator; the table below is only
rough orientation and can lag the repo.

| You need… | Look near |
|---|---|
| Classification | `capabilities/classification/` |
| RAG / retrieval | `capabilities/retrieval_augmented_generation/`, `capabilities/contextual-embeddings/` (context + embeddings), `third_party/` (Pinecone, MongoDB, LlamaIndex) |
| Summarization | `capabilities/summarization/` |
| Text-to-SQL | `capabilities/text_to_sql/`, `misc/how_to_make_sql_queries.ipynb` |
| Tool use / function calling | `tool_use/` (calculator, customer_service_agent, tool_choice, parallel_tools) |
| Structured / JSON output | `tool_use/extracting_structured_json.ipynb`, `misc/how_to_enable_json_mode.ipynb` |
| Prompt caching | `misc/prompt_caching.ipynb`, `misc/speculative_prompt_caching.ipynb` |
| Context / memory management | `tool_use/memory_cookbook.ipynb`, `tool_use/context_engineering/`, `misc/session_memory_compaction.ipynb` |
| Sub-agents / agent workflows | `multimodal/using_sub_agents.ipynb`, `patterns/agents/` (orchestrator, evaluator-optimizer, basic workflows) |
| Automated evals / test cases | `misc/building_evals.ipynb`, `misc/generate_test_cases.ipynb`, `tool_evaluation/`, `patterns/agents/evaluator_optimizer.ipynb` |
| Moderation filter | `misc/building_moderation_filter.ipynb` |
| Vision / charts / PDF transcription | `multimodal/`, `misc/pdf_upload_summarization.ipynb` |
| Extended thinking | `extended_thinking/` |
| Agent SDK patterns | `claude_agent_sdk/` |
| Managed Agents (server-side) | `managed_agents/` |
| Observability / usage & cost | `observability/usage_cost_api.ipynb` |
| Building custom Claude Skills | `skills/notebooks/` |
| Frontend prompting | `coding/prompting_for_frontend_aesthetics.ipynb` |

Recipes are `.ipynb` (JSON) — read the cells, don't render. If a fetch of a
client-rendered GitHub page returns a shell, fetch the raw file
(`raw.githubusercontent.com/...`) or use the Chrome tools instead.

**Nothing fits?** Say so. A forced-fit recipe is worse than none — fall back to
`build-loop` designing from scratch. Do not stretch an unrelated recipe.

## Phase 3 — Vet before you borrow

Extract the *minimal* relevant snippet and interrogate it against the target repo:

- **Model & API drift** — recipes may pin old model strings or an SDK version.
  Check current model names and SDK shape against `docs/model-selection.md` and
  the installed SDK; the cookbook is a pattern, not a version pin.
- **Language / stack fit** — the cookbook is mostly Python notebooks. If the repo
  is TypeScript/React (or anything else), you are porting the *pattern*, not the
  code. Name what changes.
- **Security & secrets** — never carry over hardcoded keys, permissive CORS, or
  `verify=False`. Flag anything the `security-reviewer` would reject on sight.
- **Scope** — take the one cell that answers the gap. Leave demo scaffolding,
  print-debugging, and unrelated helpers behind.

State, in one line, what you're borrowing and what you're changing:
> "Borrowing the RAG chunk-and-embed loop from `capabilities/contextual-embeddings`; porting from Python to our TS + pgvector; dropping the notebook's inline key."

## Phase 4 — Hand to build-loop to adapt + verify

The recipe is an *input to a build*, not a commit. Enter `build-loop` (or its
delegated-build brief) with the vetted snippet as the starting design:

- The self-question phase reconciles the recipe with the spec and CONTEXT.md.
- The build adapts it into the codebase's conventions, naming, and stack profile.
- Verified checks and the independent reviewer chain (`qa-agent` → `code-reviewer`
  → `security-reviewer`) clear it — the same bar as any other code. **Evidence over
  claims:** green checks + a working demo, never "the cookbook says it works".

For a hard defect surfacing during the adapt, `diagnosing-bugs` applies as usual.

## Phase 5 — Attribute + harvest

- **Attribution** — the repo is MIT; when code is materially derived, note the
  source (recipe path + repo) in a comment or the PR message, and keep the MIT
  notice for a non-trivial copied block. Recipes under `third_party/` integrate
  external libraries (Pinecone, MongoDB, LlamaIndex, ElevenLabs, WolframAlpha…) and
  may carry additional vendor terms or non-MIT dependencies — check before copying.
- **Lesson** — append a lessons-learned entry: which recipe, what had to change to
  fit the repo, and any drift you hit (stale model string, Python-only assumption).
  A recipe you keep re-borrowing is a template you haven't written yet — if the
  pattern recurs, propose promoting it into `templates/profiles/<stack>/` so it
  wins Phase 1 next time.
