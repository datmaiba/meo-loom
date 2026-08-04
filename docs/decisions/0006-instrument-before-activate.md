# Decision 0006: Instrument before activating producers

- Status: accepted
- Public baseline: MeoLoom 3.0
- Owner and approving authority: Dat Mai Ba (platform owner)

Producer activation requires observable start/resume/end evidence, validation
against the telemetry contract, and a rollback path. Instrumentation may exist
while a producer remains planned; presence of a runtime or corpus does not make
that producer active. Tests must prove that missing or malformed lifecycle
evidence fails closed rather than silently degrading.
