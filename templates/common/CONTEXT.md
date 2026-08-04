# CONTEXT.md — shared language for {{PROJECT_NAME}}

A glossary of this project's domain terms — the ubiquitous language shared by
the team, the code, and the agent. One line per term. Nothing else lives here:
architecture belongs in `spec/02-architecture.md`, corrections in
`lessons-learned/`.

Why: "there's a problem with the *materialization cascade*" beats twenty words
of description — fewer tokens, consistent naming in code, and an agent that
navigates the codebase by the same words the team uses.

Rules for the agent:
- **Read this file at the start of every phase** (build-loop LOAD step).
- **Use these terms verbatim** in code identifiers, commits, and reports.
- **Propose new entries** at the end of a phase for any concept you had to
  describe in a sentence more than once. Keep definitions to one line.
- When a term changes meaning, update the line — don't append a duplicate.

## Glossary

| Term | Meaning (one line) |
|---|---|
| _(example — delete)_ materialization cascade | Making a draft lesson "real": assigning file-system slots to it and every child section |
