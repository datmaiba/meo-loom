# EV-lite governance contract

Status: normative for governed self-evolution in MeoLoom.

EV-lite keeps proposal authority human-controlled. It does not grant an agent
approval, merge, deployment, export, or external-write authority.

## EV1. Proposal record

Each proposal is one UTF-8 Markdown file named
`evolution/PROPOSAL-YYYY-MM-DD-<slug>.md`. The filename date is its creation
date. A proposal contains these state fields exactly once:

```text
Status: proposed | approved | rejected | expired | applied
Approved-by: Dat, <date> | n/a
Implementation: <sha> | n/a
Outcome: pending | measured | unmeasured
```

It also contains:

- **Evidence:** committed evidence references supporting one recurring theme.
- **Change:** an exact touched-path allowlist.
- **Expected outcome:** the observable result the change should produce.
- **Rollback:** the commit or action that restores the prior behavior.
- **Next:** deliberately deferred follow-up work, or `none`.

Evidence must be factual and traceable. A proposal cannot use its own new eval,
review, or output as the evidence that justified creating it.

## EV2. State and authority

`kit-evolve` and other agents may create only `proposed` records. They stop for
Dat's decision and never approve or merge their own proposal.

Dat is the approval authority and final merge control:

- approval sets `Status: approved` and `Approved-by: Dat, <date>`;
- rejection sets `Status: rejected` and records the reason;
- a proposal still `proposed` more than 14 calendar days after its filename
  date must become `expired` before any further processing;
- implementation is limited to the approved allowlist and records its commit
  SHA in `Implementation`;
- the merged authoritative record may be `applied` only when that SHA remains
  reachable through Dat's merge strategy.

Agents may prepare an approved implementation and its merge candidate. Dat's
merge is the final act that makes the applied record authoritative.

## EV3. Outcome and rollback

An applied proposal starts with `Outcome: pending`. After the observation
window, close it as:

- `measured`, with a committed evidence reference and the observed result; or
- `unmeasured`, with the concrete reason measurement was not possible.

Never fabricate a metric or reconstruct missing evidence. Rollback reverts the
recorded implementation commit while preserving proposal history and its
outcome evidence.
