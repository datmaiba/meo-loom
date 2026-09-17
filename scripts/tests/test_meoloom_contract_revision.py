"""MeoLoom 3.0 contract transition pins.

The registry format stays at revision 1.  ``dat-kit`` remains only where it is
a frozen legacy revision or wire-level ownership identifier; it is no longer
the current product revision.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "registry" / "platform.json"
sys.path.insert(0, str(ROOT / "scripts"))

import contract_check as cc

CURRENT = "MeoLoom 3.0"
LEGACY_V2 = "dat-kit 2.0"
LEGACY_V116 = "dat-kit 1.16.0"


def platform() -> dict[str, object]:
    return json.loads(PLATFORM.read_text(encoding="utf-8"))


def write_agents(target: Path, *revisions: str) -> None:
    markers = "\n".join(
        f"**Canonical contract revision:** {revision}" for revision in revisions
    )
    (target / "AGENTS.md").write_text(
        "# Agent contract — demo\n\n"
        f"{markers}\n\n"
        "This file is the single canonical instruction entrypoint.\n",
        encoding="utf-8",
    )
    (target / "CLAUDE.md").write_text(
        (ROOT / "templates" / "common" / "CLAUDE.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def codes(report: cc.Report) -> set[str]:
    return {item.code for item in report.diagnostics}


def test_meoloom_is_the_only_current_revision() -> None:
    payload = platform()
    assert payload["format_revision"] == 1
    assert payload["release_version"] == "3.0.1"
    assert payload["canonical_revision"] == CURRENT
    assert payload["green_revisions"] == [CURRENT]
    assert payload["migratable_source_revisions"] == [LEGACY_V2, LEGACY_V116]


def test_current_and_legacy_descriptors_are_all_explicit() -> None:
    payload = platform()
    descriptors = {
        item["revision"]: item for item in payload["revision_descriptors"]
    }
    assert set(descriptors) == {CURRENT, LEGACY_V2, LEGACY_V116}
    assert descriptors[CURRENT]["snapshot_provenance"] == (
        "registry/snapshots/project-contract-3.0.json"
    )
    assert descriptors[LEGACY_V2]["snapshot_provenance"] == (
        "registry/snapshots/project-contract-2.0.json"
    )
    assert descriptors[LEGACY_V116]["snapshot_provenance"] == (
        "registry/snapshots/project-contract-1.16.json"
    )


def test_each_legacy_revision_has_a_direct_meoloom_edge() -> None:
    edges = {
        (item["source_revision"], item["target_revision"]): item["status"]
        for item in platform()["migration_edges"]
    }
    assert edges[(LEGACY_V2, CURRENT)] in {"planned", "available"}
    assert edges[(LEGACY_V116, CURRENT)] in {"planned", "available"}


def test_frozen_legacy_snapshot_identities_do_not_move() -> None:
    expected = {
        "registry/snapshots/project-contract-2.0.json": (
            LEGACY_V2,
            {
                "AGENTS.md": "52a92fdafc39d83145dcca540039ec8e48f309a280a9b7cdd03a099fb96c908f",
                "docs/agent-workflow.md": "9b0e1d235a59db64c1e414d624487d779fe8cdc33d4c7e408943edf4e266df53",
            },
        ),
        "registry/snapshots/project-contract-1.16.json": (
            LEGACY_V116,
            {
                "AGENTS.md": "e4ad841c8eb2039aad551138c328135e6afa08abec256f7d2959d0611726b0e4",
                "docs/agent-workflow.md": "9b0e1d235a59db64c1e414d624487d779fe8cdc33d4c7e408943edf4e266df53",
            },
        ),
    }
    for relative, (revision, hashes) in expected.items():
        snapshot = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        assert snapshot["project_contract_revision"] == revision
        assert {
            item["target_relative_path"]: item["expected_content_hash"]
            for item in snapshot["files"]
        } == hashes


def test_clean_meoloom_contract_is_green(tmp_path: Path) -> None:
    write_agents(tmp_path, CURRENT)
    report = cc.check_target(tmp_path)
    assert report.revision_state == "green"
    assert not report.diagnostics, [item.code for item in report.diagnostics]


def test_dat_kit_v2_is_recognized_as_a_migration_source(tmp_path: Path) -> None:
    write_agents(tmp_path, LEGACY_V2)
    report = cc.check_target(tmp_path)
    assert report.revision_state == "migration-source"
    assert "CONTRACT_MIGRATION_REQUIRED" in codes(report)


def test_two_legacy_markers_fail_closed_as_partial(tmp_path: Path) -> None:
    write_agents(tmp_path, LEGACY_V2, LEGACY_V116)
    report = cc.check_target(tmp_path)
    assert report.revision_state == "partial"
    assert "CONTRACT_PARTIAL_MIGRATION" in codes(report)


def test_unknown_meoloom_revision_is_unsupported(tmp_path: Path) -> None:
    write_agents(tmp_path, "MeoLoom 9.9")
    report = cc.check_target(tmp_path)
    assert report.revision_state == "unsupported"
    assert "CONTRACT_UNSUPPORTED_REVISION" in codes(report)
