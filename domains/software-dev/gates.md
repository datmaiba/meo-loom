# software-dev — gates

Done-criteria for a software-dev phase. Each gate carries worked cases and
the way it can be gamed (per the gate-validity rule in `docs/loops.md`). A
phase without ALL of these green is NOT done — no exceptions, in any mode.

## SW-G1 — Project gates green · *automatable* · closer: qa-agent

Every quality-gate command the project's canonical `AGENTS.md` contract
declares exits green, run **exactly as written there** (if the project says
docker-only, never fall back to host binaries).

- **Pass:** `docker compose exec app pest` → 24/24 ✓, run verbatim from the
  contract.
- **Fail:** substituting `php artisan test` on the host because docker "was
  slow" — a different command proves nothing about the declared gate.
- **Gamed by:** a no-op gate command that exits green regardless — a
  type-check once stayed green for six phases while dozens of real errors
  accumulated. Countermeasure: the engine's red-green proof (VERIFY) applied
  to every added or changed gate command. **Evidence:** the red run's output
  captured alongside the green.
- **Evidence contract:** verbatim per-gate results in the phase report
  ("pest 24/24 ✓, tsc ✓") — never "everything works".

## SW-G2 — Working demo · **human-run** · closer: builder walks, user verifies

The phase's demo step from the build-phases spec is actually walked, not
described.

- **Pass:** each demo step executed with its observed result stated;
  browser-only steps the user must perform are listed and deferred
  explicitly.
- **Fail:** "the endpoint should now return the new field" — prediction, not
  demonstration.
- **Gamed by:** narrating the expected behavior instead of exercising it.
  Countermeasure: the report names what was actually run and seen, step by
  step.

## SW-G3 — Independent review chain · **human-run** · load-bearing · closer: reviewers per `reviewers.md`

`qa-agent` reports PHASE DONE, `code-reviewer` reports APPROVE, and
`security-reviewer` reports APPROVE whenever its trigger surfaces were
touched (see `reviewers.md`). For every added or changed safety/integrity
control, the QA record must also prove the control at its sanctioned boundary,
attribute the result to that control, and apply the engine's VERIFY red-green
rule to that control before `PHASE DONE`.

- **Pass:** verdicts on record for the phase's actual diff, in sequence, plus
  one control-proof triplet for each qualifying control:
  **Boundary:** exercise the threat through the named sanctioned public entry
  point, including an alternate sanctioned route when multiple routes reach
  the protected effect; **Attribution:** assert the exact result or diagnostic
  that distinguishes the intended control from an earlier, ambient, or
  unrelated control; **Mutation:** apply the engine's VERIFY red-green rule to
  the intended control. Worked case: both identity guards moved to the join,
  then the route that was not originally in mind was attacked successfully.
- **Fail:** self-review, a verdict on a stale diff, or a guard placed in a
  private helper when the finding named `producer_writer` as the public API;
  the public path still accepted the forbidden event while the helper test
  stayed green.
- **Gamed by:** shrinking the dispatch scope so the reviewer never sees the
  risky files; re-running a full review until one round misses the finding; or
  mutating a control the attack never reaches, so the red comes from an
  unrelated failure. Countermeasure: the dispatch prompt names the complete
  changed-file list, re-reviews are findings-scoped against the new diff, and
  Attribution identifies the control that produced the observed result.
- **Ceiling:** "APPROVE" is reviewer judgement, not a mechanical signal —
  **this gate caps the domain at Goal** (see `loop-profile.md`).
