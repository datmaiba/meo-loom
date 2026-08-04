"""Engine deletion test (Phase 4f) — the dynamic half of engine depth.

The static half lives in test_engine_manifest.py: a FORBIDDEN-token purity
scan over ENGINE.md. This file proves the same claim by deletion, per plan
§6 Phase 4 exit ("the engine contains no domain-specific policy; deletion
test proves engine depth"): with BOTH registered Domain Packs removed from a
registry fixture — descriptor rows and pack trees alike — the unmodified
engine still stands alone through the unmodified production modules. What
binds a pack to the engine is the pack's DECLARED phase correspondence
(ENGINE.md's kw A→G table and domains/knowledge-work/workflow.md's table are
row-identical after the 4d fix — this test keys on both and pins that they
stay identical), never engine-side knowledge of any pack.
"""
import json
import pathlib
import re
import shutil
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from registry import canonical_relative_path  # noqa: E402
from render import expected_outputs  # noqa: E402
from test_engine_manifest import FORBIDDEN, PHASES  # noqa: E402
from test_registry_catalog import load_ok, registry_fixture, write_json  # noqa: E402

ENGINE_FILES = ("engine/work-loop/ENGINE.md", "engine/work-loop/engine.json")


def fixture_without_packs(tmp_path: pathlib.Path) -> pathlib.Path:
    """Registry fixture with the engine copied in and BOTH packs deleted:
    their descriptor rows leave registry/domains.json and their pack trees
    leave domains/. No other file is touched — especially not the engine."""
    root = registry_fixture(tmp_path)
    shutil.copytree(ROOT / "engine", root / "engine")
    domains_path = root / "registry/domains.json"
    registry = json.loads(domains_path.read_text(encoding="utf-8"))
    removed = [item["pack_location"] for item in registry["domains"]]
    assert sorted(item["domain_id"] for item in registry["domains"]) == [
        "knowledge-work",
        "software-dev",
    ], "deletion test must remove exactly the two cutover packs"
    registry["domains"] = []
    write_json(domains_path, registry)
    for location in removed:
        # guard parity with registry_fixture's copy path (security review,
        # 4f LOW): registry-derived paths are canonicalized before they
        # drive a destructive operation — root / "/abs" would discard root
        shutil.rmtree(root / canonical_relative_path(location))
    return root


def test_engine_stands_alone_with_both_packs_deleted(tmp_path):
    root = fixture_without_packs(tmp_path)
    catalog = load_ok(root)
    assert catalog.domains() == ()
    # the engine composes with zero registered packs: manifest intact,
    # policy file resolves, every phase still declared
    manifest = json.loads((root / "engine/work-loop/engine.json").read_text(encoding="utf-8"))
    assert manifest["engine_revision"] == "work-loop/1"
    assert (root / manifest["policy"]).is_file()
    engine_text = (root / "engine/work-loop/ENGINE.md").read_text(encoding="utf-8")
    for phase in PHASES:
        assert phase in engine_text
    # rendering is not an error without packs: adapter projections (the
    # scaffold manifest) survive; there is simply no domain trigger left
    outputs = expected_outputs(catalog)
    assert not [path for path in outputs if path.startswith("skills/")]


def test_pack_deletion_required_no_engine_edit(tmp_path):
    # Deletion touched registry/domains.json and domains/ only; the engine
    # files the fixture composed with are byte-identical to the repo's. If
    # the engine referenced either pack, the deleted fixture could not have
    # loaded unmodified copies (extension proof, run in reverse).
    root = fixture_without_packs(tmp_path)
    for relative in ENGINE_FILES:
        assert (root / relative).read_bytes() == (ROOT / relative).read_bytes(), relative


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_engine_purity_holds_in_the_deleted_fixture(pattern, tmp_path):
    # The static FORBIDDEN scan re-run against the fixture the packs were
    # deleted from — the engine text that survives deletion carries none of
    # either domain's policy vocabulary.
    root = fixture_without_packs(tmp_path)
    text = (root / "engine/work-loop/ENGINE.md").read_text(encoding="utf-8")
    hits = [
        (i, line.strip())
        for i, line in enumerate(text.splitlines(), 1)
        if re.search(pattern, line, re.IGNORECASE)
    ]
    assert not hits, f"domain policy token {pattern!r} survives deletion: {hits}"


def correspondence_rows(text: str) -> list[tuple[str, str]]:
    """Extract the kw A→G correspondence table: (engine phase, A→G cell)."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*(LOAD|SELF-QUESTION|PLAN|EXECUTE|VERIFY|REVIEW|REPORT|HARVEST)\s*\|(.+)\|\s*$", line)
        if m:
            rows.append((m.group(1), m.group(2).strip()))
    return rows


def test_declared_correspondence_is_the_binding_and_stays_row_identical():
    # The binding between a pack and the engine is the correspondence the
    # pack DECLARES in its workflow slot, keyed on the engine phase sequence.
    # ENGINE.md documents the same convention; the two tables were made
    # row-identical at 4d and the deletion test keys on either — so pin both
    # halves: identical rows, and the engine-phase column is exactly the
    # engine sequence.
    engine_rows = correspondence_rows((ROOT / "engine/work-loop/ENGINE.md").read_text(encoding="utf-8"))
    pack_rows = correspondence_rows(
        (ROOT / "domains/knowledge-work/workflow.md").read_text(encoding="utf-8")
    )
    assert engine_rows, "ENGINE.md correspondence table missing"
    assert engine_rows == pack_rows, "ENGINE.md and workflow.md tables must stay row-identical"
    assert [phase for phase, _ in engine_rows] == PHASES
