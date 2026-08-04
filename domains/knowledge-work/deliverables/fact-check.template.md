# Fact-check: <document title>

> Brief: <document owner · why it is being checked · claim scope: all / load-bearing only>
> Verdict vocabulary matches `reviewers.md`: a claim is `SOURCED` only when its cited source *states* the claim (G2) with no reliability (G3), staleness (G4), or contradiction (G6) flags.

## Verdict summary
<2–3 sentences: claims checked, how many `SOURCED`, how many failing and why the reader should care.>

## Claim-by-claim

| # | Claim (as written) | Citation | Verdict | Exact problem (if failing) |
|---|---|---|---|---|
| 1 | <verbatim or tight paraphrase> | <source or **none**> | `SOURCED` / failing | <e.g. G2: source mentions the topic but never states the claim> |

## Claims that could not be checked
<Paywalled, dead link, untraceable source — listed with the reason, never silently skipped.>

---
### Verification record (fill before reporting)
- Claims total: <n> · checked: <n> · `SOURCED`: <n> · failing: <n> · unverifiable: <n>
- Every failing claim carries its exact problem above? <y/n>
- Checker independent of the document's author? <y/n — say which was used>

---
### Machine-readable footer (derived from the human verdict — do not auto-compute it)

Fill the block below AFTER the human verdict above is decided. It is a faithful
restatement of that decision for telemetry, never a replacement for it. Rules:
`gate_id` is always `gate:fact`; `verdict` is `sourced` (the machine value for
`SOURCED`) only when `finding_count` is 0 and `failure_classes` is empty;
`return_to_builder` requires a positive `finding_count` and a non-empty,
sorted, duplicate-free `failure_classes` array. `evidence_ref` points to the
numbered finding record above — never copy finding prose into the footer.

Map each failing gate to exactly one closed class: G2 source does not state the
claim / no citation → `unsupported_claim`; G2 source weaker than the claim →
`weaker_than_claim`; G2 source contradicts the claim → `contradiction`; G3
unreliable source → `unreliable_source`; G4 stale source → `stale_source`; G5
inadequate brief coverage → `inadequate_coverage`; G6 two claims contradict in
prose → `prose_contradiction`.

<!-- fact_check_recorded:begin -->
```json
{
  "gate_id": "gate:fact",
  "verdict": "sourced",
  "verdict_source": "human",
  "finding_count": 0,
  "failure_classes": [],
  "evidence_ref": "evidence:fact:example"
}
```
<!-- fact_check_recorded:end -->
