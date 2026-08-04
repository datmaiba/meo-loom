#!/usr/bin/env python3
"""MeoLoom repo validation — run locally (python3 scripts/validate.py) and in CI.

Checks: manifest JSON validity + version sync, canonical agent-contract
templates, skill/agent frontmatter, JSONL, hooks.json shape, personal-info gate.
Exit 0 = all green; exit 1 = findings printed.
"""
import datetime, json, re, subprocess, sys, glob, pathlib
from contract_check import check_repo, validate_scorecard
from registry import Catalog
from render import check_outputs, expected_outputs
from telemetry import TelemetryError, validate_defect_projection

try:
    import yaml
except ModuleNotFoundError:
    print("PyYAML is required: python3 -m pip install -r requirements-dev.txt")
    sys.exit(1)

# Windows consoles default to a legacy codepage (cp1252) that cannot encode the
# ✓/❌ status symbols — the script would crash on its final print with a false-red
# exit code even when every check passed. CI (Linux, UTF-8) never sees this.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
findings = []


def check(cond, msg):
    if not cond:
        findings.append(msg)


def frontmatter(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    parts = text.split("---")
    check(len(parts) >= 3, f"{path}: missing frontmatter")
    if len(parts) < 3:
        return None, text
    try:
        return yaml.safe_load(parts[1]), text
    except Exception as e:
        findings.append(f"{path}: frontmatter YAML error: {e}")
        return None, text


def exact_path(relative):
    """Return a repo path only when every segment has the expected casing."""
    current = ROOT
    for part in pathlib.PurePosixPath(relative).parts:
        if not current.is_dir():
            findings.append(f"{relative}: parent directory is missing")
            return current / part
        names = {child.name for child in current.iterdir()}
        if part not in names:
            findings.append(f"{relative}: missing or wrong-cased path segment '{part}'")
            return current / part
        current = current / part
    return current


# 1. Registry Catalog and the only two committed projections.
catalog_result = Catalog.load(ROOT)
catalog = catalog_result if isinstance(catalog_result, Catalog) else None
if catalog is None:
    for diagnostic in catalog_result:
        findings.append(f"{diagnostic.code}: {diagnostic.path}: {diagnostic.message}")
else:
    # Governed-inventory sweep runs at validation time, not inside
    # Catalog.load (a stray untracked file must not brick every consumer).
    for diagnostic in catalog.validate_governed_inventory():
        findings.append(f"{diagnostic.code}: {diagnostic.path}: {diagnostic.message}")
    for diagnostic in check_outputs(ROOT, expected_outputs(catalog)):
        findings.append(f"{diagnostic.code}: {diagnostic.path}: {diagnostic.message}")

# 1b. Engine revision entry — every registered domain's `required_engine_revision`
# must resolve to a committed engine manifest whose declared revision matches, and
# the engine policy file the manifest names must exist. A mismatch is the
# composition stop (DOMAIN_ENGINE_REVISION_MISMATCH) enforced at validation time.
if catalog is not None:
    for domain in catalog.domains():
        required = domain.get("required_engine_revision", "")
        if not re.fullmatch(r"[a-z][a-z0-9-]*/[0-9]+", required or ""):
            findings.append(f"{domain.get('domain_id')}: malformed required_engine_revision {required!r}")
            continue
        engine_id = required.split("/")[0]
        manifest_path = ROOT / "engine" / engine_id / "engine.json"
        check(manifest_path.is_file(),
              f"{domain.get('domain_id')}: requires engine {required!r} but engine/{engine_id}/engine.json is missing")
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            findings.append(f"engine/{engine_id}/engine.json: invalid JSON: {e}")
            continue
        if not isinstance(manifest, dict):
            findings.append(f"engine/{engine_id}/engine.json: manifest must be a JSON object")
            continue
        check(manifest.get("engine_revision") == required,
              f"DOMAIN_ENGINE_REVISION_MISMATCH: {domain.get('domain_id')} requires {required!r} "
              f"but engine/{engine_id}/engine.json declares {manifest.get('engine_revision')!r}")
        # The policy path comes from data: require a repo-relative path with no
        # parent escapes (ROOT / "/abs" discards ROOT; ".." walks out of it).
        policy = manifest.get("policy", "")
        policy_parts = pathlib.PurePosixPath(policy).parts if isinstance(policy, str) and policy else ()
        policy_ok = bool(policy_parts) and not pathlib.PurePosixPath(policy).is_absolute() and ".." not in policy_parts
        check(policy_ok, f"engine/{engine_id}/engine.json: policy must be a repo-relative path, got {policy!r}")
        check(not policy_ok or (ROOT / policy).is_file(),
              f"engine/{engine_id}/engine.json: declared policy file missing: {policy!r}")

# 2. Skills
skill_files = sorted(path for path in (ROOT / "skills").rglob("SKILL.md") if path.is_file())
for f in skill_files:
    fm, text = frontmatter(f)
    if not fm:
        continue
    check("name" in fm and "description" in fm, f"{f}: frontmatter needs name + description")
    check(len(fm.get("description", "")) < 1024, f"{f}: description {len(fm.get('description',''))} chars (limit 1024)")
    check(text.count("\n") < 500, f"{f}: body {text.count(chr(10))} lines (keep under 500)")

# (2b retired at 4f: sentence-marker pack detection is gone. Registry
# conformance — Catalog load + §3b reviewer resolution + render --check
# byte-exact — is the only pack detection. Slot completeness for active
# packs is enforced by Catalog.load's DOMAIN_SLOT_MISSING fail-closed path.)

# 3. Agents
for f in sorted(glob.glob(str(ROOT / "agents/*.md"))):
    if ".gitkeep" in f:
        continue
    fm, _ = frontmatter(f)
    if not fm:
        continue
    for key in ("name", "description", "tools"):
        check(key in fm, f"{f}: frontmatter missing '{key}'")

# 3b. Reviewer-agent tables: legacy triggers own them inside SKILL.md; active
# packs own them in <pack_location>/reviewers.md (the binding surface — the
# rendered trigger carries no policy). Every `name` in a table row must
# resolve to a committed agents/<name>.md charter.
if catalog is not None:
    for domain in catalog.domains():
        trigger_path = ROOT / "skills" / domain["trigger"]["name"] / "SKILL.md"
        check(trigger_path.is_file(), f"registered domain trigger is missing: {trigger_path.relative_to(ROOT)}")
        if domain["lifecycle"] == "active":
            table_path = ROOT / domain["pack_location"] / "reviewers.md"
        else:
            table_path = trigger_path
        if not table_path.is_file():
            continue
        for line in table_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| `"):
                match = re.search(r"`([^`]+)`", line)
                if match:
                    name = match.group(1)
                    # Only well-formed single-segment ids resolve to charters;
                    # anything else (verdict vocabulary, a traversal like
                    # `../x`) must never reach the filesystem probe.
                    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
                        continue
                    check((ROOT / f"agents/{name}.md").exists(),
                          f"{table_path}: references missing agents/{name}.md")

# 4. Hooks
hooks = json.load(open(ROOT / "hooks.json"))
check("SessionStart" in hooks.get("hooks", {}), "hooks.json: SessionStart missing")
boot = ROOT / "templates/session-bootstrap.txt"
check(boot.exists(), "templates/session-bootstrap.txt missing")
check(len(boot.read_text().split()) < 150, "session-bootstrap.txt too long (injected into every session — keep under 150 words)")
agents_template = ROOT / "templates/common/AGENTS.md"
check(agents_template.exists(), "templates/common/AGENTS.md missing")
if agents_template.exists():
    agent_text = agents_template.read_text(encoding="utf-8")
    check("single canonical instruction entrypoint" in agent_text,
          "AGENTS.md template must declare itself the canonical contract")
    check("`docs/agent-workflow.md`" in agent_text and "`docs/agent-working-rules.md`" in agent_text,
          "AGENTS.md template must link the shared workflow and working-rules docs")

# 4b. Shared contract checker — also used by brownfield preflight and CI.
for code, message in check_repo().items:
    findings.append(f"{code}: {message}")

handoff_skill = ROOT / "skills/handoff/SKILL.md"
if handoff_skill.is_file():
    handoff_text = handoff_skill.read_text(encoding="utf-8")
    for heading in ("## Runtime", "## Workflow", "## Canonical contract", "## Git state", "## Decisions in effect", "## Verified gates", "## Third-party tool risks", "## Telemetry"):
        check(heading in handoff_text,
              f"skills/handoff/SKILL.md: missing required handoff section '{heading}'")

# 4c. Pack-owned LOAD instrumentation: a governed handoff declares its Domain Pack, and
# the newest software-dev handoff declares the telemetry that software-dev owns.
#
# The check above gates the SKILL's *specification*. That is a different property, and
# measurement says it is a weak one: of 37 files in handoffs/, 16 miss at least one of
# those seven headings and 8 miss all seven. So the spec-level gate does not propagate,
# and this one gates the artifact.
#
# Scope, stated because overclaiming it would be the defect this unit exists to close:
# this verifies a handoff DECLARES a task id and a task_started event id. It does not
# verify the event exists — that needs the id checked against the committed corpus, which
# forces an export per handoff. Owner chose the weaker gate; see
# docs/decisions/0006-instrument-before-activate.md.
HANDOFF_INSTRUMENTATION_BASELINE = "HANDOFF-2026-07-26-corpus-first-security-reviewer-owed.md"
_HANDOFF_DATED = re.compile(r"^HANDOFF-(\d{4}-\d{2}-\d{2})-.+\.md$")
_UUID_SHAPED = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_TELEMETRY_HEADING = "## Telemetry"
_WORKFLOW_HEADING = "## Workflow"
# An explicitly declared non-emit. The section's own prose invites this ("if emission was
# skipped, failed, or disabled, say which and why"), and the two-id rule forbade it: an
# honest record red the gate while a fabricated pair of uuids passed. Found by trying to
# write this phase's own handoff, which is the first file the gate governs.
_TELEMETRY_DECLARED_NON_EMIT = re.compile(
    r"^(skipped|failed|disabled)\b\s*[:\u2014-]\s*\S", re.IGNORECASE | re.MULTILINE)
# Anchored to a whole LINE. A bare substring test is satisfied by `### Telemetry` and by
# any prose that merely mentions the string; qa-agent defeated both.
_TELEMETRY_HEADING_LINE = re.compile(r"^##[ \t]+Telemetry[ \t]*\r?$", re.MULTILINE)
_WORKFLOW_HEADING_LINE = re.compile(r"^##[ \t]+Workflow[ \t]*\r?$", re.MULTILINE)
_ANY_HEADING_LINE = re.compile(r"^##[ \t]", re.MULTILINE)
_DOMAIN_PACK_LINE = re.compile(r"^domain_pack:[ \t]*([a-z0-9-]+)[ \t]*\r?$", re.MULTILINE)


def _mask_fenced_headings(text):
    """Blank out heading-LOOKING lines inside fenced blocks, preserving every offset.

    Fence-unawareness broke the gate in both directions, and qa-agent reproduced both: a
    handoff with NO real section but a fenced markdown *example* beginning `## Telemetry`
    passed (false green — and that is the shape a handoff ABOUT this phase has), while a
    real section whose body contained a fenced block with a `## ` line was truncated at it
    and red (false red).

    Only heading-looking lines are masked, and with same-length filler, so ids inside a
    fenced block within the section still count and every offset into the document is
    unchanged — the section is then sliced out of the ORIGINAL text.
    """
    inside = False
    out = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            inside = not inside
            out.append(line)
            continue
        if inside and stripped.startswith("#"):
            body = line.rstrip("\r\n")
            out.append(" " * len(body) + line[len(body):])
        else:
            out.append(line)
    return "".join(out)


def _handoff_date(name):
    """The calendar date in a handoff filename, or None if the name is not canonical.

    The date is PARSED, not pattern-matched: `HANDOFF-2026-13-45-x.md` satisfies a shape
    regex, and being last by filename it would become the governed file for as long as it
    existed, making the gate permanently decorative. qa-agent found exactly that.
    """
    matched = _HANDOFF_DATED.match(name)
    if not matched:
        return None
    try:
        return datetime.date.fromisoformat(matched.group(1))
    except ValueError:
        return None


def _handoff_section(text, masked, heading_line):
    """Return a top-level Markdown section from original text, or None.

    The masked copy is used only to recognise headings, while the original preserves the
    section's content. This keeps fenced examples from forging a section boundary.
    """
    heading = heading_line.search(masked)
    if heading is None:
        return None
    following = _ANY_HEADING_LINE.search(masked[heading.end():])
    end = heading.end() + following.start() if following else len(text)
    return text[heading.end():end]


def _declared_domain_pack(text):
    """Read the first nonblank Workflow line, never a prose mention elsewhere."""
    masked = _mask_fenced_headings(text)
    workflow = _handoff_section(text, masked, _WORKFLOW_HEADING_LINE)
    if workflow is None:
        return None
    first_nonblank = next((line for line in workflow.splitlines() if line.strip()), "")
    matched = _DOMAIN_PACK_LINE.fullmatch(first_nonblank)
    return matched.group(1) if matched else None


handoffs_dir = ROOT / "handoffs"
if handoffs_dir.is_dir():
    # Candidates are ANY file whose name begins `handoff-`, case-insensitively, with no
    # extension filter at all — the canonical `.md` is then required by the naming rule
    # below. qa-agent escaped an exact `HANDOFF-*.md` glob three times running, each time
    # one character away: `handoff-…` (prefix case), `….MD` (extension case), then
    # `….markdown`. Filtering candidates narrowly means each new spelling is a silent
    # exemption; admitting them all and refusing the non-canonical ones closes the family.
    # CONTEXT-* and SESSION-ORDER-* are still excluded, because the test is the prefix.
    handoff_files = []
    for candidate in sorted(handoffs_dir.iterdir()):
        if not candidate.name.lower().startswith("handoff-"):
            continue
        check(not candidate.is_symlink(),
              f"handoffs/{candidate.name}: handoff must not be a symlink")
        if candidate.is_file() and not candidate.is_symlink():
            handoff_files.append(candidate)
    baseline_date = _handoff_date(HANDOFF_INSTRUMENTATION_BASELINE)
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    for handoff in handoff_files:
        parsed = _handoff_date(handoff.name)
        # An unparseable name is refused, never skipped: skipping would let
        # `HANDOFF-notes.md` stand as the only handoff and the gate govern nothing. The
        # dated form is contractual in skills/handoff/SKILL.md.
        check(parsed is not None,
              f"handoffs/{handoff.name}: handoff filename must be "
              "HANDOFF-<YYYY-MM-DD>-<slug>.md with a real calendar date")
        # A future date pins `max()` to that file for as long as it exists. One day of
        # slack absorbs clock skew and timezone differences between hosts and CI.
        if parsed is not None:
            check(parsed <= tomorrow,
                  f"handoffs/{handoff.name}: handoff date is in the future")
    dated = [(parsed, p) for p in handoff_files
             if (parsed := _handoff_date(p.name)) is not None]
    # The GOVERNED set is computed first, and the baseline file is not a member of it: it
    # is the boundary marker, not a candidate. Selecting the newest over ALL handoffs and
    # then testing it against the baseline exempted a same-day handoff whose slug sorted
    # before the baseline's — because the baseline itself was then "newest". That would
    # have exempted this very phase's own handoff, written under it. qa-agent found it; ADR 0006 had asserted the
    # opposite as fact.
    governed = [
        (parsed, path) for parsed, path in dated
        if path.name != HANDOFF_INSTRUMENTATION_BASELINE
        and (baseline_date is None or parsed >= baseline_date)
    ]
    declared_packs = {}
    valid_domain_packs = {"none"} | {domain["domain_id"] for domain in catalog.domains()}
    for _, handoff in governed:
        handoff_text = handoff.read_text(encoding="utf-8", errors="replace")
        declared = _declared_domain_pack(handoff_text)
        declared_packs[handoff] = declared
        check(declared in valid_domain_packs,
              f"handoffs/{handoff.name}: first nonblank line of '{_WORKFLOW_HEADING}' must "
              "be domain_pack: <registered domain_id>|none")
        workflow = _handoff_section(
            handoff_text, _mask_fenced_headings(handoff_text), _WORKFLOW_HEADING_LINE)
        check(not (declared == "none" and workflow is not None and "build-loop" in workflow),
              f"handoffs/{handoff.name}: domain_pack: none contradicts build-loop workflow")

    software_dev_governed = [
        pair for pair in governed if declared_packs[pair[1]] == "software-dev"
    ]
    if software_dev_governed:
        # Newest by (date, filename), never by mtime: a fresh `git clone` writes mtimes in
        # checkout order, which tracks path order, so mtime-last in a clone is whichever
        # prefix sorts last rather than the newest handoff.
        _, newest_handoff = max(software_dev_governed, key=lambda pair: (pair[0], pair[1].name))
        newest_text = newest_handoff.read_text(encoding="utf-8", errors="replace")
        masked = _mask_fenced_headings(newest_text)
        section = _handoff_section(newest_text, masked, _TELEMETRY_HEADING_LINE)
        if section is None:
            findings.append(
                f"handoffs/{newest_handoff.name}: missing required handoff section "
                f"'{_TELEMETRY_HEADING}'")
        else:
            # Two DISTINCT ids: the task id and the task_started event id. The SKILL's
            # blanket "write none rather than omitting" rule would otherwise let
            # `## Telemetry` + `none` satisfy a heading-only check, which is a rubber
            # stamp, and one id repeated twice is not two ids.
            declared = len(set(_UUID_SHAPED.findall(section))) >= 2
            # A skipped emit recorded honestly is IN scope; a back-filled one is not. The
            # reason text is required, so `skipped` alone is still a rubber stamp.
            excused = bool(_TELEMETRY_DECLARED_NON_EMIT.search(section))
            check(declared or excused,
                  f"handoffs/{newest_handoff.name}: '{_TELEMETRY_HEADING}' must declare a "
                  "task_id and a task_started event_id, or say skipped/failed/disabled "
                  "with a reason")

# 5. Personal-info gate (the repository root is a plugin distribution source)
PERSONAL_INFO_TOKEN_FILE = ROOT / ".personal-info-tokens.local"


def _load_personal_info_tokens(path: pathlib.Path) -> tuple[str, ...]:
    """Load the maintainer-local token list without making it public source."""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except FileNotFoundError:
        return ()
    return tuple(
        token
        for raw in lines
        if (token := raw.strip()) and not token.startswith("#")
    )


_personal_info_tokens = _load_personal_info_tokens(PERSONAL_INFO_TOKEN_FILE)
BANNED = (
    re.compile("|".join(re.escape(token) for token in _personal_info_tokens), re.I)
    if _personal_info_tokens
    else None
)

# The gate below skips telemetry/events.jsonl, the machine-local stream that is the
# one file allowed to hold local_private events. The skip is only sound while that
# file cannot reach a commit, so this asks git instead of asserting a substitute.
#
# An earlier version of this check tokenised telemetry/.gitignore on whitespace and
# looked for "events.jsonl". qa-agent showed that wrong seven ways: `# events.jsonl`,
# `   events.jsonl`, `x events.jsonl` and friends passed while git did NOT ignore the
# file (a false green on exactly the condition the check exists to catch), and
# `/events.jsonl` / `*.jsonl` failed while git DID ignore it. Reimplementing
# gitignore semantics is the mistake; git is the only correct oracle.
#
# It also skipped unconditionally, so `git add -f telemetry/events.jsonl` made the
# file tracked AND still unscanned. Now the skip requires ignored AND untracked, and
# anything else is scanned — a tracked file is committed, therefore not private.
# Fails safe: if git is unavailable the file is scanned rather than skipped.
#
# Honest note on the second conjunct: `git check-ignore` is index-aware by default
# (verified on git 2.34 - a tracked path reports NOT ignored, which is exactly what
# `--no-index` exists to turn off), so `ignored` alone already rejects a tracked
# file. `not tracked` is kept as belt-and-braces on a disclosure gate and is
# recorded here as REDUNDANT rather than advertised as the control - an earlier
# commit message credited it with catching the tracked case, which git was already
# doing. code-reviewer round 4, 2026-07-25.
def _is_skippable_local_stream(path: pathlib.Path) -> bool:
    if path.resolve() != (ROOT / "telemetry" / "events.jsonl").resolve():
        return False
    try:
        ignored = subprocess.run(
            ("git", "check-ignore", "-q", "telemetry/events.jsonl"),
            cwd=ROOT, capture_output=True, check=False,
        ).returncode == 0
        tracked = subprocess.run(
            ("git", "ls-files", "--error-unmatch", "telemetry/events.jsonl"),
            cwd=ROOT, capture_output=True, check=False,
        ).returncode == 0
    except (OSError, ValueError):
        return False  # no git: scan it
    return ignored and not tracked
for f in glob.glob(str(ROOT / "**/*"), recursive=True):
    p = pathlib.Path(f)
    if p.is_dir() or ".git/" in f or p.suffix not in {".md", ".json", ".jsonl", ".sh", ".txt", ".tpl", ".py", ".yml", ".yaml", ".mdc", ".toml", ".tsv"}:
        continue
    # Exempt only this exact repository path. Resolving here would also exempt a
    # tracked symlink alias whose target is the local file.
    if p == PERSONAL_INFO_TOKEN_FILE:
        continue
    # Skip the local-private stream only while git confirms it is ignored and not
    # tracked — see _is_skippable_local_stream. Scanning it otherwise would report
    # the local-private stream's location on a hit; skipping a committable file would
    # be worse.
    if _is_skippable_local_stream(p):
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if BANNED is not None and BANNED.search(line):
            findings.append(f"PERSONAL INFO LEAK {f}:{i}")

# 6. Skill-eval cases — static guard against trigger regressions (Tier 1).
# Each positive case names a `match` trigger phrase that MUST (a) still appear in
# its expect_skill's description and (b) appear in no other skill's description.
# Catches the common failure of editing a description and silently breaking a
# skill's triggering, or two skills fighting over the same trigger.
skill_desc = {}
for f in skill_files:
    fm, _ = frontmatter(f)
    if fm and fm.get("name"):
        skill_desc[fm["name"]] = fm.get("description", "") or ""

evals_path = ROOT / "benchmarks/skill-evals.jsonl"
check(evals_path.exists(), "benchmarks/skill-evals.jsonl missing")
if evals_path.exists():
    for i, raw in enumerate(evals_path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            case = json.loads(raw)
        except Exception as e:
            findings.append(f"skill-evals.jsonl:{i}: invalid JSON: {e}")
            continue
        exp = case.get("expect_skill")
        if exp is None:
            continue  # negative case — verifiable only behaviourally (Tier 2), skip here
        cid = case.get("id", f"line {i}")
        if exp not in skill_desc:
            findings.append(f"skill-evals [{cid}]: expect_skill '{exp}' has no skills/{exp}/SKILL.md")
            continue
        m = (case.get("match") or "").lower()
        check(bool(m), f"skill-evals [{cid}]: positive case needs a 'match' trigger phrase")
        if m:
            check(m in skill_desc[exp].lower(),
                  f"skill-evals [{cid}]: trigger '{case.get('match')}' no longer in {exp} description (trigger regressed?)")
            clash = [n for n, d in skill_desc.items() if n != exp and m in d.lower()]
            check(not clash,
                  f"skill-evals [{cid}]: trigger '{case.get('match')}' also in {clash} — trigger collision")

# 7. JSONL is append-only evidence. Scorecard v1 remains valid before the v2
# boundary; v2 records are strict and v1 may never follow the first v2 line.
for jsonl in sorted((ROOT / "benchmarks").glob("*.jsonl")):
    parsed_entries = []
    for i, raw in enumerate(jsonl.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except Exception as e:
            findings.append(f"{jsonl.name}:{i}: invalid JSON: {e}")
            continue
        parsed_entries.append(entry)
    if jsonl.name == "scorecard.jsonl":
        for code, detail in validate_scorecard(parsed_entries):
            findings.append(f"scorecard.jsonl: {code}: {detail}")
    if jsonl.name == "defects.jsonl":
        # The durable defect projection is a closed 13-field T3.10.2 record with
        # append-only correction chains — validate it through its owning runtime.
        try:
            validate_defect_projection(ROOT)
        except TelemetryError as diagnostic:
            findings.append(f"defects.jsonl: {diagnostic.code}: {diagnostic.detail}")

if findings:
    print(f"❌ {len(findings)} finding(s):")
    for x in findings:
        print(" -", x)
    sys.exit(1)
print("✓ all checks green")
