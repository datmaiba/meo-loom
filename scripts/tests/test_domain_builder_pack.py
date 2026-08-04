"""domain-builder rewrite + synthetic non-software pack (Phase 4e).

DP6 extension proof: a domain-builder-authored synthetic pack (ledger-close —
a bookkeeping month-end close, non-software and non-knowledge-work) completes
the engine lifecycle on a registry fixture: Catalog resolution → engine
revision check → rendered trigger → six slots in DP1 order, with NO engine,
renderer, shell, or validator dispatch edit — every test here drives the
unmodified production modules over a temp tree. Also pins the 4e-rewritten
domain-builder SKILL.md (descriptor + six-slot + rendered-trigger authoring;
scope-boundary and capability-ladder dedup by reference to docs/loops.md; the
ENGINE.md "What every pack must declare" coverage; the inherited 4c/4d
constraints — single-line trigger descriptions, §3b reviewer-row rule, pinned
skill-eval phrases). 4e decision (recorded in the handoff): the synthetic pack
is fixture-only — DP6 asks for a synthetic/non-software *fixture*, and the
installed-host pack read is an external host smoke; no committed pack.
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

from registry import Catalog  # noqa: E402
from render import (  # noqa: E402
    SLOT_ORDER,
    UNSAFE_FIELD_CHARS,
    check_outputs,
    expected_outputs,
    render_domain_trigger,
    write_outputs,
)
from test_registry_catalog import codes, load_ok, registry_fixture, write_json  # noqa: E402

BUILDER = (ROOT / "skills/domain-builder/SKILL.md").read_text(encoding="utf-8")
PINNED_EVAL_PHRASES = ("run the build loop", "write a researched report")

def make_descriptor() -> dict:
    """Clone a registered descriptor and override every field: the closed
    key set stays synced with registry/domains.json, so a descriptor schema
    change breaks this fixture instead of silently diverging from it."""
    domains = json.loads((ROOT / "registry/domains.json").read_text(encoding="utf-8"))
    base = json.loads(json.dumps(
        next(d for d in domains["domains"] if d["domain_id"] == "knowledge-work")
    ))
    base.update(
        domain_id="ledger-close",
        contract_revision="domain-pack/1",
        lifecycle="active",
        pack_location="domains/ledger-close",
        trigger={
            "name": "ledger-close",
            "description": (
                "The month-end close loop for bookkeeping. Invoke when the user wants "
                "to close the books, reconcile accounts, or prepare the monthly close "
                "package. Loads the work-loop engine plus the ledger-close Domain Pack."
            ),
            "aliases": ["close the books", "month-end close"],
        },
        required_engine_revision="work-loop/1",
        gate_authority_ref="ledger-close-controller",
        loop_ceiling="Goal",
        evolution_profile_ref="maintainer-policy",
    )
    return base


DESCRIPTOR = make_descriptor()

# Slot content is what the rewritten domain-builder's interview produces: every
# ENGINE.md "What every pack must declare" item lands in its mapped slot.
SLOTS = {
    "workflow.md": (
        "# ledger-close workflow\n\n"
        "Phases: intake trial balance -> reconcile -> adjust -> review -> close.\n\n"
        "## Engine bindings (what this pack declares)\n\n"
        "- Question lenses: completeness (every account reconciled), cutoff\n"
        "  (transactions in the right period), support (every adjustment has a\n"
        "  document).\n"
        "- Decision log: the close checklist's Notes column; a recorded answer\n"
        "  is never re-asked.\n"
        "- Escalation triggers: any unreconciled difference above the materiality\n"
        "  threshold; any journal entry without support; a period reopen.\n"
        "- Smallest self-contained unit of work: one fully reconciled account\n"
        "  with its support attached.\n"
    ),
    "ground-truth.md": (
        "# ledger-close ground truth\n\n"
        "1. The general ledger and subledgers (authoritative).\n"
        "2. Bank and card statements for the period.\n"
        "3. The prior month's signed close package.\n\n"
        "A balance without a statement or subledger behind it cannot support an\n"
        "adjustment.\n"
    ),
    "gates.md": (
        "# ledger-close gates\n\n"
        "## LC-G1 — every balance-sheet account reconciles to its subledger\n\n"
        "- PASS worked case: cash account ties to the bank statement with two\n"
        "  outstanding checks listed and aged.\n"
        "- FAIL worked case: a $412 unexplained difference plugged to misc\n"
        "  expense to force the tie-out.\n"
        "- Gaming line: this gate can be gamed by booking a plug entry that\n"
        "  makes the reconciliation appear to tie.\n"
        "- Human-needed: yes — judging whether support is adequate needs the\n"
        "  controller.\n"
        "- Unlocked ceiling: Goal, human-run.\n"
    ),
    "reviewers.md": (
        "# ledger-close reviewers\n\n"
        "The controller reviews every close package before sign-off: they check\n"
        "each reconciliation's support and every adjustment's document trail.\n"
        "The preparer never signs off their own close (independence). Escalate\n"
        "to the external accountant when a period must be reopened.\n"
    ),
    "loop-profile.md": (
        "# ledger-close loop profile\n\n"
        "Ceiling: Goal, human-run — LC-G1 needs the controller's judgement to\n"
        "close honestly, so this interview-authored domain never runs on a\n"
        "schedule or unattended.\n"
    ),
}
DELIVERABLE = (
    "# Monthly close package\n\n"
    "- Reconciliation per balance-sheet account (LC-G1 evidence)\n"
    "- Adjusting entries with support\n"
    "- Controller sign-off line\n"
)


def add_ledger_close_pack(
    root: pathlib.Path,
    descriptor: dict | None = None,
    *,
    authority: bool = True,
    governed: bool = True,
) -> dict:
    descriptor = descriptor or json.loads(json.dumps(DESCRIPTOR))
    domains_path = root / "registry/domains.json"
    domains = json.loads(domains_path.read_text(encoding="utf-8"))
    domains["domains"].append(descriptor)
    write_json(domains_path, domains)
    pack = root / descriptor["pack_location"]
    pack.mkdir(parents=True)
    for name, text in SLOTS.items():
        (pack / name).write_text(text, encoding="utf-8")
    deliverables = pack / "deliverables"
    deliverables.mkdir()
    (deliverables / "close-package.md").write_text(DELIVERABLE, encoding="utf-8")
    # evolution FIRST (4c/4d precedent, and what the rewritten builder teaches).
    # Two distinct fail-closed mechanisms, both exercised negatively below:
    # - gate_authority_ref must resolve to an evolution authority with
    #   succession (DP2) or Catalog.load fails: EVOLUTION_AUTHORITY_REQUIRED.
    # - the pack's paths must be governed by exactly one component-class glob
    #   or validate_governed_inventory() reports EVOLUTION_ORPHAN_PATH.
    evolution_path = root / "registry/evolution.json"
    evolution = json.loads(evolution_path.read_text(encoding="utf-8"))
    if authority:
        # clone an existing authority shape rather than inventing a new schema
        entry = json.loads(json.dumps(
            next(a for a in evolution["authorities"] if a["authority_id"] == "software-dev-reviewer")
        ))
        entry["authority_id"] = descriptor["gate_authority_ref"]
        entry["role_type"] = "independent-controller"
        evolution["authorities"].append(entry)
    if governed:
        evolution["component_classes"].append(
            {
                "component_id": "ledger-close-fixture",
                "path_globs": [f"skills/{descriptor['trigger']['name']}/**",
                               f"{descriptor['pack_location']}/**"],
                "owner": "maintainers",
                "governance_class": "B",
                "policy_ref": descriptor["evolution_profile_ref"],
            }
        )
    write_json(evolution_path, evolution)
    return descriptor


def fixture_with_engine(tmp_path: pathlib.Path) -> pathlib.Path:
    root = registry_fixture(tmp_path)
    shutil.copytree(ROOT / "engine", root / "engine")
    return root


# --- DP6 extension proof: end-to-end dry-run --------------------------------

def test_end_to_end_dry_run_catalog_engine_check_six_slots_in_dp1_order(tmp_path):
    root = fixture_with_engine(tmp_path)
    add_ledger_close_pack(root)
    catalog = load_ok(root)
    descriptor = next(d for d in catalog.domains() if d["domain_id"] == "ledger-close")
    # engine-revision check (the DP4 composition stop, enforced by validate §1b)
    engine_id = descriptor["required_engine_revision"].split("/")[0]
    manifest = json.loads((root / "engine" / engine_id / "engine.json").read_text(encoding="utf-8"))
    assert manifest["engine_revision"] == descriptor["required_engine_revision"]
    assert (root / manifest["policy"]).is_file()
    # rendered trigger names the six slots in DP1 order
    outputs = expected_outputs(catalog)
    trigger = outputs["skills/ledger-close/SKILL.md"].decode("utf-8")
    named = re.findall(r"`(domains/ledger-close/[^`]+)`", trigger)
    assert named == [f"domains/ledger-close/{slot}" for slot in SLOT_ORDER]
    assert "GENERATED FROM REGISTRY" in trigger
    assert "no independent domain policy" in trigger


def test_pack_files_actually_load_not_just_names_in_text(tmp_path):
    root = fixture_with_engine(tmp_path)
    add_ledger_close_pack(root)
    outputs = expected_outputs(load_ok(root))
    trigger = outputs["skills/ledger-close/SKILL.md"].decode("utf-8")
    for relative in re.findall(r"`(domains/ledger-close/[^`]+)`", trigger):
        path = root / relative
        if relative.endswith("/"):
            assert path.is_dir() and any(path.iterdir()), relative
        else:
            assert path.is_file() and path.read_text(encoding="utf-8").strip(), relative
    # the loaded files carry the declared policy, not placeholders
    pack = root / "domains/ledger-close"
    assert "LC-G1" in (pack / "gates.md").read_text(encoding="utf-8")
    assert "gamed by" in (pack / "gates.md").read_text(encoding="utf-8")
    assert "controller" in (pack / "reviewers.md").read_text(encoding="utf-8")
    assert "Goal, human-run" in (pack / "loop-profile.md").read_text(encoding="utf-8")
    assert "LC-G1" in (pack / "deliverables/close-package.md").read_text(encoding="utf-8")


def test_extension_required_no_engine_renderer_shell_or_validator_dispatch_edit():
    # The fixture above drives unmodified production modules; the synthetic
    # domain must appear nowhere in them (no per-domain dispatch anywhere).
    for relative in ("scripts/registry.py", "scripts/render.py", "scripts/validate.py",
                     "engine/work-loop/ENGINE.md", "engine/work-loop/engine.json",
                     "registry/domains.json", "registry/evolution.json"):
        assert "ledger-close" not in (ROOT / relative).read_text(encoding="utf-8"), relative


# --- fail-closed paths -------------------------------------------------------

def test_alias_collision_with_registered_domain_fails_closed(tmp_path):
    root = registry_fixture(tmp_path)
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    descriptor["trigger"]["aliases"] = ["fact check"]  # collides with knowledge-work
    add_ledger_close_pack(root, descriptor)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "REGISTRY_TRIGGER_ALIAS_COLLISION" in codes(result)


def test_trigger_destination_collision_fails_closed(tmp_path):
    root = registry_fixture(tmp_path)
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    descriptor["trigger"]["name"] = "knowledge-work"  # destination already owned
    add_ledger_close_pack(root, descriptor)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "PROJECTION_DESTINATION_COLLISION" in codes(result)


def test_engine_revision_mismatch_is_the_composition_stop(tmp_path):
    root = fixture_with_engine(tmp_path)
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    descriptor["required_engine_revision"] = "work-loop/2"
    add_ledger_close_pack(root, descriptor)
    catalog = load_ok(root)  # registry shape is fine; composition is what stops
    loaded = next(d for d in catalog.domains() if d["domain_id"] == "ledger-close")
    manifest = json.loads((root / "engine/work-loop/engine.json").read_text(encoding="utf-8"))
    assert loaded["required_engine_revision"] != manifest["engine_revision"]
    # the enforcing surfaces: validate §1b flags it; the rendered trigger fails closed
    assert "DOMAIN_ENGINE_REVISION_MISMATCH" in (ROOT / "scripts/validate.py").read_text(encoding="utf-8")
    trigger = expected_outputs(catalog)["skills/ledger-close/SKILL.md"].decode("utf-8")
    assert "DOMAIN_ENGINE_REVISION_MISMATCH" in trigger


def test_unresolvable_gate_authority_fails_load(tmp_path):
    # "evolution first" fail-closed proof, half 1: no authority, no Catalog.
    root = registry_fixture(tmp_path)
    add_ledger_close_pack(root, authority=False)
    result = Catalog.load(root)
    assert not isinstance(result, Catalog)
    assert "EVOLUTION_AUTHORITY_REQUIRED" in codes(result)


def test_ungoverned_pack_paths_are_orphans_in_the_inventory(tmp_path):
    # half 2: without the component-class glob the pack files are orphans —
    # the governance sweep (validate_governed_inventory) reports every one.
    root = registry_fixture(tmp_path)
    add_ledger_close_pack(root, governed=False)
    catalog = load_ok(root)
    orphans = [
        d.path for d in catalog.validate_governed_inventory()
        if d.code == "EVOLUTION_ORPHAN_PATH" and d.path.startswith("domains/ledger-close/")
    ]
    assert len(orphans) == len(SLOTS) + 1  # five slot files + the deliverable


def test_pinned_eval_phrases_still_come_from_the_eval_corpus():
    # the literals guarded here and warned about in domain-builder's body must
    # keep tracking benchmarks/skill-evals.jsonl — not drift as folklore
    evals = (ROOT / "benchmarks/skill-evals.jsonl").read_text(encoding="utf-8")
    for phrase in PINNED_EVAL_PHRASES:
        assert phrase in evals, f"pinned phrase no longer in skill-evals: {phrase!r}"


def test_missing_and_stale_synthetic_trigger_fail_byte_exact_check(tmp_path):
    root = fixture_with_engine(tmp_path)
    add_ledger_close_pack(root)
    outputs = expected_outputs(load_ok(root))
    write_outputs(root, outputs)
    trigger = root / "skills/ledger-close/SKILL.md"
    trigger.unlink()
    diagnostics = check_outputs(root, outputs)
    assert any(d.code == "PROJECTION_MISSING" and d.path == "skills/ledger-close/SKILL.md" for d in diagnostics)
    write_outputs(root, outputs)
    trigger.write_bytes(trigger.read_bytes() + b"hand edit\n")
    diagnostics = check_outputs(root, outputs)
    assert any(d.code == "PROJECTION_BYTE_MISMATCH" and d.path == "skills/ledger-close/SKILL.md" for d in diagnostics)


# --- negative trigger cases --------------------------------------------------

def test_unsafe_field_charset_is_pinned():
    # security LOW (4e): the parametrized cases below derive from the guard
    # constant — pin the literal so a silently shrunken charset fails here
    # instead of shrinking the test matrix (guard: render.py, commit 300c7fb).
    assert UNSAFE_FIELD_CHARS == "\t\n\r\x85\u2028\u2029"


@pytest.mark.parametrize("bad_char", list(UNSAFE_FIELD_CHARS))
def test_unsafe_description_characters_fail_render(tmp_path, bad_char):
    root = registry_fixture(tmp_path)
    catalog = load_ok(root)
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    descriptor["trigger"]["description"] = f"a{bad_char}b"
    with pytest.raises(ValueError):
        render_domain_trigger(catalog, descriptor)


@pytest.mark.parametrize("bad_char", list(UNSAFE_FIELD_CHARS))
def test_unsafe_alias_characters_fail_render(tmp_path, bad_char):
    # security INFO (4f, closed at 5a): aliases embed into the generated
    # SKILL.md body exactly like the description embeds into frontmatter —
    # the same UNSAFE_FIELD_CHARS guard applies to every registry field
    # that reaches a generated file.
    root = registry_fixture(tmp_path)
    catalog = load_ok(root)
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    descriptor["trigger"]["aliases"] = [f"a{bad_char}b"]
    with pytest.raises(ValueError):
        render_domain_trigger(catalog, descriptor)


@pytest.mark.parametrize(
    "field_path",
    [("trigger", "name"), ("domain_id",), ("required_engine_revision",), ("pack_location",)],
    ids=lambda item: "/".join(item),
)
def test_unsafe_body_field_characters_fail_render(tmp_path, field_path):
    # Same guard for the remaining registry strings interpolated into the
    # rendered body (registry validation is the first line; render must
    # fail closed on its own).
    root = registry_fixture(tmp_path)
    catalog = load_ok(root)
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    target = descriptor
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = "a\u2028b"
    with pytest.raises(ValueError):
        render_domain_trigger(catalog, descriptor)


def test_synthetic_description_does_not_reuse_pinned_eval_phrases():
    for phrase in PINNED_EVAL_PHRASES:
        assert phrase not in DESCRIPTOR["trigger"]["description"]
    for ch in UNSAFE_FIELD_CHARS:
        assert ch not in DESCRIPTOR["trigger"]["description"]


def test_synthetic_aliases_collide_with_nothing_registered():
    domains = json.loads((ROOT / "registry/domains.json").read_text(encoding="utf-8"))
    taken = set()
    for domain in domains["domains"]:
        taken.add(domain["trigger"]["name"].casefold())
        taken.update(alias.casefold() for alias in domain["trigger"]["aliases"])
    mine = {DESCRIPTOR["trigger"]["name"], *DESCRIPTOR["trigger"]["aliases"]}
    assert not taken & {alias.casefold() for alias in mine}


# --- the rewritten domain-builder SKILL.md -----------------------------------

def frontmatter_description() -> str:
    match = re.search(r"description: >-\n((?:  .*\n)+)", BUILDER)
    return " ".join(line.strip() for line in match.group(1).splitlines())


def test_builder_authors_descriptor_six_slots_rendered_trigger_evolution():
    description = frontmatter_description()
    for token in ("registry descriptor", "six-slot", "renders the thin trigger", "evolution profile"):
        assert token in description, token
    # all closed descriptor fields are named for the authoring step (DP2)
    for field in ("domain_id", "contract_revision", "lifecycle", "pack_location",
                  "required_engine_revision", "gate_authority_ref", "loop_ceiling",
                  "evolution_profile_ref"):
        assert field in BUILDER, field
    for artifact in ("registry/domains.json", "scripts/render.py", "registry/evolution.json"):
        assert artifact in BUILDER, artifact
    # DP1 slot set in DP1 order on the "Six slots" line
    slots_line = next(line for line in BUILDER.splitlines() if line.startswith("- **Six slots**"))
    positions = [slots_line.index(f"`{slot}`") for slot in SLOT_ORDER]
    assert positions == sorted(positions)


def test_builder_retired_the_five_slot_authoring_path():
    assert "What it captures" not in BUILDER  # the old five-slot table header
    assert "skills/<domain>/" not in BUILDER  # old packs lived beside skills/
    assert "the five files" not in BUILDER
    # 4f single fire: the quoted legacy note left with validate.py §2b —
    # the marker sentence appears nowhere in the builder at all
    assert "Contract files live beside " + "this one" not in BUILDER


def test_builder_dedups_scope_boundary_and_ladder_to_docs_loops():
    flattened = " ".join(BUILDER.split())
    assert "docs/loops.md` §Scope boundary" in flattened
    assert "do not restate" in flattened
    assert "capability ladder is canonical in `docs/loops.md`" in flattened
    # the ladder's prerequisites table is not restated here
    assert "| Loop |" not in BUILDER


def test_builder_interview_covers_everything_engine_binds_to():
    engine = (ROOT / "engine/work-loop/ENGINE.md").read_text(encoding="utf-8")
    assert "What every pack must declare" in engine  # the checklist source
    for item in ("Question lenses", "Ground-truth sources", "Decision-log location",
                 "Reviewer team, sequence, charters", "Gates with exact criteria",
                 "Escalation trigger list", "Smallest self-contained unit of work",
                 "Deliverable templates", "Loop ceiling"):
        assert item in BUILDER, f"interview must gather: {item}"
    assert "What every pack must declare" in BUILDER


def test_builder_encodes_inherited_4c_4d_constraints():
    flattened = " ".join(BUILDER.split())
    assert "SINGLE line" in flattened
    assert "U+0085/U+2028/U+2029" in flattened
    assert "agents/<name>.md" in flattened  # §3b reviewer-row rule
    for phrase in PINNED_EVAL_PHRASES:  # warned about in the body…
        assert phrase in flattened
        assert phrase not in frontmatter_description()  # …never in the description
    assert "collision" in flattened
    assert "byte-exact" in flattened


def test_builder_keeps_gate_validity_semantics_and_registration_step():
    flattened = " ".join(BUILDER.split())
    for token in ("worked cases", "gaming line", "Human-needed", "Sign-off",
                  "mark it draft"):
        assert token in flattened, token
    assert "DOMAIN_LOOP_CEILING_MISMATCH" in flattened  # ceiling mirrored in descriptor
    assert "fresh host session" in flattened  # DP5 registration evidence rule
    assert "scribe with a quality bar" in flattened  # stance survives
