"""Fail-closed regressions from the Phase 1B code review.

B1: a malformed bootstrap must never yield "no Catalog and no diagnostics".
M1: Catalog.load must return diagnostics, never raise, on descriptor garbage.
M5: greenfield/add-missing FilePlans are lifecycle-filtered (contract R5).
F3: registry JSON loading refuses symlinks (read-side symmetry with render).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

from registry import Catalog
from test_registry_catalog import codes, load_ok, registry_fixture, write_json


def mutate(root: Path, relative: str, change) -> None:
    path = root / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    write_json(path, value)


# --- B1 -------------------------------------------------------------------

@pytest.mark.parametrize("children", ["not-a-list", {}, [], None])
def test_malformed_children_always_produces_diagnostics(tmp_path, children):
    root = registry_fixture(tmp_path)

    def change(value):
        value["children"] = children

    mutate(root, "registry/platform.json", change)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert result, "fail-open: no Catalog and no diagnostics"
    assert "REGISTRY_BOOTSTRAP_MALFORMED" in codes(result)


def test_partial_child_set_names_every_missing_kind(tmp_path):
    root = registry_fixture(tmp_path)

    def change(value):
        value["children"] = [item for item in value["children"] if item["kind"] == "domains"]

    mutate(root, "registry/platform.json", change)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    missing = [item.message for item in result if item.code == "REGISTRY_CHILD_MISSING"]
    assert any("adapters" in message for message in missing)
    assert any("evolution" in message for message in missing)


# --- M1 -------------------------------------------------------------------

@pytest.mark.parametrize(
    "name", ["bad<name", "UPPER", "", 7, None, "a/b"], ids=repr
)
def test_invalid_trigger_name_is_a_diagnostic_not_an_exception(tmp_path, name):
    root = registry_fixture(tmp_path)

    def change(value):
        value["domains"][0]["trigger"]["name"] = name

    mutate(root, "registry/domains.json", change)
    result = Catalog.load(root)  # must not raise
    assert not isinstance(result, Catalog)
    assert "REGISTRY_TRIGGER_INVALID" in codes(result)


def test_non_list_aliases_is_a_diagnostic_not_an_exception(tmp_path):
    root = registry_fixture(tmp_path)

    def change(value):
        value["domains"][0]["trigger"]["aliases"] = "not-a-list"

    mutate(root, "registry/domains.json", change)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "REGISTRY_TYPE_INVALID" in codes(result)


# --- M5 -------------------------------------------------------------------

def test_greenfield_plan_contains_only_scaffold_active_entries():
    catalog = load_ok(ROOT)
    for mode in ("greenfield", "add-missing"):
        plan = catalog.scaffold_file_plan(mode)
        lifecycles = {entry.artifact_lifecycle for entry in plan.entries}
        assert lifecycles <= {"scaffold_active"}, (mode, lifecycles)


def test_inspect_mode_still_reports_every_lifecycle():
    catalog = load_ok(ROOT)
    inspect = catalog.scaffold_file_plan("inspect-brownfield")
    greenfield = catalog.scaffold_file_plan("greenfield")
    assert len(inspect.entries) >= len(greenfield.entries)


# --- F3 -------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privilege on Windows")
def test_symlinked_registry_child_is_rejected_fail_closed(tmp_path):
    root = registry_fixture(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    child = root / "registry/domains.json"
    child.unlink()
    child.symlink_to(outside)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "REGISTRY_CHILD_MALFORMED" in codes(result)
