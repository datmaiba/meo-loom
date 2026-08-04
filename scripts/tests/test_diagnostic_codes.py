"""R8 mechanical enforcement: emitted diagnostic codes == documented codes.

The registry contract (docs/contracts/registry.md R8) declares diagnostic
codes as stable API. This test extracts every code the registry/projection
implementation can emit and compares it, both directions, with the codes
documented in the contract. A drift in either direction is a contract
violation, not a style issue (code-review finding M2, Phase 1B).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCES = ("scripts/registry.py", "scripts/render.py")
CONTRACT = "docs/contracts/registry.md"

# Codes defined by the contract but owned by the Phase 3 migration machinery.
RESERVED = {
    "CONTRACT_MIGRATION_REQUIRED",
    "CONTRACT_UNSUPPORTED_REVISION",
    "CONTRACT_PARTIAL_MIGRATION",
    "CONTRACT_MIGRATION_CONFLICT",
    "FILE_PLAN_PRECONDITION_FAILED",
    "FILE_PLAN_APPROVAL_REQUIRED",
}

_EMIT = re.compile(r'(?:self\.add\(|Diagnostic\()\s*\n?\s*"([A-Z][A-Z0-9_]{3,})"')
_CONDITIONAL = re.compile(r'"([A-Z][A-Z0-9_]{3,})" if [^\n]+ else "([A-Z][A-Z0-9_]{3,})"')
_DOCUMENTED = re.compile(r"`([A-Z][A-Z0-9_]{3,})`")


def emitted_codes() -> set[str]:
    codes: set[str] = set()
    for relative in SOURCES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        codes.update(_EMIT.findall(text))
        for pair in _CONDITIONAL.findall(text):
            codes.update(pair)
    return codes


def documented_codes() -> set[str]:
    text = (ROOT / CONTRACT).read_text(encoding="utf-8")
    section = text.split("## R8", 1)[1].split("## R9", 1)[0]
    return set(_DOCUMENTED.findall(section))


def test_every_emitted_code_is_documented():
    undocumented = emitted_codes() - documented_codes()
    assert not undocumented, f"emitted but not in R8: {sorted(undocumented)}"


def test_every_documented_code_is_emitted_or_reserved():
    dead = documented_codes() - emitted_codes() - RESERVED
    assert not dead, f"documented in R8 but never emitted: {sorted(dead)}"


def test_reserved_codes_are_not_emitted_by_the_registry():
    early = emitted_codes() & RESERVED
    assert not early, f"reserved Phase 3 codes emitted by Phase 1 code: {sorted(early)}"
