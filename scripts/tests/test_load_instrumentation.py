"""The LOAD instrumentation gate: the newest governed handoff must declare its telemetry.

`premise-challenger` (2026-07-26) reproduced that this producer's real trigger had fired
37 times and emitted nothing: no file under `engine/`, `skills/`, `adapters/`, `.github/`
or `hooks.json` referenced telemetry at all. `engine/work-loop/ENGINE.md` §1 LOAD now
instructs the `task_started` emit, and this gate is the forcing function on the one
artifact that survives a session.

What the gate can and cannot do, stated because the honest scope is the whole design:
it checks that the newest governed handoff **declares** a task id and an event id. It
does NOT check the event exists — that would need the id verified against the committed
corpus, which forces an export per handoff. Owner chose the weaker gate on 2026-07-26 and
`docs/decisions/0006-instrument-before-activate.md` records that choice.

Assertions here name the SPECIFIC finding rather than asserting the whole gate is green.
A repo copy carries the developer's working tree, so any ambient finding would otherwise
red these tests for the wrong reason — code-reviewer round 4, 2026-07-25.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

import pytest

from repo_fixture import ROOT, is_git_checkout, repo_copy, run_validate


TELEMETRY_HEADING = "## Telemetry"

# Two well-formed uuid4s, so a compliant fixture section is genuinely compliant.
_TASK_ID = "3f2b1c4e-8a7d-4b6f-9c2e-1d5a7b3c9e04"
_EVENT_ID = "b7e4d219-6c53-4a8e-bf01-2d9c4e6a7b18"

COMPLIANT_SECTION = (
    f"\n{TELEMETRY_HEADING}\n"
    f"task_id: `{_TASK_ID}` · `task_started` event_id: `{_EVENT_ID}`\n"
    "Emitted at LOAD, not reconstructed.\n"
)


def _handoff(root: Path, name: str, *, section: str = "", domain_pack: str = "software-dev") -> Path:
    path = root / "handoffs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# {name}\n\n## Goal\nfixture.\n\n## Workflow\n"
        f"domain_pack: {domain_pack}\n{section}",
        encoding="utf-8",
    )
    return path


def _missing_section_finding(name: str) -> str:
    return f"handoffs/{name}: missing required handoff section '{TELEMETRY_HEADING}'"


def _undated_finding(name: str) -> str:
    return f"handoffs/{name}: handoff filename must be HANDOFF-<YYYY-MM-DD>-<slug>.md"


def _handoff_findings(out: str) -> list[str]:
    """Only findings about handoff ARTIFACTS.

    The SKILL.md spec check emits the same "missing required handoff section" phrase, so a
    bare substring assertion would be satisfied — or defeated — by a finding about a
    different file entirely.
    """
    return [line for line in out.splitlines() if line.strip().startswith("- handoffs/")]


def _baseline() -> str:
    """The gate's baseline, read from the gate rather than restated here.

    Restating it would be a second source of truth that drifts; reading it means a
    change to the constant reds these tests instead of silently re-scoping them.
    """
    source = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
    match = re.search(r'HANDOFF_INSTRUMENTATION_BASELINE\s*=\s*"([^"]+)"', source)
    assert match, "scripts/validate.py must define HANDOFF_INSTRUMENTATION_BASELINE"
    return match.group(1)


pytestmark = pytest.mark.skipif(
    not is_git_checkout(ROOT), reason="needs a git checkout to copy"
)


# --- behaviour tests ---------------------------------------------------------------


def test_gate_reds_when_the_newest_post_baseline_handoff_lacks_the_section(tmp_path):
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "HANDOFF-2026-07-26-no-telemetry.md")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert _missing_section_finding("HANDOFF-2026-07-26-no-telemetry.md") in out


def test_gate_greens_when_the_newest_post_baseline_handoff_has_the_section(tmp_path):
    """The positive case — asserted as a PAIR, so it cannot survive deleting the gate.

    An absence-assertion alone passes when the gate is removed entirely, which qa-agent
    demonstrated for four of the first draft's tests. Checking both states in one fixture
    makes the test mutation-sensitive: green with the section, red without it.
    """
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-compliant.md"
    path = _handoff(root, name, section=COMPLIANT_SECTION)
    code, out = run_validate(root)
    assert code == 0, out[-400:]
    assert not _handoff_findings(out), out

    path.write_text(
        "# h\n\n## Goal\nfixture.\n\n## Workflow\ndomain_pack: software-dev\n",
        encoding="utf-8",
    )
    code, out = run_validate(root)
    assert code != 0 and _missing_section_finding(name) in out, "the gate is not live"


def test_a_handoff_that_mentions_the_heading_in_earlier_prose_still_passes(tmp_path):
    """qa-agent's first finding, and the most likely victim was this phase's own handoff.

    Splitting on the first occurrence of the bare string examined the tail of the earlier
    paragraph instead of the section, so a compliant handoff that described the format —
    which any handoff about this phase does — red."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-mentions.md"
    body = (
        "# h\n\n## Workflow\ndomain_pack: software-dev\n\n## What changed\n"
        "skills/handoff/SKILL.md gains a mandatory `## Telemetry` section.\n"
        + COMPLIANT_SECTION
        + "\n## Next steps\n1. nothing.\n"
    )
    (root / "handoffs" / name).write_text(body, encoding="utf-8")
    code, out = run_validate(root)
    assert code == 0, out[-400:]
    assert not _handoff_findings(out), out


def test_a_prose_mention_with_ids_but_no_section_is_refused(tmp_path):
    """The mirror of the above, and the more dangerous half: a false GREEN. The heading
    test must match a whole line, not a substring anywhere in the file."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-no-section.md"
    body = (
        f"# h\n\n## Workflow\ndomain_pack: software-dev\n\n## Goal\nI skipped the ## Telemetry section. refs `{_TASK_ID}` "
        f"and `{_EVENT_ID}`.\n"
    )
    (root / "handoffs" / name).write_text(body, encoding="utf-8")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert _missing_section_finding(name) in out


def test_a_deeper_heading_does_not_satisfy_the_section(tmp_path):
    """`### Telemetry` contains `## Telemetry` as a substring."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-deeper.md"
    _handoff(root, name, section=f"\n### Telemetry\ntask_id: `{_TASK_ID}` · `{_EVENT_ID}`\n")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert _missing_section_finding(name) in out


def test_a_same_day_handoff_sorting_before_the_baseline_is_still_governed(tmp_path):
    """The baseline is a DATE boundary plus the baseline file itself, not a filename
    comparison. Comparing whole filenames mixed date order with intra-day slug order, so
    a same-day handoff whose slug sorted earlier was exempt — and this phase's own
    handoff, on branch `feature/a1-instrument-the-loop`, is exactly that shape."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    baseline = _baseline()
    _handoff(root, baseline)
    same_day_earlier_slug = baseline.replace(
        baseline.split("-", 4)[4], "a1-instrument-the-loop.md")
    assert same_day_earlier_slug < baseline, "fixture must sort BEFORE the baseline"
    _handoff(root, same_day_earlier_slug)
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert _missing_section_finding(same_day_earlier_slug) in out


def test_a_mis_cased_handoff_prefix_is_refused(tmp_path):
    """An exact `HANDOFF-*` glob let `handoff-...` escape BOTH checks — the same permanent
    hole the dated-name rule closes, one character away."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "handoff-2026-07-26-lower.md")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert "handoff-2026-07-26-lower.md" in out


@pytest.mark.parametrize(
    "body, expect_red",
    [
        ("skipped: the instrumentation landed in this phase, so LOAD predates it.\n", False),
        ("disabled: DAT_KIT_TELEMETRY=off on this host.\n", False),
        ("failed: the repository root was unavailable.\n", False),
        ("skipped\n", True),
        ("skipped:\n", True),
        ("I skipped it.\n", True),
    ],
)
def test_an_honestly_declared_non_emit_satisfies_the_section_only_with_a_reason(
        tmp_path, body, expect_red):
    """The section's prose invites recording a skipped, failed, or disabled emit, and the
    two-id rule forbade exactly that: an honest record red while a fabricated pair of
    uuids passed. Found by trying to write this phase's OWN handoff — the first file the
    gate governs. The reason text is required, so a bare `skipped` is still a rubber stamp.
    """
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-declared.md"
    _handoff(root, name, section=f"\n{TELEMETRY_HEADING}\n{body}")
    code, out = run_validate(root)
    if expect_red:
        assert code != 0, out[-400:]
        assert f"handoffs/{name}: '{TELEMETRY_HEADING}'" in out
    else:
        assert code == 0, out[-400:]
        assert not _handoff_findings(out), out


@pytest.mark.parametrize(
    "name",
    [
        "HANDOFF-2026-07-26-upper.MD",
        "HANDOFF-2026-07-26-mixed.Md",
        "HANDOFF-2026-07-26-long.markdown",
        "handoff-2026-07-26-lower-prefix.md",
    ],
)
def test_no_spelling_of_the_name_escapes_the_naming_rule(tmp_path, name):
    """qa-agent escaped an exact `HANDOFF-*.md` glob three times, each one character away:
    prefix case, then `.MD`, then `.markdown`. Candidates are now any `handoff-`-prefixed
    file and the naming rule refuses everything non-canonical, so the family is closed
    rather than one spelling at a time."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, name, section=COMPLIANT_SECTION)
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert name in out


@pytest.mark.parametrize(
    "name, why",
    [
        ("HANDOFF-2026-13-45-impossible.md", "a shape regex accepts month 13, day 45"),
        ("HANDOFF-9999-12-31-far-future.md", "a future date pins max() to it forever"),
    ],
)
def test_an_unreal_or_future_date_is_refused(tmp_path, name, why):
    """Either would make the gate permanently decorative by staying `max()` forever."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, name, section=COMPLIANT_SECTION)
    _handoff(root, "HANDOFF-2026-07-26-real.md", section=COMPLIANT_SECTION)
    code, out = run_validate(root)
    assert code != 0, why + " :: " + out[-400:]
    assert name in out, why


def test_gate_selects_by_handoff_prefix_and_filename_order_not_mtime(tmp_path):
    """The discriminating test. Fixture is built so that a WRONG selector reds.

    The non-compliant OLDER handoff is given the NEWEST mtime, and everything else shares
    one older mtime. Measured against four candidate selectors:

      * correct (HANDOFF- prefix, last by filename) -> picks the compliant newest -> green
      * max by mtime over HANDOFF-*                 -> picks the old one          -> RED
      * max by mtime over handoffs/*                -> picks the old one          -> RED
      * name-sort over all of handoffs/             -> picks the SESSION-ORDER-*  -> RED

    An earlier draft of this test set every mtime EQUAL. That does not discriminate:
    ``max()`` returns the first maximal element in directory order, so an mtime
    implementation greened by accident. plan-reviewer round 2 measured exactly that.
    """
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "CONTEXT-2026-07-27-a.md")
    old = _handoff(root, "HANDOFF-2026-07-26-a-noncompliant.md")
    newest = _handoff(root, "HANDOFF-2026-07-26-b-compliant.md", section=COMPLIANT_SECTION)
    trailing = _handoff(root, "SESSION-ORDER-2026-07-30-z.md")

    for path in (root / "handoffs").iterdir():
        os.utime(path, (1_000_000, 1_000_000))
    os.utime(old, (9_000_000, 9_000_000))  # the wrong file, made newest by mtime

    assert sorted(p.name for p in (root / "handoffs").iterdir())[-1] == trailing.name
    code, out = run_validate(root)
    assert code == 0, out[-400:]
    assert _missing_section_finding(old.name) not in out, "selector followed mtime"
    assert _missing_section_finding(trailing.name) not in out, "selector ignored the prefix"
    assert _missing_section_finding(newest.name) not in out, "the right file was refused"
    assert not _handoff_findings(out), out


def test_a_fenced_example_of_the_section_does_not_satisfy_the_gate(tmp_path):
    """The false GREEN, and the dangerous direction: a handoff with NO real section but a
    fenced markdown example beginning `## Telemetry` passed. That is exactly the shape of a
    handoff written ABOUT this phase, which is the handoff most likely to exist."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-fenced-example.md"
    body = (
        "# h\n\n## Workflow\ndomain_pack: software-dev\n\n## Goal\nDescribe the new section.\n\n"
        "```markdown\n"
        f"## Telemetry\ntask_id: `{_TASK_ID}` · `task_started` event_id: `{_EVENT_ID}`\n"
        "```\n"
    )
    (root / "handoffs" / name).write_text(body, encoding="utf-8")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert _missing_section_finding(name) in out


def test_a_fence_inside_the_section_does_not_truncate_it(tmp_path):
    """The false RED mirror: a real section whose body contains a fenced block with a
    `## ` line was cut off at that line, so the ids after it were never seen."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-fence-inside.md"
    body = (
        "# h\n\n## Workflow\ndomain_pack: software-dev\n\n## Goal\nfixture.\n\n"
        f"{TELEMETRY_HEADING}\n"
        "The format is:\n\n```markdown\n## Telemetry\n<ids here>\n```\n\n"
        f"task_id: `{_TASK_ID}` · `task_started` event_id: `{_EVENT_ID}`\n"
    )
    (root / "handoffs" / name).write_text(body, encoding="utf-8")
    code, out = run_validate(root)
    assert code == 0, out[-400:]
    assert not _handoff_findings(out), out


def test_an_uppercase_extension_does_not_escape_the_checks(tmp_path):
    """The prefix case was closed and the EXTENSION case was not: `.MD` escaped both the
    naming rule and the section rule, and the gate silently fell back to an older file."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "HANDOFF-2026-07-26-upper.MD")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert "HANDOFF-2026-07-26-upper.MD" in out


def test_gate_reds_on_an_undated_handoff_filename(tmp_path):
    """Excluding an undated name instead would leave a permanent hole: name a file
    HANDOFF-notes.md and never carry the section. The dated form is contractual in
    skills/handoff/SKILL.md, so an unparseable name is itself a violation."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "HANDOFF-notes.md", section=COMPLIANT_SECTION)
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert _undated_finding("HANDOFF-notes.md") in out


def test_gate_ignores_handoffs_at_or_before_the_baseline(tmp_path):
    """Every handoff written before the instrumentation landed is exempt. Without this
    the gate reds the moment it lands, and back-filling a section is forbidden by the
    emitted-not-reconstructed rule the section itself states."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    baseline = _baseline()
    _handoff(root, baseline)
    _handoff(root, "HANDOFF-2026-07-20-older.md")
    _, out = run_validate(root)
    assert _missing_section_finding(baseline) not in out
    assert _missing_section_finding("HANDOFF-2026-07-20-older.md") not in out


def test_gate_is_a_no_op_when_there_are_no_handoff_files(tmp_path):
    """A fresh clone of the kit into a new project has no handoffs."""
    root = repo_copy(tmp_path, clear_handoffs=True)
    _, out = run_validate(root)
    # Scoped to findings about handoff ARTIFACTS. The SKILL.md spec check emits the same
    # "missing required handoff section" phrase, so a bare substring assertion here would
    # be satisfied by an unrelated finding about a different file.
    assert not [line for line in out.splitlines() if line.strip().startswith("- handoffs/")], out


@pytest.mark.parametrize(
    "body, why",
    [
        ("none\n", "the SKILL's blanket 'write none' rule must not satisfy this section"),
        ("Emitted at LOAD.\n", "prose with no ids is a rubber stamp"),
        (f"task_id: `{_TASK_ID}`\n", "one id is not two"),
    ],
)
def test_gate_reds_on_a_section_that_declares_no_ids(tmp_path, body, why):
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-rubber-stamp.md"
    _handoff(root, name, section=f"\n{TELEMETRY_HEADING}\n{body}")
    code, out = run_validate(root)
    assert code != 0, why + " :: " + out[-400:]
    assert f"handoffs/{name}: '{TELEMETRY_HEADING}'" in out, why


# --- change detector, labelled ------------------------------------------------------
#
# This asserts prose, so its red-green is deleting a sentence and proves little. It is
# kept because the property it names is contract-level: T3.6 requires exactly one
# original task_started per task, so a resuming session that emits a second one is a
# contract violation, and the resuming state is the one whose omission would cause it.


def test_engine_load_declares_only_the_generic_pack_slot():
    text = (ROOT / "engine" / "work-loop" / "ENGINE.md").read_text(encoding="utf-8")
    load = text.split("### 1. LOAD", 1)[1].split("### 2.", 1)[0]
    assert "Domain Pack" in load and "LOAD obligations" in load
    assert "telemetry.py" not in load and "--repository-root" not in load


def test_software_dev_pack_owns_the_exact_load_obligation():
    workflow = (ROOT / "domains" / "software-dev" / "workflow.md").read_text(encoding="utf-8")
    domains = json.loads((ROOT / "registry" / "domains.json").read_text(encoding="utf-8"))["domains"]
    trigger = next(domain["trigger"]["name"] for domain in domains if domain["domain_id"] == "software-dev")
    assert f"start --workflow {trigger}" in workflow
    assert "--repository-root" in workflow
    assert "task_id" in workflow and "event_id" in workflow
    assert "second `task_started`" in workflow
    assert "DAT_KIT_TELEMETRY=off" in workflow


def test_domain_pack_none_is_valid_without_a_telemetry_declaration(tmp_path):
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "HANDOFF-2026-07-26-standalone.md", domain_pack="none")
    code, out = run_validate(root)
    assert code == 0, out[-400:]


def test_domain_pack_none_cannot_opt_out_of_a_build_loop_handoff(tmp_path):
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-mismatched-pack.md"
    _handoff(root, name, domain_pack="none")
    path = root / "handoffs" / name
    path.write_text(path.read_text(encoding="utf-8") + "build-loop\n", encoding="utf-8")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert "domain_pack: none contradicts build-loop workflow" in out


def test_symlinked_handoff_is_refused_before_it_is_read(tmp_path):
    root = repo_copy(tmp_path, clear_handoffs=True)
    target = root / "outside.md"
    target.write_text("outside", encoding="utf-8")
    name = "HANDOFF-2026-07-26-link.md"
    try:
        (root / "handoffs" / name).symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert f"handoffs/{name}: handoff must not be a symlink" in out


@pytest.mark.parametrize("domain_pack", ("", "not-a-registered-pack"))
def test_missing_or_unknown_domain_pack_is_refused(tmp_path, domain_pack):
    root = repo_copy(tmp_path, clear_handoffs=True)
    name = "HANDOFF-2026-07-26-bad-domain.md"
    if domain_pack:
        _handoff(root, name, domain_pack=domain_pack)
    else:
        (root / "handoffs" / name).write_text("# h\n\n## Workflow\nstandalone\n", encoding="utf-8")
    code, out = run_validate(root)
    assert code != 0, out[-400:]
    assert name in out and "domain_pack" in out


def test_newer_non_software_dev_handoff_does_not_replace_software_dev_selector(tmp_path):
    root = repo_copy(tmp_path, clear_handoffs=True)
    _handoff(root, "HANDOFF-2026-07-26-software-dev.md", section=COMPLIANT_SECTION)
    _handoff(root, "HANDOFF-2026-07-27-knowledge-work.md", domain_pack="knowledge-work")
    code, out = run_validate(root)
    assert code == 0, out[-400:]
