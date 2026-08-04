# Decision 0007: Telemetry v3 public baseline authorization

- Status: accepted
- Date: 2026-08-04
- Owner and approving authority: Dat Mai Ba (platform owner)
- Contract revision: `telemetry-v3/1`
- Contract SHA-256: `f6fff8e4d55a3ff39c9862bfcaab703ff6ab5de7d0656e40b38436561ff3b5f4`
- Effective boundary: MeoLoom 3.0 public clean-root commit

## Decision

Authorize the exact contract hash above, `scripts/telemetry.py`, the
`telemetry/` runtime root, and the three empty committed public corpora:

- `benchmarks/telemetry-v3.jsonl`
- `benchmarks/defects.jsonl`
- `benchmarks/scorecard.jsonl`

The empty files establish the public append-only baseline. This authorization
does not mark any producer active. Producer status remains governed by T3.12
and `telemetry/producers.json`; every producer starts `planned` and requires its
own activation evidence.

Any byte change to the Telemetry v3 contract invalidates this decision's hash
binding and requires a new Class C authorization record. Changes also owe both
independent reviewer classes, full cross-component regression, and rollback
evidence under `platform-contract-policy/1`.
