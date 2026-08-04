---
name: build-loop
description: >-
  The self-questioning build loop for spec-driven software projects. Invoke on any request like "build phase N", "run the build loop", "continue the project", "preflight", "autopilot", or "delegated build", or any feature work in a repo that has a spec/ directory. Loads the work-loop engine plus the software-dev Domain Pack (six slots: workflow, ground truth, gates, reviewers, deliverables, loop profile) and resumes an interrupted build from the newest handoffs/ file.
---
<!-- GENERATED FROM REGISTRY — DO NOT EDIT; source_revision=domains/1 -->

# build-loop

Resolve domain `software-dev` through the Registry Catalog.
Load engine `work-loop/1` and pack `domains/software-dev`.
Load the six semantic slots in this exact order:

1. `domains/software-dev/workflow.md`
1. `domains/software-dev/ground-truth.md`
1. `domains/software-dev/gates.md`
1. `domains/software-dev/reviewers.md`
1. `domains/software-dev/deliverables/`
1. `domains/software-dev/loop-profile.md`

Registered aliases: `build phase`, `run build loop`.
Fail closed with `DOMAIN_SLOT_MISSING` or `DOMAIN_ENGINE_REVISION_MISMATCH`
before execution when the Catalog, engine, or any slot is unavailable.
Use only the loaded pack's deliverable, gate, and reviewer routing; this
trigger contains no independent domain policy.
