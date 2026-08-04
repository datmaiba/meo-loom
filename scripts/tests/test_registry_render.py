import copy
import json
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from render import MANIFEST_PATH, check_outputs, expected_outputs, write_outputs
from test_registry_catalog import load_ok, registry_fixture, write_json


def add_synthetic_domain(root: Path) -> None:
    domains_path = root / "registry/domains.json"
    domains = json.loads(domains_path.read_text(encoding="utf-8"))
    domains["domains"].append(
        {
            "domain_id": "synthetic-domain",
            "contract_revision": "domain-pack/1",
            "lifecycle": "active",
            "pack_location": "skills/synthetic-pack",
            "trigger": {
                "name": "synthetic-domain",
                "description": "Run the synthetic registry extension proof.",
                "aliases": ["synthetic proof"],
            },
            "required_engine_revision": "work-loop/1",
            "gate_authority_ref": "software-dev-reviewer",
            "loop_ceiling": "Goal",
            "evolution_profile_ref": "maintainer-policy",
        }
    )
    write_json(domains_path, domains)
    pack = root / "skills/synthetic-pack"
    pack.mkdir(parents=True)
    for filename in ("workflow.md", "ground-truth.md", "gates.md", "reviewers.md", "loop-profile.md"):
        (pack / filename).write_text(f"# {filename}\n", encoding="utf-8")
    deliverables = pack / "deliverables"
    deliverables.mkdir()
    (deliverables / "output.md").write_text("# output\n", encoding="utf-8")

    evolution_path = root / "registry/evolution.json"
    evolution = json.loads(evolution_path.read_text(encoding="utf-8"))
    evolution["component_classes"].append(
        {
            "component_id": "synthetic-domain-fixture",
            "path_globs": ["skills/synthetic-domain/**", "skills/synthetic-pack/**"],
            "owner": "maintainers",
            "governance_class": "B",
            "policy_ref": "maintainer-policy",
        }
    )
    write_json(evolution_path, evolution)


def add_synthetic_adapter(root: Path) -> None:
    template = root / "adapters/synthetic/SYNTHETIC.md.tpl"
    template.parent.mkdir(parents=True)
    template.write_text("Read AGENTS.md.\n", encoding="utf-8")
    adapters_path = root / "registry/adapters.json"
    adapters = json.loads(adapters_path.read_text(encoding="utf-8"))
    synthetic = copy.deepcopy(next(item for item in adapters["adapters"] if item["adapter_id"] == "codex"))
    synthetic.update(
        {
            "adapter_id": "synthetic",
            "aliases": ["synthetic-host"],
            "host": "Synthetic Host",
            "repository_artifact_paths": ["adapters/synthetic/SYNTHETIC.md.tpl"],
            "project_artifacts": [
                {
                    "source_template": "adapters/synthetic/SYNTHETIC.md.tpl",
                    "target_relative_path": "SYNTHETIC.md",
                    "ownership_class": "adapter",
                    "materialization_action": "render-pointer",
                    "artifact_lifecycle": "repo_only",
                    "project_contract_revision": "dat-kit 2.0",
                    "expected_content_hash": None,
                    "precondition": "target-absent",
                }
            ],
            "conformance_fixtures": ["ADAPTER-SYNTHETIC-01"],
            "smoke_command": ["synthetic", "--smoke"],
            "rollback": {
                "owned_repository_paths": ["adapters/synthetic/SYNTHETIC.md.tpl"],
                "owned_project_paths": ["SYNTHETIC.md"],
                "removal_precondition": "exact-adapter-owned-hash",
                "verification_commands": [["synthetic", "--version"]],
            },
        }
    )
    adapters["adapters"].append(synthetic)
    write_json(adapters_path, adapters)

    evolution_path = root / "registry/evolution.json"
    evolution = json.loads(evolution_path.read_text(encoding="utf-8"))
    if not any(item["path"] == "adapters" for item in evolution["governed_roots"]):
        evolution["governed_roots"].append({"path": "adapters", "owner": "host-adapter-platform"})
    evolution["component_classes"].append(
        {
            "component_id": "synthetic-adapter-fixture",
            "path_globs": ["adapters/synthetic/**"],
            "owner": "host-adapter-platform",
            "governance_class": "B",
            "policy_ref": "host-adapter-policy",
        }
    )
    write_json(evolution_path, evolution)


def test_synthetic_registry_only_domain_renders_without_python_change(tmp_path):
    root = registry_fixture(tmp_path)
    add_synthetic_domain(root)
    catalog = load_ok(root)
    outputs = expected_outputs(catalog)
    trigger = "skills/synthetic-domain/SKILL.md"
    assert trigger in outputs
    assert b"skills/synthetic-pack/workflow.md" in outputs[trigger]
    assert b"source_revision=domains/1" in outputs[trigger]


def test_synthetic_adapter_template_reaches_manifest_without_shell_edit(tmp_path):
    root = registry_fixture(tmp_path)
    add_synthetic_adapter(root)
    catalog = load_ok(root)
    manifest = expected_outputs(catalog)[MANIFEST_PATH]
    assert (
        b"adapters/synthetic/SYNTHETIC.md.tpl\tSYNTHETIC.md\tadapter\trender-pointer"
        b"\tdat-kit 2.0\trepo_only\n"
    ) in manifest


def test_missing_descriptor_owned_projection_fails_byte_exact_check(tmp_path):
    root = registry_fixture(tmp_path)
    add_synthetic_domain(root)
    catalog = load_ok(root)
    outputs = expected_outputs(catalog)
    write_outputs(root, outputs)
    trigger = root / "skills/synthetic-domain/SKILL.md"
    trigger.unlink()
    diagnostics = check_outputs(root, outputs)
    assert any(item.code == "PROJECTION_MISSING" and item.path == "skills/synthetic-domain/SKILL.md" for item in diagnostics)


def test_projection_check_is_byte_exact_and_never_repairs(tmp_path):
    root = registry_fixture(tmp_path)
    catalog = load_ok(root)
    outputs = expected_outputs(catalog)
    write_outputs(root, outputs)
    manifest = root / MANIFEST_PATH
    manifest.write_bytes(manifest.read_bytes() + b"# hand edit\n")
    before = manifest.read_bytes()
    diagnostics = check_outputs(root, outputs)
    assert any(item.code == "PROJECTION_BYTE_MISMATCH" for item in diagnostics)
    assert manifest.read_bytes() == before
