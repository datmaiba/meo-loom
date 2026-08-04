"""Repository-side Host Adapter conformance.

Proves, per registered adapter: the pointer chain targets AGENTS.md through a
declared mechanism; pointer templates carry no policy; every adapter ships an
ADAPTER.md package; rollback owns only adapter-owned paths (never the
canonical contract); repo_only artifacts stay out of emission plans; and a
retired artifact never reaches greenfield either.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from registry import Catalog
from test_registry_catalog import load_ok, registry_fixture, write_json

# Policy-block detector: a thin pointer must not smuggle instruction policy.
POLICY_BLOCK = re.compile(r"(?im)^##|\bMUST\b|quality gates?|plan gate|autopilot|severity")

CANONICAL_OWNED = {"AGENTS.md_policy_owner"}  # marker; real check below


def adapters():
    return load_ok(ROOT).adapters()


def test_every_adapter_ships_an_adapter_package():
    for adapter in adapters():
        package = ROOT / "adapters" / adapter["adapter_id"] / "ADAPTER.md"
        assert package.is_file(), package
        assert f"adapters/{adapter['adapter_id']}/ADAPTER.md" in adapter["repository_artifact_paths"]


def test_pointer_chain_targets_agents_md_only():
    for adapter in adapters():
        assert adapter["pointer_semantics"]["canonical_target"] == "AGENTS.md", adapter["adapter_id"]
        assert adapter["policy_prohibition"]["canonical_owner"] == "AGENTS.md"


def test_pointer_templates_reference_agents_and_carry_no_policy():
    for adapter in adapters():
        for artifact in adapter["project_artifacts"]:
            text = (ROOT / artifact["source_template"]).read_text(encoding="utf-8")
            assert "AGENTS.md" in text, artifact["source_template"]
            assert not POLICY_BLOCK.search(text), (
                f"policy block smuggled into thin pointer {artifact['source_template']}"
            )
            assert len(text.splitlines()) <= 12, "pointer templates stay thin"


def test_rollback_never_claims_the_canonical_contract():
    canonical = {"AGENTS.md", "docs/agent-working-rules.md", "docs/agent-workflow.md", "CONTEXT.md"}
    for adapter in adapters():
        owned = set(adapter["rollback"]["owned_project_paths"])
        assert not (owned & canonical), (adapter["adapter_id"], owned & canonical)


def test_native_adapters_emit_no_pointer_artifacts():
    for adapter in adapters():
        if adapter["pointer_semantics"]["mechanism"] == "native":
            active = [
                item for item in adapter["project_artifacts"]
                if item["artifact_lifecycle"] == "scaffold_active"
            ]
            assert not active, adapter["adapter_id"]


def test_repo_only_artifacts_stay_out_of_greenfield_and_manifest_materialization():
    catalog = load_ok(ROOT)
    greenfield_targets = {
        entry.target_relative_path for entry in catalog.scaffold_file_plan("greenfield").entries
    }
    assert "GEMINI.md" not in greenfield_targets
    # The committed TSV may report the row, but only scaffold_active rows
    # materialize (init.sh) — assert the TSV row, if present, is repo_only.
    manifest = (ROOT / "templates/common/.meoloom-files.tsv").read_text(encoding="utf-8")
    for line in manifest.splitlines()[1:]:
        fields = line.split("\t")
        if fields[1] == "GEMINI.md":
            assert fields[5] == "repo_only"


def test_retired_artifact_never_reaches_greenfield(tmp_path):
    root = registry_fixture(tmp_path)
    path = root / "registry/adapters.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    adapter = value["adapters"][0]
    retired_targets = set()
    for artifact in adapter["project_artifacts"]:
        artifact["artifact_lifecycle"] = "retired"
        retired_targets.add(artifact["target_relative_path"])
    # descriptor lifecycle mirrors the minimum artifact lifecycle
    adapter["lifecycle"] = "retired"
    write_json(path, value)
    loaded = Catalog.load(root)
    assert isinstance(loaded, Catalog), loaded  # must load, not skip vacuously
    assert retired_targets, "fixture adapter must own at least one artifact"
    greenfield = {
        entry.target_relative_path
        for entry in loaded.scaffold_file_plan("greenfield").entries
    }
    assert not (retired_targets & greenfield)


def test_official_facts_have_dates_and_https_sources():
    for adapter in adapters():
        assert adapter["official_facts"], f"{adapter['adapter_id']} has no dated facts"
        for fact in adapter["official_facts"]:
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact["verified_on"])
            assert fact["source_url"].startswith("https://")
            assert fact["reverify_before"].strip()
