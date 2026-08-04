"""Format-freeze pin (Phase 5 slice 5b, decision D-5b-B).

Pins the frozen registry/contract format values for the dat-kit 2.0.0 release
train, per the freeze statement in docs/contracts/registry.md R9. Any drift in
these values after the freeze is a format change and must reopen the release
train — this test makes that drift loud.

Amending the freeze requires updating BOTH this test and the R9 statement in
the same commit (the docs-anchor test below enforces the coupling).
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

FROZEN_FORMAT_REVISION = 1
FROZEN_CANONICAL_REVISION = "MeoLoom 3.0"
FROZEN_GREEN_REVISIONS = ["MeoLoom 3.0"]
FROZEN_MIGRATABLE_SOURCES = ["dat-kit 2.0", "dat-kit 1.16.0"]

REGISTRY_FILES = [
    "registry/platform.json",
    "registry/domains.json",
    "registry/adapters.json",
    "registry/evolution.json",
    "registry/snapshots/project-contract-1.16.json",
    "registry/snapshots/project-contract-2.0.json",
    "registry/snapshots/project-contract-3.0.json",
]


def _load(rel_path):
    return json.loads((ROOT / rel_path).read_text(encoding="utf-8"))


def test_format_revision_is_frozen_at_1_everywhere():
    for rel_path in REGISTRY_FILES:
        payload = _load(rel_path)
        assert payload["format_revision"] == FROZEN_FORMAT_REVISION, (
            f"{rel_path}: format_revision {payload['format_revision']!r} != "
            f"{FROZEN_FORMAT_REVISION} — the 2.0.0 format freeze (registry.md "
            "R9) forbids format changes; a bump reopens the release train."
        )


def test_contract_revision_state_is_frozen():
    platform = _load("registry/platform.json")
    assert platform["canonical_revision"] == FROZEN_CANONICAL_REVISION
    assert platform["green_revisions"] == FROZEN_GREEN_REVISIONS
    assert platform["migratable_source_revisions"] == FROZEN_MIGRATABLE_SOURCES


def test_child_revisions_match_bootstrap_rows():
    platform = _load("registry/platform.json")
    for child in platform["children"]:
        payload = _load(child["path"])
        assert payload["registry_revision"] == child["revision"], (
            f"{child['path']}: registry_revision "
            f"{payload['registry_revision']!r} != bootstrap row "
            f"{child['revision']!r}"
        )


def test_freeze_statement_anchored_in_registry_contract():
    """Docs half of D-5b-B: removing/renaming the R9 freeze statement (or this
    file) without the other is a coupling break — fail loudly."""
    contract = (ROOT / "docs" / "contracts" / "registry.md").read_text(
        encoding="utf-8"
    )
    assert "Format freeze — MeoLoom 3.0.0 successor train" in contract
    assert "scripts/tests/test_format_freeze.py" in contract
