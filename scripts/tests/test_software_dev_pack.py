"""software-dev Domain Pack cutover checks (Phase 4c).

Before/after behavioral pins for the six build-loop paths (normal, autopilot,
delegated, security, recovery, harvest): the policy that lived in the
pre-cutover skills/build-loop/SKILL.md must survive on the composed surface —
engine/work-loop/ENGINE.md for loop mechanics, domains/software-dev/* for
software policy — and the rendered thin trigger must actually resolve the
files it names. Also pins the four public review-cost rules in reviewers.md
map's exact sw phrasing) and pack purity (no engine mechanics restated).
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from registry import Catalog  # noqa: E402

PACK = ROOT / "domains" / "software-dev"
ENGINE = (ROOT / "engine/work-loop/ENGINE.md").read_text(encoding="utf-8")
TRIGGER = (ROOT / "skills/build-loop/SKILL.md").read_text(encoding="utf-8")


def slot(name: str) -> str:
    return (PACK / name).read_text(encoding="utf-8")


def flat(text: str) -> str:
    """Whitespace-normalized view: prose is hard-wrapped, policy is not."""
    return " ".join(text.split())


# --- composition: descriptor, trigger, slots -------------------------------

def test_descriptor_is_active_and_points_at_the_pack():
    catalog = Catalog.load(ROOT)
    assert isinstance(catalog, Catalog)
    descriptor = next(d for d in catalog.domains() if d["domain_id"] == "software-dev")
    assert descriptor["lifecycle"] == "active"
    assert descriptor["pack_location"] == "domains/software-dev"
    assert descriptor["required_engine_revision"] == "work-loop/1"


def test_trigger_is_generated_and_resolves_every_named_file():
    assert "GENERATED FROM REGISTRY" in TRIGGER
    named = re.findall(r"`(domains/software-dev/[^`]+)`", TRIGGER)
    assert len(named) == 6, "thin trigger must name exactly the six slots"
    for relative in named:
        path = ROOT / relative
        assert path.is_dir() if relative.endswith("/") else path.is_file(), relative
    assert "work-loop/1" in TRIGGER
    # thin means thin: no policy vocabulary from the old operative body
    for token in ("PREFLIGHT", "qa-agent", "severity", "spec/08-decisions.md"):
        assert token not in TRIGGER, f"trigger carries policy token {token!r}"


def test_loop_profile_migrated_wholesale_and_old_location_is_gone():
    assert not (ROOT / "skills/build-loop/loop-profile.md").exists()
    profile = slot("loop-profile.md")
    assert "**Goal.** No build-loop task safely unlocks Time or Proactive yet" in profile
    assert "| Build a phase from spec (`build phase N`) | **Goal** |" in profile


# --- the six behavioral paths ----------------------------------------------

def test_normal_path_policy_survives():
    workflow, reviewers = slot("workflow.md"), slot("reviewers.md")
    # engine owns the loop mechanics
    assert "stop for explicit approval" in flat(ENGINE)
    assert "Never bundle plan and execution" in flat(ENGINE)
    assert "A green gate proves nothing" in flat(ENGINE)  # red-green rule lives in VERIFY
    # pack owns the software instantiation
    assert "think like the senior engineer" in flat(workflow)
    assert "spec/08-decisions.md" in workflow
    for lens in ("Data", "Contracts", "UX states", "Domain invariants", "Security",
                 "Edge cases", "Reuse", "Traps", "Scope"):
        assert f"| {lens} |" in workflow, f"lens {lens} lost in cutover"
    assert "build → qa-agent → fix → qa-agent → code-reviewer" in flat(reviewers)


def test_autopilot_path_policy_survives():
    workflow = slot("workflow.md")
    assert '**"autopilot"**' in ENGINE  # activation keyword is engine-owned
    assert "One up-front approval stop" in ENGINE
    assert "Incremental preflight" in workflow
    assert "PREFLIGHT DONE" in workflow
    assert "taste choices" in workflow
    assert "security-reviewer APPROVE" in workflow  # phase-transition requirement


def test_delegated_path_policy_survives():
    workflow = slot("workflow.md")
    assert "writes NO code" in workflow
    assert "spec compliance" in workflow and "code quality" in workflow
    assert "max 2 retries per task" in workflow
    assert "Consult before the final retry" in workflow
    assert "benchmarks/escalations.jsonl" in workflow


def test_security_path_policy_survives():
    reviewers = slot("reviewers.md")
    for surface in ("auth/session logic", "file uploads or path handling",
                    "new public endpoints", "permission changes", "payment/money"):
        assert surface in flat(reviewers), f"security trigger surface {surface!r} lost"
    assert "after code-reviewer approves" in flat(reviewers)
    # skip-stated-never-silent is engine REPORT policy
    assert "never silently" in ENGINE


def test_recovery_path_policy_survives():
    workflow = slot("workflow.md")
    assert "newest" in ENGINE and "handoff" in ENGINE  # resume protocol is engine-owned
    assert "git log --oneline -10" in workflow
    assert "RESUME STATE" in workflow
    assert "fresh | partially built (list what exists) | built" in workflow


def test_harvest_path_policy_survives():
    # harvest is engine-owned end to end; the pack must not fork it
    assert "Scorecard" in ENGINE and "5-part wrap-up" in ENGINE
    assert "mechanical step comes FIRST" in ENGINE
    combined = "".join(slot(n) for n in ("workflow.md", "gates.md", "reviewers.md", "ground-truth.md"))
    assert "wrap-up" not in combined, "pack restates the engine's harvest protocol"


# --- public review-cost rules 1–4 (exact software-dev phrasing) -------------

@pytest.mark.parametrize("phrase", [
    "qa-agent → code-reviewer → security-reviewer is a strict sequence; never parallel",
    "dispatch prompt names the changed-file list and pastes gate outputs",
    "Round 2+ verifies previous findings against the new diff only",
    "static analysis, no PoC — runtime belongs to qa-agent alone",
    "≤ ~30 lines",
])
def test_review_cost_rules_land_in_reviewers_slot(phrase):
    assert phrase in flat(slot("reviewers.md")), f"§16 phrasing missing: {phrase!r}"


def test_control_proof_triplet_is_pinned():
    surfaces = {
        "gates.md": flat(slot("gates.md")),
        "qa-agent.md": flat((ROOT / "agents/qa-agent.md").read_text(encoding="utf-8")),
    }
    phrases = (
        "every added or changed safety/integrity control",
        "**Boundary:** exercise the threat through the named sanctioned public entry point",
        "**Attribution:** assert the exact result or diagnostic that distinguishes the intended control",
        "**Mutation:** apply the engine's VERIFY red-green rule to the intended control",
    )
    for name, text in surfaces.items():
        for phrase in phrases:
            assert phrase in text, f"{name} lost control-proof obligation: {phrase!r}"


# --- purity: no engine mechanics restated in the pack -----------------------

ENGINE_ONLY = [
    "genuinely unanswerable ones to the user",  # SELF-QUESTION escalation rule
    "grade your own work",                      # REVIEW independence rule
    "until you have seen it fail",              # red-green proof mechanics (engine wording)
    "you've seen it fail",                      # red-green proof (pre-cutover wording)
    "keep what conforms",                       # recovery keep-or-fix rule
    "Never bundle plan",                        # PLAN approval mechanics
    "wakeup",                                   # long-run scheduling rule
    "is law",                                   # hard rules
    "propose an amendment",
]


@pytest.mark.parametrize("sentence", ENGINE_ONLY)
def test_pack_purity_no_engine_mechanics_restated(sentence):
    for name in ("workflow.md", "ground-truth.md", "gates.md", "reviewers.md", "loop-profile.md"):
        assert sentence not in slot(name), f"{name} restates engine mechanics: {sentence!r}"


def test_deliverables_slot_has_a_real_template():
    deliverables = PACK / "deliverables"
    templates = list(deliverables.glob("*.md"))
    assert templates, "DP3.5: every pack supplies at least one usable template"
    text = templates[0].read_text(encoding="utf-8")
    for gate in ("SW-G1", "SW-G2", "SW-G3"):
        assert gate in text, "deliverable must name the gates it owes evidence to"
