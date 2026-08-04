import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATE = ROOT / "scripts/validate.py"
sys.path.insert(0, str(ROOT / "scripts"))
from contract_check import validate_scorecard


V2 = {
    "schema_version": 2,
    "agent_runtime": "codex",
    "workflow": "build-loop",
    "canonical_contract_revision": "dat-kit 1.16.0",
    "git_state": {"branch": "master", "head": "abc", "dirty": True},
}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.pop("agent_runtime"),
        lambda x: x.update(agent_runtime="invalid"),
        lambda x: x.pop("workflow"),
        lambda x: x.pop("canonical_contract_revision"),
        lambda x: x.pop("git_state"),
        lambda x: x.update(schema_version="2"),
    ],
)
def test_v2_field_contract(mutation):
    entry = json.loads(json.dumps(V2))
    mutation(entry)
    assert validate_scorecard([entry])


def test_v1_after_v2_is_invalid():
    assert ("SCORECARD_V1_AFTER_V2", "line 2") in validate_scorecard([V2, {"task": "legacy"}])
