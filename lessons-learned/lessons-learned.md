# Lessons learned — MeoLoom public baseline

This file begins with the public clean-root repository. Private maintenance
history and source-identifying evidence are intentionally not reproduced here.

- A claim is complete only when its named checks have run and their concrete
  results are recorded.
- Local telemetry, memory, and personal-info tokens remain local by default;
  public tests use synthetic values only.
- A public release is built from an explicit allowlist into a new repository,
  never by changing a private repository's visibility.
- The three committed benchmark corpora are append-only from this public root.
  Corrections append new records; they do not rewrite earlier bytes.
- Current MeoLoom names and legacy migration identifiers are separate concerns:
  retain an old identifier only when a compatibility contract requires it.
- The builder never closes its own review gate. Independent review findings are
  either fixed or declined with a written reason.
