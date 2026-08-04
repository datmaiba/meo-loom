# Decision 0004: Corpus evidence is separate from producer activation

- Status: accepted
- Public baseline: MeoLoom 3.0
- Owner and approving authority: Dat Mai Ba (platform owner)

Committed benchmark corpora are evidence stores, not producer activation
switches. A producer may write only through the validated runtime path and only
when its own lifecycle contract permits it. The public corpora start empty at
the clean root and are byte-append-only from that baseline. This repository has
no inherited historical exception.

Known process-level bypasses that Python alone cannot prevent are handled by
full-history CI, protected public branches, independent review, and the rule
that publication never rewrites the public root.
