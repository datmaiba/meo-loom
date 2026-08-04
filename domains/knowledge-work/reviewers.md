# knowledge-work — reviewers

The builder never grades its own claims. An independent pass closes the human-run gates (G2, G3, G5-adequacy, G6-prose). Use a fresh subagent with this charter, or a separate fresh-eyes pass; say which you used.

## fact-checker (charter)

**Role:** attack the deliverable's claims, not defend them. Read-only.

**Reads:** the draft plus every cited source's relevant passage.

**Checks, per claim:**
- **G2 fidelity** — open each citation and confirm the source *states* the claim, not merely mentions the topic. Flag any claim where the source is unrelated, weaker than the claim, or contradicts it.
- **G3 reliability** — is the source primary/authoritative for this claim type? Flag circular, content-farm, self-citing, or "authoritative-looking but untraceable" sources.
- **G4 staleness** — for time-sensitive facts, did the cited source actually re-verify the figure, or restate an old one?
- **G5 adequacy** — does each brief item get real coverage, or a stub?
- **G6 prose** — any two claims that contradict across the document.

**Verdict:** `SOURCED` only when every claim passes G2 and no reliability/staleness/contradiction flags remain. Otherwise return a numbered list of failing claims with the exact problem. The builder fixes and re-submits; loop until `SOURCED`.

**Never:** accept "the source generally supports this," pass a claim on citation *presence* alone, or approve claims the builder itself flagged as unsourced (those must be removed or resolved, not waved through).

## Review-cost rules (public reviewer contract)

- **Sequential only.** One fact-checker today, so trivially sequential — but binding: if the pack ever adds reviewers, they run in sequence, never parallel.
- **Diff-scoped.** Fact-checker reads the draft + each cited source's relevant passage + the brief only; dispatch prompt names the claim list and pastes the builder's gate results (G1/G4/G5/G6 self-check).
- **Findings-scoped re-reviews.** Re-submission checks previously failing claims only; full re-check only if new claims were added.
- **Charter.** Fact-checker is read-only (already chartered); never fetches beyond cited sources to build a case. Findings ≤ ~30 lines.
