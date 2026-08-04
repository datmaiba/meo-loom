"""The producer-bound emit channel: T3.12 L601's missing "runtime" leg.

Before this channel existed, every event that could reach
``benchmarks/telemetry-v3.jsonl`` was stamped ``dat-kit-cli``, so a receipt bound
to a named producer could only be hand-authored - a synthetic event, forbidden by
T3.12 L603-604. That, and not any trust judgement, was the conformance blocker to
activation.

This module pins the channel's properties. It activates nothing:
``telemetry/producers.json`` stays untouched and no resolver reads these events.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import telemetry  # noqa: E402


def _producers_module():
    path = ROOT / "telemetry" / "producers.py"
    spec = importlib.util.spec_from_file_location("dat_kit_producers_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "telemetry").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _lying_producer_id() -> str:
    """A ``str`` subclass whose real value is HARVEST but which reports task-handoff.

    Shared by the two tests that drive the identity type check - one through
    ``producer_writer``, one through ``bind`` directly - so the fixture cannot drift
    between them.
    """

    class Liar(str):
        def __eq__(self, other):  # noqa: D105
            return other == telemetry.TASK_HANDOFF_PRODUCER_ID

        def __hash__(self):  # noqa: D105
            return hash(telemetry.TASK_HANDOFF_PRODUCER_ID)

    return Liar(telemetry.HARVEST_PRODUCER_ID)


def _events(root: Path) -> list[dict]:
    path = root / "telemetry" / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run(root: Path, *argv: str) -> int:
    return telemetry.main(["--repository-root", str(root), *argv])


# --- the channel exists and stamps its own identity ---------------------------


def test_task_handoff_channel_is_registered_and_bindable(tmp_path):
    writer = telemetry.producer_writer(_repo(tmp_path), telemetry.TASK_HANDOFF_PRODUCER_ID)
    assert isinstance(writer, telemetry.ProducerWriter)


def test_producer_writer_refuses_an_unregistered_id(tmp_path):
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.producer_writer(_repo(tmp_path), "not-a-registered-producer")
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"


def test_registry_is_immutable(tmp_path):
    with pytest.raises(TypeError):
        telemetry._PRODUCER_POLICIES["smuggled"] = telemetry._task_handoff_policy()  # type: ignore[index]
    # The property that matters is not "a MappingProxyType rejects writes" - that
    # is stdlib behaviour - but that the mutation attempt leaves the channel set
    # unchanged, so bind() still refuses the smuggled id.
    with pytest.raises(telemetry.TelemetryError):
        telemetry.producer_writer(_repo(tmp_path), "smuggled")


def test_bound_channel_owns_only_its_declared_event_types_via_public_append(tmp_path):
    """The control at the PUBLIC entry point, which is where the gap was.

    A policy constrains fields, not event types, so a writer bound to
    task-handoff could otherwise stamp its identity on a task_finished, whose
    closed payload touches none of its metadata rules. Round 1 named
    ``producer_writer`` as public API; a first fix guarded only the CLI caller
    and tested the private helper, leaving this path open under a green test.
    """
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    before = len(_events(root))
    event = telemetry._new_event(
        task_id,
        "task_finished",
        {"outcome": "completed", "scorecard_ref": None},
        producer_revision=telemetry.TASK_HANDOFF_REVISION,
    )
    writer = telemetry.producer_writer(root, telemetry.TASK_HANDOFF_PRODUCER_ID)
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        writer.append(event)
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"
    assert len(_events(root)) == before


# Deliberately absent: a second test for the CLI path. Round 2 asked for an
# authority check ahead of lifecycle validation so an unauthorized channel would
# not receive whichever diagnostic the lifecycle happened to raise. That check was
# a DUPLICATE of the writer's, and keeping two copies in sync is exactly what
# produced round 3's fail-open regression. The control is now single-sourced in
# ProducerWriter._append, covered by the public-append test above; the CLI path
# reaches it through the same writer. The cost is a less precise diagnostic on
# that one path, accepted in exchange for one control instead of two.


def test_the_cli_channel_is_unconstrained():
    """The bound must not accidentally constrain the generic channel.

    The CLI policy makes no event_types claim, so it owns everything - the
    decision is visible at its construction rather than in a side table.
    """
    policy = telemetry._cli_policy()
    assert policy.event_types is None
    assert all(policy.owns(event_type) for event_type in telemetry.EVENT_TYPES)


def test_handoff_ref_outside_the_handoffs_tree_is_refused(tmp_path):
    """handoff_ref is the schema's one free-text-ish field and it reaches the
    committed public corpus through this flow. It must be policy-bounded."""
    root = _repo(tmp_path)
    assert _run(root, "start", "--workflow", "build-loop") == 0
    task_id = _events(root)[0]["task_id"]
    payload = json.dumps({"handoff_ref": "clients/acme/teardown-plan.md", "reason": "deliberate_pause"})
    before = len(_events(root))
    assert _run(root, "append", "--task-id", task_id, "--event", "handoff_created", "--payload-json", payload) == 2
    assert len(_events(root)) == before


# --- HARVEST is refused unconditionally --------------------------------------


def test_harvest_is_refused_at_the_composition_root(tmp_path):
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.producer_writer(_repo(tmp_path), "build-loop-harvest")
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"


def test_harvest_refusal_survives_a_registry_that_contains_it(tmp_path, monkeypatch):
    """The refusal must not depend on HARVEST being absent from the registry."""
    from types import MappingProxyType

    smuggled = MappingProxyType(
        {
            **dict(telemetry._PRODUCER_POLICIES),
            "build-loop-harvest": telemetry._task_handoff_policy(),
        }
    )
    monkeypatch.setattr(telemetry, "_PRODUCER_POLICIES", smuggled)
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.producer_writer(_repo(tmp_path), "build-loop-harvest")
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"


def test_the_refused_id_is_a_real_producer_id():
    """The coupling assertion, made where a failure is loud and free.

    An earlier draft asserted ``_harvest_producer_id() == PRODUCER_IDS[0]`` -
    a tautology restating the implementation, green under exactly the tuple
    reorder that disabled the guard. This asserts the *literal the control
    depends on* against the registry, by membership rather than position, so a
    rename of the producer fails here instead of silently opening the channel.
    """
    producers = _producers_module()
    assert telemetry.HARVEST_PRODUCER_ID in producers.PRODUCER_IDS


def test_reordering_producer_ids_cannot_disable_the_refusal(tmp_path, monkeypatch):
    """Position independence, proven rather than asserted."""
    producers = _producers_module()
    reordered = tuple(reversed(producers.PRODUCER_IDS))
    assert reordered[0] != telemetry.HARVEST_PRODUCER_ID
    monkeypatch.setattr(producers, "PRODUCER_IDS", reordered, raising=True)
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.producer_writer(_repo(tmp_path), telemetry.HARVEST_PRODUCER_ID)
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"


# --- the policy is exactly sufficient, and no wider ---------------------------


def test_policy_admits_the_runtime_source_class():
    policy = telemetry._task_handoff_policy()
    assert "runtime" in policy.source_classes


def test_policy_authorizes_only_its_own_revision():
    policy = telemetry._task_handoff_policy()
    assert policy.authorizes("producer.revision", telemetry.TASK_HANDOFF_REVISION)
    assert not policy.authorizes("producer.revision", "telemetry-cli/1")


def test_policy_authorizes_handoff_coverage_refs_only():
    policy = telemetry._task_handoff_policy()
    assert policy.authorizes("coverage.missing_requirement_refs", "handoff:abc:task_resumed")
    assert not policy.authorizes("coverage.missing_requirement_refs", "evidence:abc")


# --- the generic CLI channel is unchanged ------------------------------------


def _seed_resumable_task(root: Path) -> str:
    assert _run(root, "start", "--workflow", "build-loop") == 0
    task_id = _events(root)[0]["task_id"]
    payload = json.dumps({"handoff_ref": "handoffs/example.md", "reason": "deliberate_pause"})
    assert _run(root, "append", "--task-id", task_id, "--event", "handoff_created", "--payload-json", payload) == 0
    return task_id


def test_generic_resume_still_stamps_the_cli_channel(tmp_path):
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    assert _run(root, "resume", "--task-id", task_id) == 0
    resumed = [e for e in _events(root) if e["event_type"] == "task_resumed"]
    assert len(resumed) == 1
    assert resumed[0]["producer"] == {"id": "dat-kit-cli", "revision": "telemetry-cli/1"}


def test_generic_lifecycle_events_still_stamp_the_cli_channel(tmp_path):
    root = _repo(tmp_path)
    _seed_resumable_task(root)
    assert {e["producer"]["id"] for e in _events(root)} == {"dat-kit-cli"}


# --- the bound channel, end to end ------------------------------------------


def test_handoff_resume_stamps_the_producer_channel(tmp_path):
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    assert _run(root, "handoff-resume", "--task-id", task_id) == 0
    resumed = [e for e in _events(root) if e["event_type"] == "task_resumed"]
    assert len(resumed) == 1
    assert resumed[0]["producer"] == {
        "id": telemetry.TASK_HANDOFF_PRODUCER_ID,
        "revision": telemetry.TASK_HANDOFF_REVISION,
    }


def test_handoff_resume_preserves_task_id_and_lineage(tmp_path):
    """T3.12 L598's second and third limbs, on the bound channel."""
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    assert _run(root, "handoff-resume", "--task-id", task_id) == 0
    resumed = [e for e in _events(root) if e["event_type"] == "task_resumed"][0]
    first = _events(root)[0]
    assert resumed["task_id"] == task_id
    assert resumed["lineage"]["parent_task_id"] == first["lineage"]["parent_task_id"]
    assert resumed["lineage"]["delegation_id"] == first["lineage"]["delegation_id"]
    assert resumed["payload"]["resumed_from_handoff"] is True


def test_strict_tail_is_what_distinguishes_the_two_append_surfaces(tmp_path):
    """Pinned at the writer, because the CLI cannot reach this control.

    ``_append(strict_tail=True)`` refuses to write after a torn trailing record;
    the public ``ProducerWriter.append`` passes ``strict_tail=False`` and does
    not. Attempting to prove this through the CLI is a false control: the
    ``validate_lifecycle_events`` read at the top of ``_execute_command`` already
    raises TELEMETRY_HISTORY_CORRUPT on an interrupted record, so the writer is
    never reached and the test would pass with either surface. Recorded because
    an earlier draft of this module made exactly that mistake, and the red-green
    check caught it.
    """
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    handoff_event_id = _events(root)[1]["event_id"]  # read before tearing the tail

    corpus = root / "telemetry" / "events.jsonl"
    with corpus.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version": 3, "event_id": "torn')  # no trailing newline
    torn = corpus.read_bytes()

    writer = telemetry.producer_writer(root, telemetry.TASK_HANDOFF_PRODUCER_ID)
    event = telemetry._new_event(
        task_id,
        "task_resumed",
        {
            "handoff_ref": "handoffs/example.md",
            "resumed_from_handoff": True,
            "resumed_from_event_id": handoff_event_id,
        },
        producer_revision=telemetry.TASK_HANDOFF_REVISION,
    )

    with pytest.raises(telemetry.TelemetryError) as excinfo:
        writer._append(event, corpus_check=None, strict_tail=True)
    assert excinfo.value.code == "TELEMETRY_HISTORY_CORRUPT"
    assert corpus.read_bytes() == torn


def test_a_second_resume_of_the_same_handoff_is_refused(tmp_path):
    """Caught by _validate_lifecycle_corpus in _append_lifecycle_event, BEFORE any
    writer is chosen, so it does NOT distinguish the bound channel from the CLI one and
    says nothing about what ProducerWriter.append validates - that is the F2 residual,
    recorded at that method and as ADR 0004 follow-up 6. See
    test_strict_tail_is_what_distinguishes_the_two_append_surfaces for the real
    distinction.
    """
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    assert _run(root, "handoff-resume", "--task-id", task_id) == 0
    before = len(_events(root))
    assert _run(root, "handoff-resume", "--task-id", task_id) == 2
    assert len(_events(root)) == before


def test_bound_append_populates_coverage(tmp_path):
    """_expected_coverage must still run on the bound path."""
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    assert _run(root, "handoff-resume", "--task-id", task_id) == 0
    resumed = [e for e in _events(root) if e["event_type"] == "task_resumed"][0]
    assert resumed["coverage"]["status"] == "partial"
    assert "task_finished" in resumed["coverage"]["missing_event_types"]


def test_caller_cannot_supply_a_producer_id(tmp_path):
    """Identity is channel-stamped; an event carrying producer.id is rejected."""
    writer = telemetry.producer_writer(_repo(tmp_path), telemetry.TASK_HANDOFF_PRODUCER_ID)
    # Must be an event type the channel OWNS, or the event-type bound fires first
    # and this test would pass on the wrong control - which is exactly what
    # happened when the bound was added, and is why the assertion checks the
    # detail rather than the code.
    event = telemetry._new_event(
        "00000000-0000-4000-8000-000000000000",
        "task_resumed",
        {
            "handoff_ref": "handoffs/example.md",
            "resumed_from_handoff": True,
            "resumed_from_event_id": "00000000-0000-4000-8000-000000000001",
        },
        producer_revision=telemetry.TASK_HANDOFF_REVISION,
    )
    event["producer"]["id"] = telemetry.CLI_PRODUCER_ID
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        writer.append(event)
    # TELEMETRY_EVENT_INVALID is the module's default code for every generic shape
    # failure, so asserting it alone cannot distinguish this refusal from an
    # unrelated one - the defect this unit's own lesson names. Assert the detail.
    assert "producer.id" in str(excinfo.value)


# --- activation is untouched -------------------------------------------------


def test_this_channel_activates_no_producer():
    registry = json.loads((ROOT / "telemetry" / "producers.json").read_text(encoding="utf-8"))
    assert all(
        entry == {"status": "planned", "event_id": None}
        for entry in registry["producers"].values()
    )


def test_handoff_resume_is_enrolled_in_the_disabled_envelope(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)
    assert telemetry.main(
        ["--repository-root", str(root), "handoff-resume", "--task-id", task_id],
        environ={"DAT_KIT_TELEMETRY": "off"},
    ) == 0
    assert not [e for e in _events(root) if e["event_type"] == "task_resumed"]


def test_handoff_resume_is_enrolled_in_the_degraded_envelope(tmp_path, monkeypatch):
    """The commit message claimed disabled AND degraded; only disabled was pinned."""
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)

    def _boom(*args, **kwargs):
        raise OSError("simulated operational failure")

    monkeypatch.setattr(telemetry, "_append_lifecycle_event", _boom)
    before = len(_events(root))
    assert telemetry.main(["--repository-root", str(root), "handoff-resume", "--task-id", task_id]) == 0
    # Exit 0 alone would stay green on any early-exit path; assert the envelope's
    # actual contract - the command reports degraded and writes nothing.
    assert len(_events(root)) == before
    assert not [e for e in _events(root) if e["event_type"] == "task_resumed"]


def test_every_dat_kit_producer_declares_what_it_owns():
    """Ownership travels with the grant, so there is no forgotten-row state.

    Review round 3 found a side map keyed by producer id with a fail-open
    default, and a reviewer asked for fail-closed - which would have denied the
    twelve pre-existing runtime tests that bind ad-hoc ids through the public
    TelemetryStore API. Putting event_types on ProducerPolicy dissolves the
    dilemma: a policy cannot exist without having made the choice, the choice is
    read at the registration site, and the general store contract is untouched.
    This test now only has to assert that MeoLoom's own producers made it.
    """
    for producer_id, policy in telemetry._PRODUCER_POLICIES.items():
        assert policy.event_types is not None, (
            f"{producer_id} declares no event_types, so its channel is unconstrained"
        )


def test_a_policy_cannot_declare_an_unknown_event_type():
    with pytest.raises(ValueError):
        telemetry.ProducerPolicy(
            source_classes=("runtime",),
            verdict_sources=(),
            metadata_rules={"producer.revision": ("x/1",)},
            event_types=("not_a_real_event_type",),
        )


def test_a_policy_cannot_declare_an_empty_ownership_set():
    """Empty would read as 'owns nothing', which is a registration mistake, not a
    policy - an unconstrained channel says so with None."""
    with pytest.raises(ValueError):
        telemetry.ProducerPolicy(
            source_classes=("runtime",),
            verdict_sources=(),
            metadata_rules={"producer.revision": ("x/1",)},
            event_types=(),
        )


def test_writer_rejects_a_non_mapping_event_with_a_structured_diagnostic(tmp_path):
    """Round 3: the ownership check ran .get() before any shape validation, so a
    non-mapping raised a raw AttributeError at a public surface."""
    writer = telemetry.producer_writer(_repo(tmp_path), telemetry.TASK_HANDOFF_PRODUCER_ID)
    for bad in (None, [1, 2], "x"):
        with pytest.raises(telemetry.TelemetryError) as excinfo:
            writer.append(bad)
        assert excinfo.value.code == "TELEMETRY_EVENT_INVALID"


# --- refusal diagnostics are distinguishable (decided 2026-07-25) -------------
# T3.9's code list is closed and defines TELEMETRY_CORRECTION_UNAUTHORIZED for
# correction evidence; producer-channel authorization has no code of its own and
# adding one is a Class C contract change. Recorded decision: keep the shared
# code, and make the DETAIL distinguishable so a test - and therefore a reviewer -
# can tell which control refused. See
# docs/decisions/0004-corpus-evidence-separate-from-activation.md.


def test_each_producer_refusal_has_its_own_detail(tmp_path):
    root = _repo(tmp_path)
    task_id = _seed_resumable_task(root)

    with pytest.raises(telemetry.TelemetryError) as unregistered:
        telemetry.producer_writer(root, "not-a-registered-producer")

    with pytest.raises(telemetry.TelemetryError) as harvest:
        telemetry.producer_writer(root, telemetry.HARVEST_PRODUCER_ID)

    unowned = telemetry._new_event(
        task_id,
        "task_finished",
        {"outcome": "completed", "scorecard_ref": None},
        producer_revision=telemetry.TASK_HANDOFF_REVISION,
    )
    with pytest.raises(telemetry.TelemetryError) as not_owned:
        telemetry.producer_writer(root, telemetry.TASK_HANDOFF_PRODUCER_ID).append(unowned)

    # The FOURTH control, absent from this enumeration until security-reviewer round 2
    # went looking: the identity type check landed with the qa-agent F6 fold and neither
    # this test nor ADR 0004 decision 10 was extended, so the record claimed three
    # refusals while the code had four.
    with pytest.raises(telemetry.TelemetryError) as not_str:
        telemetry.producer_writer(root, 7)  # type: ignore[arg-type]

    details = [str(e.value) for e in (unregistered, harvest, not_owned, not_str)]
    assert all(d.startswith("TELEMETRY_CORRECTION_UNAUTHORIZED") for d in details)
    assert "not in the store registry" in details[0]
    assert "HARVEST has no emit channel" in details[1]
    assert "does not own this event type" in details[2]
    assert "must be exactly str" in details[3]
    # The point of the decision: four refusals, one code, four readable reasons.
    assert len({d for d in details}) == 4

    # Recurrence control, not merely a restored count. Decision 10's enumeration rotted
    # from three to four silently because nothing tied the record to the code: a test
    # that hand-builds its own N-tuple stays green when guard N+1 lands. Count the
    # refusal sites in the source instead, so adding or removing one reds HERE and the
    # fix is "extend the record". code-reviewer round 5 M2.
    #
    # Known hole, stated rather than implied: this keys on the `producer channel
    # refused: ` prefix convention, so a guard worded differently escapes it. The
    # convention is declared in ADR 0004 decision 10 - security-reviewer round 3 pointed
    # out that a pin depending on an undocumented convention is only as strong as the
    # convention being written down somewhere a future author will read.
    source = (ROOT / "scripts" / "telemetry.py").read_text(encoding="utf-8")
    assert source.count('"producer channel refused: ') == len(details), (
        "the number of producer-refusal sites changed: extend or trim both this test "
        "and ADR 0004 decision 10's enumeration"
    )


# --- qa-agent findings, 2026-07-25 -------------------------------------------


def test_export_refuses_a_finished_task_before_writing_anything(tmp_path):
    """qa-agent F1 (HIGH): the append happened first and the receipt could never land.

    export_event_corpus validated target/task/existence but not that the task was
    still OPEN. The durable append succeeded, then _validate_task_sequences rejected
    the receipt forever ("original event appears after task finish"), and because the
    corpus is append-only and the retry is idempotent by event_id those bytes could
    NEVER get a receipt - while the retry reported {"no_op": true, "status": "ok"}, so
    an operator saw success.
    """
    root = _repo(tmp_path)
    assert _run(root, "start", "--workflow", "other") == 0
    task_id = _events(root)[0]["task_id"]
    assert _run(root, "finish", "--task-id", task_id, "--outcome", "completed") == 0

    corpus = root / "benchmarks" / "telemetry-v3.jsonl"
    assert _run(root, "export", "--task-id", task_id, "--target", "benchmarks/telemetry-v3.jsonl") == 2
    assert not corpus.exists(), "refused, so nothing may have been written"
    assert not [e for e in _events(root) if e["event_type"] == "benchmark_exported"]


def test_producer_id_must_be_exactly_str(tmp_path):
    """qa-agent F6: a str subclass with a lying __eq__ bound task-handoff's policy and
    then stamped its own real value ("build-loop-harvest") on disk."""
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.producer_writer(_repo(tmp_path), _lying_producer_id())
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"
    assert "exactly str" in str(excinfo.value)


# --- the identity guards live at the join, not at the wrapper -----------------
#
# Both guards are enforced in ``TelemetryStore.bind``, the join the two sanctioned
# entry points converge on - ``producer_writer`` and ``_cli_writer`` each end in
# ``.bind(...)``. A hardening applied at one wrapper and not at the join guards only
# the caller its author had in mind. These tests therefore drive ``bind`` directly as
# well as through the wrapper.
#
# They pin the sanctioned paths and claim nothing about the private-API bypasses
# (direct ``ProducerWriter`` construction, hand-built ``_ProducerChannel``), which
# Python cannot close; those are recorded in ADR 0004 decision 10.


def test_bind_refuses_harvest_even_when_the_store_registers_it(tmp_path):
    """A store composed directly with a harvest entry bound it, and every event it
    appended was stamped ``build-loop-harvest`` on disk - the outcome T3.12
    L606-627 approves no mechanism for."""
    store = telemetry.TelemetryStore(
        _repo(tmp_path),
        {telemetry.HARVEST_PRODUCER_ID: telemetry._task_handoff_policy()},
    )
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        store.bind(telemetry.HARVEST_PRODUCER_ID)
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"
    # The detail, not just the code: four controls share this code and only the detail
    # says which one fired (ADR 0004 decision 10).
    assert "HARVEST has no emit channel" in str(excinfo.value)


def test_bind_refuses_a_producer_id_that_is_not_exactly_str(tmp_path):
    """``bind``'s registry membership test consults the id's own ``__eq__``/``__hash__``,
    so a lying str subclass satisfied it and ``_prepare_event`` then stamped the
    object's REAL value."""
    store = telemetry.TelemetryStore(
        _repo(tmp_path),
        {telemetry.TASK_HANDOFF_PRODUCER_ID: telemetry._task_handoff_policy()},
    )
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        store.bind(_lying_producer_id())
    assert excinfo.value.code == "TELEMETRY_CORRECTION_UNAUTHORIZED"
    assert "exactly str" in str(excinfo.value)


# set() is deliberately absent: CPython converts an unhashable set to frozenset
# and retries, so it never raised and would be a fake red case (qa-agent nit).
@pytest.mark.parametrize("bad", [{"a": 1}, ["x"], 7, None])
def test_unhashable_event_type_is_a_structured_diagnostic(tmp_path, bad):
    """qa-agent F9: `x in frozenset` raised a bare TypeError out of the public API,
    because the ownership check runs before validate_event."""
    writer = telemetry.producer_writer(_repo(tmp_path), telemetry.TASK_HANDOFF_PRODUCER_ID)
    with pytest.raises(telemetry.TelemetryError) as excinfo:
        writer.append({"event_type": bad})
    # A shape defect must carry the shape code, not an authorization one.
    assert excinfo.value.code == "TELEMETRY_EVENT_INVALID"


@pytest.mark.parametrize(
    "setup, detail",
    [
        ("finished", "cannot resume a finished task"),
        ("no-handoff", "no unmatched handoff to resume"),
        ("no-events", "resume target has no lifecycle events"),
    ],
)
def test_resume_lifecycle_refusals_carry_the_lifecycle_code(tmp_path, setup, detail):
    """qa-agent F10: these reported TELEMETRY_EVENT_INVALID, indistinguishable from a
    malformed argument. The existing tests assert .detail only, so the wrong code
    could be restored with the suite still green — this pins the code."""
    root = _repo(tmp_path)
    # workflow "other": build-loop additionally requires gate_result + review_result
    # before a task may finish, which is not what this test is about.
    assert _run(root, "start", "--workflow", "other") == 0
    task_id = _events(root)[0]["task_id"]
    if setup == "finished":
        assert _run(root, "finish", "--task-id", task_id, "--outcome", "completed") == 0
    if setup == "no-events":
        # A well-formed uuid4 that no task in the stream owns.
        task_id = "00000000-0000-4000-8000-000000000000"

    with pytest.raises(telemetry.TelemetryError) as excinfo:
        telemetry.build_resume_linkage(_events(root), task_id)
    assert excinfo.value.detail == detail
    assert excinfo.value.code == "TELEMETRY_LIFECYCLE_INVALID"


def test_defect_projection_also_refuses_a_finished_task(tmp_path):
    """code-reviewer round 4: only the general-export half of the F1 guard was tested,
    so reverting the defect-projection half left the suite green."""
    root = _repo(tmp_path)
    assert _run(root, "start", "--workflow", "other") == 0
    task_id = _events(root)[0]["task_id"]
    payload = json.dumps({
        "defect_id": "defect:example",
        "introduced_task": None,
        "approving_reviewers": ["reviewer:code-reviewer"],
        "gate_that_should_have_caught_it": "gate:example",
        "evidence_ref": "evidence:example",
    })
    assert _run(root, "append", "--task-id", task_id, "--event", "defect_recorded", "--payload-json", payload) == 0
    assert _run(root, "finish", "--task-id", task_id, "--outcome", "completed") == 0

    assert _run(root, "export", "--task-id", task_id, "--target", "benchmarks/defects.jsonl") == 2
    assert not (root / "benchmarks" / "defects.jsonl").exists()
    assert not [e for e in _events(root) if e["event_type"] == "benchmark_exported"]
