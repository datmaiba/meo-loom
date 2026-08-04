# Shared agent contract — demo

This is the canonical, agent-neutral contract for this repository. Runtime
entrypoints MUST remain pointers. Use the dat-kit build-loop for feature work.

## Project policy

- Controllers call services; services call repositories.
- Application commands run through containers only.
