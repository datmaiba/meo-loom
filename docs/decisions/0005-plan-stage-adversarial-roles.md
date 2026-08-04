# Decision 0005: Plan-stage adversarial roles run in parallel and blind

- Status: accepted
- Public baseline: MeoLoom 3.0
- Owner and approving authority: Dat Mai Ba (platform owner)

`prior-art-auditor` and `premise-challenger` run at PLAN before drafting and
always before a third revision. They run in parallel, do not see one another's
findings, and never close a gate. Findings are fixed or explicitly declined
with a reason. Their purpose is to test whether work already exists and whether
the requested goal is well-formed; fidelity review remains a separate role.

Revisit when either role repeatedly returns no substantive finding on
non-trivial plans, when the third-revision trigger is missed, or when measured
cost exceeds the plan-review passes the roles replace.
