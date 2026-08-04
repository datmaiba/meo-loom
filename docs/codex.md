# Codex support — moved

This document has moved: the Codex host guide and the brownfield migration
reference now live in [`adapters/codex/ADAPTER.md`](../adapters/codex/ADAPTER.md).

You may have been sent here by a `BROWNFIELD_CONTRACT_CONFLICT`,
`LEGACY_CONTRACT`, or migration diagnostic. The short version: never migrate
by hand-editing first — generate the deterministic, read-only plan and review
it before changing any file:

```bash
python "<DAT_KIT_ROOT>/scripts/contract_check.py" --target . --migration-plan
```

The plan exits non-zero while drift remains and never changes the target.
Full guidance (file-ownership classes, preservation-first merge rules,
host-specific behavior): `adapters/codex/ADAPTER.md`.
