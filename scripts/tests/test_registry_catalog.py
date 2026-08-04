import copy
import json
from pathlib import Path
import shutil
import sys


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from registry import Catalog, Diagnostic, canonical_relative_path


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copy_file(source: Path, root: Path) -> None:
    relative = source.relative_to(ROOT)
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def registry_fixture(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "registry", tmp_path / "registry")
    platform = json.loads((ROOT / "registry/platform.json").read_text(encoding="utf-8"))
    adapters = json.loads((ROOT / "registry/adapters.json").read_text(encoding="utf-8"))
    snapshot = json.loads(
        (ROOT / "registry/snapshots/project-contract-1.16.json").read_text(encoding="utf-8")
    )
    paths = {item["path"] for item in platform["version_targets"]}
    for adapter in adapters["adapters"]:
        paths.update(adapter["repository_artifact_paths"])
        paths.update(item["source_template"] for item in adapter["project_artifacts"])
    paths.update(item["source_template"] for item in snapshot["files"])
    for relative in sorted(paths):
        copy_file(ROOT / relative, tmp_path)
    # Active Domain Packs: Catalog.load fails closed (DOMAIN_SLOT_MISSING)
    # unless every declared slot exists under pack_location, so the fixture
    # must carry each active pack's slot tree alongside the registry. The
    # location is validated before touching the filesystem — raw registry
    # data must never drive a copy outside ROOT/tmp_path, even in tests.
    domains = json.loads((ROOT / "registry/domains.json").read_text(encoding="utf-8"))
    for descriptor in domains["domains"]:
        if descriptor["lifecycle"] == "active":
            location = canonical_relative_path(descriptor["pack_location"])
            shutil.copytree(ROOT / location, tmp_path / location)
    return tmp_path


def load_ok(root: Path) -> Catalog:
    loaded = Catalog.load(root)
    assert isinstance(loaded, Catalog), loaded
    return loaded


def codes(result: object) -> list[str]:
    assert isinstance(result, tuple)
    return [item.code for item in result]


def test_current_catalog_is_atomic_and_cutover_state_matches_plan():
    catalog = load_ok(ROOT)
    assert [item["domain_id"] for item in catalog.domains()] == ["knowledge-work", "software-dev"]
    # Phase 4 cutover state: software-dev cut over in slice 4c;
    # knowledge-work cut over in slice 4d.
    assert {item["domain_id"]: item["lifecycle"] for item in catalog.domains()} == {
        "knowledge-work": "active",
        "software-dev": "active",
    }
    # 2.0.0 since slice 5b (D-5b-A: straight bump, no rc suffix — Phase 5
    # Exit requires RC artifact == tagged artifact).
    assert catalog.release_version == "3.0.0"
    assert [item.path for item in catalog.version_targets()] == [
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
    ]
    assert [item.target_relative_path for item in catalog.scaffold_file_plan("greenfield").entries] == [
        ".claude/CLAUDE.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/agent-workflow.md",
    ]


def test_future_bootstrap_fails_before_missing_child_is_read(tmp_path):
    root = registry_fixture(tmp_path)
    platform_path = root / "registry/platform.json"
    platform = json.loads(platform_path.read_text(encoding="utf-8"))
    platform["format_revision"] = 2
    platform["children"][0]["path"] = "registry/does-not-exist.json"
    write_json(platform_path, platform)
    result = Catalog.load(root)
    assert codes(result) == ["REGISTRY_FORMAT_UNSUPPORTED"]


def test_unknown_descriptor_field_has_json_path(tmp_path):
    root = registry_fixture(tmp_path)
    path = root / "registry/domains.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["domains"][0]["surprise"] = True
    write_json(path, value)
    result = Catalog.load(root)
    assert "REGISTRY_UNKNOWN_FIELD" in codes(result)
    diagnostic = next(item for item in result if item.code == "REGISTRY_UNKNOWN_FIELD")
    assert diagnostic.path == "registry/domains.json#/domains/0/surprise"


def test_mixed_code_and_child_format_fails_atomically(tmp_path):
    root = registry_fixture(tmp_path)
    path = root / "registry/adapters.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["format_revision"] = 2
    write_json(path, value)
    result = Catalog.load(root)
    assert "REGISTRY_ATOMIC_UPGRADE_REQUIRED" in codes(result)
    assert not isinstance(result, Catalog)


def test_new_governed_product_path_without_component_is_orphaned(tmp_path):
    root = registry_fixture(tmp_path)
    product = root / "docs/new-area/product.bin"
    product.parent.mkdir(parents=True)
    product.write_bytes(b"product")
    # Load must still succeed: a stray file must not brick every Catalog
    # consumer. The governed-inventory sweep is a validation-time concern.
    catalog = load_ok(root)
    result = catalog.validate_governed_inventory()
    assert "EVOLUTION_ORPHAN_PATH" in codes(result)
    assert any(item.path == "docs/new-area/product.bin" for item in result)


def test_phase6b_telemetry_paths_resolve_to_one_narrow_owner():
    catalog = load_ok(ROOT)
    for path in (
        "telemetry",
        "telemetry/schema-v3.json",
        "telemetry/events.jsonl",
        "scripts/telemetry.py",
    ):
        explanation = catalog.explain_path(path)
        assert isinstance(explanation, dict), explanation
        assert explanation["component_id"] == "telemetry-v3-runtime"
        assert explanation["owner"] == "maintainers"
        assert explanation["governance_class"] == "B"
        assert explanation["policy_revision"] == "maintainer-policy/1"


def test_phase6b_telemetry_admission_does_not_hide_boundary_orphans():
    catalog = load_ok(ROOT)
    for path in ("telemetry-v3/events.jsonl", "scripts/telemetry.py.bak"):
        explanation = catalog.explain_path(path)
        assert isinstance(explanation, Diagnostic), explanation
        assert explanation.code == "EVOLUTION_ORPHAN_PATH"


def test_phase6b_telemetry_admission_fails_closed_when_missing_or_ambiguous(tmp_path):
    root = registry_fixture(tmp_path)
    evolution_path = root / "registry/evolution.json"
    evolution = json.loads(evolution_path.read_text(encoding="utf-8"))
    component = next(
        item for item in evolution["component_classes"]
        if item["component_id"] == "telemetry-v3-runtime"
    )

    evolution["component_classes"].remove(component)
    write_json(evolution_path, evolution)
    catalog = load_ok(root)
    missing = catalog.explain_path("telemetry/events.jsonl")
    assert isinstance(missing, Diagnostic), missing
    assert missing.code == "EVOLUTION_ORPHAN_PATH"

    overlapping = copy.deepcopy(component)
    overlapping["component_id"] = "telemetry-v3-overlap-fixture"
    evolution["component_classes"].extend((component, overlapping))
    write_json(evolution_path, evolution)
    catalog = load_ok(root)
    ambiguous = catalog.explain_path("telemetry/events.jsonl")
    assert isinstance(ambiguous, Diagnostic), ambiguous
    assert ambiguous.code == "EVOLUTION_OWNERSHIP_AMBIGUOUS"


def test_catalog_results_are_defensive_copies():
    catalog = load_ok(ROOT)
    domains = catalog.domains()
    domains[0]["trigger"]["name"] = "mutated"
    assert catalog.domains()[0]["trigger"]["name"] == "knowledge-work"


# --- Slice 5a: historical snapshots are records, not scaffold sources ------
# Historical snapshot rule: the immutable 1.16 snapshot
# records what real 1.16 projects have on disk; only the canonical revision's
# snapshot is a scaffold source and live-verified against template bytes.
# Before this change, the atomic templates flip was impossible: two snapshots
# listing the same targets raised REGISTRY_PATH_COLLISION, and the 1.16 rows
# raised REGISTRY_SNAPSHOT_HASH_MISMATCH against the flipped live template.


def test_fileplan_scaffold_rows_come_only_from_the_canonical_snapshot():
    catalog = load_ok(ROOT)
    plan = catalog.scaffold_file_plan("greenfield")
    assert [item.target_relative_path for item in plan.entries] == [
        ".claude/CLAUDE.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/agent-workflow.md",
    ]
    assert {item.project_contract_revision for item in plan.entries} == {"MeoLoom 3.0"}


def test_historical_snapshot_is_a_record_not_live_verified(tmp_path):
    # The live template carries the 2.0 marker; the 1.16 snapshot's hashes
    # intentionally no longer match it. Catalog.load must stay green and the
    # 1.16 snapshot must stay loaded for migration recognition.
    root = registry_fixture(tmp_path)
    catalog = load_ok(root)
    model = catalog.revision_model()
    assert "dat-kit 1.16.0" in model["snapshots"]
    assert "dat-kit 2.0" in model["snapshots"]


def test_historical_snapshot_descriptor_disagreement_still_fails_closed(tmp_path):
    # Internal consistency stays enforced for historical snapshots: the
    # descriptor's static_template_hashes and the snapshot rows must agree.
    root = registry_fixture(tmp_path)
    snapshot_path = root / "registry/snapshots/project-contract-1.16.json"
    value = json.loads(snapshot_path.read_text(encoding="utf-8"))
    value["files"][0]["expected_content_hash"] = "0" * 64
    write_json(snapshot_path, value)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "REGISTRY_SNAPSHOT_HASH_MISMATCH" in codes(result)

def test_canonical_snapshot_still_verifies_live_template_bytes(tmp_path):
    root = registry_fixture(tmp_path)
    (root / "templates/common/AGENTS.md").write_text(
        "# tampered\n\n**Canonical contract revision:** dat-kit 2.0\n", encoding="utf-8"
    )
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "REGISTRY_SNAPSHOT_HASH_MISMATCH" in codes(result)
