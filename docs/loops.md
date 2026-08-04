# Loops in MeoLoom

MeoLoom organizes work along **two orthogonal axes**. This doc explains the model; it is documentation, not an executable spec. [ADR 0001](decisions/0001-open-platform.md) records the current versioned architecture decision, its evidence, migration cost, and explicit conditions to revisit.

## The two axes

**Domain axis — *what kind of work.*** Declared by a Domain Pack under `domains/<domain-id>/` — the six-slot contract: `workflow.md`, `ground-truth.md`, `gates.md`, `reviewers.md`, `deliverables/`, `loop-profile.md` (`docs/contracts/domain-pack.md`). Each pack is bound by a registry descriptor whose generated trigger loads it. Today: `software-dev` (trigger `build-loop`) and `knowledge-work` (trigger `knowledge-work`).

**Loop axis — *how a run is triggered and ended.*** These are Anthropic's four loop types:

| Loop | Triggered by | Ends when |
|---|---|---|
| **Turn** | you send a message | the model self-checks and returns to you |
| **Goal** | you send a message | a measurable gate passes and an independent reviewer approves — the model keeps going until then |
| **Time** | a schedule (cron) | the gate passes on that run |
| **Proactive** | an event | never, until you switch it off |

A single run is one point on the grid: *"run this domain in this loop."*

## The capability ladder — loop capability is earned by gate quality

A domain does not get to pick any loop it likes. It unlocks loops **only to the degree its gate is measurable *and* validated.** A *measurable* gate is not automatically a *correct* one, so a gate must survive the validity check (real worked cases + a stated "this gate can be gamed by X" line + practitioner sign-off) before it counts.

| Loop | Prerequisite | Status in MeoLoom |
|---|---|---|
| **Turn** | none — always available | **available** |
| **Goal** | a measurable **and validated** gate + an independent reviewer | **available** |
| **Time** | an *automated* gate + a genuinely recurring task | **deferred** |
| **Proactive** | stable Goal+Time and low risk — otherwise **notify-only** | **deferred** |

Why the ladder matters: it refuses to automate what cannot be safely automated. A gate that only a human can close (e.g. "does this cited source actually support the claim?") is a **Turn/Goal, human-run** gate — it never authorizes a scheduled or event-driven run. High-risk fields (legal, medical, finance) are additionally capped at notify-only for Proactive.

This is a faithful operationalization of Anthropic's own guidance: most work belongs in Turn; Goal loops only work with measurable done-criteria; Proactive is the easiest to deploy wrong if scaled before it's validated.

## How to choose a loop

- Clear end-point you'll judge yourself, one pass → **Turn.**
- Clear, checkable done-criteria and you want the model to iterate to green → **Goal.**
- The same check needs to run on a cadence → **Time** *(not yet built)*.
- Work should react to events and run unattended → **Proactive** *(not yet built; notify-only first)*.

When in doubt, start at Turn. Move up only when the gate is measurable, validated, and the extra autonomy is worth it.

## Scope boundary

MeoLoom safely supports only domains that **the author, or a supplying practitioner, actually practices.** A Domain Pack encodes a real practitioner's own discipline; it does not let anyone author a domain they cannot personally judge. MeoLoom is a methodology — it does not, by itself, install or run anything on a schedule; the deferred Time/Proactive loops will be opt-in when they land.
