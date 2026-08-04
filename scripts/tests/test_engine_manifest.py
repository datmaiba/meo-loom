"""Engine manifest and purity checks (Phase 4b).

The engine is the host- and domain-neutral working loop. These tests pin:
(1) the manifest ↔ descriptor composition contract (a changed engine revision
must fail composition), and (2) engine purity — ENGINE.md must contain no
domain-specific policy tokens (the static half of the Phase 4f deletion test).
"""
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from registry import Catalog  # noqa: E402

ENGINE_DIR = ROOT / "engine" / "work-loop"
PHASES = ["LOAD", "SELF-QUESTION", "PLAN", "EXECUTE", "VERIFY", "REVIEW", "REPORT", "HARVEST"]

# Domain policy must live in packs, not the engine. Word-boundary tokens that
# indicate software-dev or knowledge-work policy leaked into ENGINE.md.
FORBIDDEN = [
    r"\bspec/(?!brief\b)",   # software ground-truth layout ("spec/brief" is the
                             # map-mandated neutral rewording of L180–183, allowed)
    r"\bgit\b",              # repository operations
    r"\bcommits?\b",         # repository operations
    r"\bqa-agent\b", r"\bcode-reviewer\b", r"\bsecurity-reviewer\b", r"\bplan-reviewer\b",
    r"\bdemo\b",             # software done-evidence
    r"\bfact-check", r"\bcitation", r"\bcited\b",  # knowledge-work truth standards
    r"\bendpoints?\b", r"\bdocker\b", r"\btype-check", r"\bpytest\b",
    r"\bmodel:\s", r"\bopus\b", r"\bsonnet\b", r"\bhaiku\b",  # host model routing
]


def manifest():
    return json.loads((ENGINE_DIR / "engine.json").read_text(encoding="utf-8"))


def test_manifest_exists_and_declares_work_loop_1():
    m = manifest()
    assert m["engine_id"] == "work-loop"
    assert m["engine_revision"] == "work-loop/1"
    assert m["phases"] == PHASES


def test_manifest_policy_file_exists():
    m = manifest()
    assert (ROOT / m["policy"]).is_file()


def test_engine_md_names_every_phase():
    text = (ENGINE_DIR / "ENGINE.md").read_text(encoding="utf-8")
    for phase in PHASES:
        assert phase in text, f"ENGINE.md missing phase {phase}"


def test_registered_domains_pin_this_engine_revision():
    catalog = Catalog.load(ROOT)
    assert isinstance(catalog, Catalog), "registry must load to compose the engine"
    revision = manifest()["engine_revision"]
    for domain in catalog.domains():
        assert domain["required_engine_revision"] == revision, (
            f"{domain['domain_id']} pins {domain['required_engine_revision']!r}; "
            f"engine declares {revision!r} — composition must fail on mismatch"
        )


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_engine_purity_no_domain_policy_tokens(pattern):
    text = (ENGINE_DIR / "ENGINE.md").read_text(encoding="utf-8")
    hits = [
        (i, line.strip())
        for i, line in enumerate(text.splitlines(), 1)
        if re.search(pattern, line, re.IGNORECASE)
    ]
    assert not hits, f"domain policy token {pattern!r} in ENGINE.md: {hits}"
