import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _load_producers():
    path = ROOT / "telemetry" / "producers.py"
    spec = importlib.util.spec_from_file_location("dat_kit_producers_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


producers = _load_producers()


def test_status_registry_is_closed_and_all_five_producers_are_planned():
    registry = producers.load_producer_registry()

    assert set(registry["producers"]) == set(producers.PRODUCER_IDS)
    assert len(registry["producers"]) == 5
    assert all(
        item == {"status": "planned", "event_id": None}
        for item in registry["producers"].values()
    )


def test_live_harvest_authority_is_not_exported():
    source = (ROOT / "telemetry" / "producers.py").read_text(encoding="utf-8")

    assert not hasattr(producers, "emit_build_loop_harvest")
    for authority_name in (
        "task_id",
        "root_cause_locus",
        "root_cause_ref",
        "candidate_ref",
        "ProducerPolicy",
    ):
        assert authority_name not in source


@pytest.mark.parametrize("event_id", [None, "00000000-0000-4000-8000-000000000000"])
def test_status_registry_rejects_active_until_future_resolver_contract(event_id):
    registry = producers.load_producer_registry()
    registry["producers"]["build-loop-harvest"] = {
        "status": "active",
        "event_id": event_id,
    }

    with pytest.raises(ValueError, match="future approved resolver contract"):
        producers.validate_producer_registry(registry)


def test_status_registry_rejects_unknown_producer():
    registry = producers.load_producer_registry()
    registry["producers"]["caller-selected"] = {
        "status": "planned",
        "event_id": None,
    }

    with pytest.raises(ValueError, match="exactly the five required producers"):
        producers.validate_producer_registry(registry)
