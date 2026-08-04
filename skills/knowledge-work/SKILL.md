---
name: knowledge-work
description: >-
  The working loop for knowledge work — research, writing, analysis, synthesis, and documentation. Invoke when the user wants to write a researched report, produce a briefing or memo, do a literature or market review, fact-check a document, or synthesize sources into an argument. Loads the work-loop engine plus the knowledge-work Domain Pack (six slots: workflow, ground truth, gates, reviewers, deliverables, loop profile). Capped at the Goal loop — its load-bearing gate (does the cited source actually support the claim?) needs a human reviewer to close, so it never runs on a schedule or unattended. MeoLoom's first non-dev Domain Pack.
---
<!-- GENERATED FROM REGISTRY — DO NOT EDIT; source_revision=domains/1 -->

# knowledge-work

Resolve domain `knowledge-work` through the Registry Catalog.
Load engine `work-loop/1` and pack `domains/knowledge-work`.
Load the six semantic slots in this exact order:

1. `domains/knowledge-work/workflow.md`
1. `domains/knowledge-work/ground-truth.md`
1. `domains/knowledge-work/gates.md`
1. `domains/knowledge-work/reviewers.md`
1. `domains/knowledge-work/deliverables/`
1. `domains/knowledge-work/loop-profile.md`

Registered aliases: `fact check`, `research report`.
Fail closed with `DOMAIN_SLOT_MISSING` or `DOMAIN_ENGINE_REVISION_MISMATCH`
before execution when the Catalog, engine, or any slot is unavailable.
Use only the loaded pack's deliverable, gate, and reviewer routing; this
trigger contains no independent domain policy.
