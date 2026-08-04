# knowledge-work — gates

Done-criteria for a knowledge-work deliverable. Each gate carries its worked cases and the way it can be gamed (per the gate-validity rule, `docs/contracts/domain-pack.md` DP3.3). A gate marked **human-run** cannot be closed mechanically and caps the task at Goal.

> Seeded from the Phase 0 paper validity check, which the practitioner (a dev who does research/writing) signed off. Verdict: valid, non-gameable gates exist for this domain; the load-bearing one is human-run.

## G1 — Citation presence · *automatable*
Every non-trivial factual claim carries an inline citation to a locatable source.
- **Pass:** "The standard VAT rate is 10% [Circular 219/2013/TT-BTC]." — marker present.
- **Fail:** "Most startups fail in year one." — no citation.
- **Gamed by:** a citation marker that points nowhere or to an unrelated source — G1 passes on *presence* alone. Necessary but weak; always run with G2.
- **Ceiling unlocked:** Goal (a linter/reviewer can flag uncited claims).

## G2 — Source–claim fidelity · **human-run** · load-bearing
Each cited source actually *supports* the specific claim attached to it.
- **Pass:** claim "the standard rate is 10%" cited to the article that states 10%.
- **Fail:** same claim cited to an article about filing deadlines.
- **Gamed by:** citing a long, plausible source that *mentions* the topic but never states the claim, betting the reviewer won't read it.
- **Ceiling unlocked:** Goal, human-run — cannot be automated. **This gate sets the domain ceiling.**

## G3 — Source reliability · *mostly human-run*
Sources are primary/authoritative, not circular, content-farm, or self-citing.
- **Pass:** a tax rate cited to the government circular.
- **Fail:** a tax rate cited to a blog quoting an unnamed "expert."
- **Gamed by:** a source that merely *looks* authoritative (official-sounding name, stale gov mirror).
- **Ceiling unlocked:** Goal, human-run (partial automation via allow/deny lists).

## G4 — Currency · *date automatable, staleness human-run*
Every time-sensitive fact is verified current, with a source date inside the agreed window.
- **Pass:** "As of 2026, the rate is X [source dated 2026]."
- **Fail:** a 2019 price presented as current.
- **Gamed by:** a fresh-dated source that *restates* an old figure without re-verifying — date looks current, fact is stale.
- **Ceiling unlocked:** Goal now; a Time-based re-check of a living document is a *future* candidate, but only after G2/G3 are trusted.

## G5 — Brief coverage · *presence automatable, adequacy human-run*
The deliverable answers every item in the agreed brief/outline.
- **Pass:** brief asked for 3 competitors; all 3 covered in depth.
- **Fail:** only 2 of 3 covered.
- **Gamed by:** a one-line stub for the missing item to tick the box without real coverage.
- **Ceiling unlocked:** Goal.

## G6 — Internal consistency · *numbers automatable, prose human-run*
No two claims contradict; every number reconciles with its source figure.
- **Pass:** the summary total equals the sum of the parts in the table.
- **Fail:** intro says "revenue grew," the body shows a decline.
- **Gamed by:** hard to game numerically (recompute catches it); prose contradictions can hide across a long document.
- **Ceiling unlocked:** Goal.

## Domain ceiling

**Goal.** The structural gates (G1, G4-date, G5-presence, G6-numbers) are automatable; the semantic gates (G2, G3, G4-staleness, G5-adequacy, G6-prose) are human-run. Because G2 — the gate that actually protects quality — is inherently human, no knowledge-work task safely unlocks Time or Proactive. Correct by design.
