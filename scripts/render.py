#!/usr/bin/env python3
"""Render MeoLoom's two committed registry projections."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
from typing import Iterable

from registry import Catalog, CatalogLoadError, Diagnostic


GENERATED_MARKER = "GENERATED FROM REGISTRY — DO NOT EDIT"

# Field-content guard for generated files: ASCII separators plus the code
# points some YAML parsers treat as line breaks (NEL, LS, PS) — any of them
# could terminate a `>-` block scalar or a TSV field and smuggle content.
UNSAFE_FIELD_CHARS = "\t\n\r\x85\u2028\u2029"
MANIFEST_PATH = "templates/common/.meoloom-files.tsv"
SLOT_ORDER = (
    "workflow.md",
    "ground-truth.md",
    "gates.md",
    "reviewers.md",
    "deliverables/",
    "loop-profile.md",
)


def render_domain_trigger(catalog: Catalog, descriptor: dict[str, object]) -> bytes:
    trigger = descriptor["trigger"]
    if not isinstance(trigger, dict):  # not assert: must survive python -O
        raise ValueError(f"descriptor {descriptor.get('domain_id')!r} has no trigger object")
    aliases = trigger["aliases"]
    if not isinstance(aliases, list):
        raise ValueError(f"descriptor {descriptor.get('domain_id')!r} aliases must be a list")
    # Aliases and the other registry strings below embed into the generated
    # body: they get the same content guard as the description, or registry
    # data could smuggle lines into the rendered trigger (4f security INFO,
    # closed at 5a). Registry validation is the first line of defense; the
    # renderer still fails closed on its own.
    body_fields = [
        trigger.get("name"),
        descriptor.get("domain_id"),
        descriptor.get("required_engine_revision"),
        descriptor.get("pack_location"),
        *aliases,
    ]
    for field in body_fields:
        if (
            not isinstance(field, str)
            or not field.strip()
            or any(ch in field for ch in UNSAFE_FIELD_CHARS)
        ):
            raise ValueError(
                f"descriptor {descriptor.get('domain_id')!r} has a body field that"
                " is not a non-empty single line without tabs, newlines, or"
                " Unicode line breaks"
            )
    # The description is embedded in generated YAML frontmatter: a newline (legal
    # JSON) would terminate the `>-` block scalar and let registry data smuggle
    # frontmatter keys or instruction lines into the rendered trigger. Same
    # content guard as the scaffold-manifest fields below.
    description = trigger.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or any(ch in description for ch in UNSAFE_FIELD_CHARS)
    ):
        raise ValueError(
            f"descriptor {descriptor.get('domain_id')!r} description must be a"
            " non-empty single line without tabs, newlines, or Unicode line breaks"
        )
    pack = descriptor["pack_location"]
    lines = [
        "---",
        f"name: {trigger['name']}",
        "description: >-",
        f"  {trigger['description']}",
        "---",
        f"<!-- {GENERATED_MARKER}; source_revision={catalog.domain_registry_revision} -->",
        "",
        f"# {trigger['name']}",
        "",
        f"Resolve domain `{descriptor['domain_id']}` through the Registry Catalog.",
        f"Load engine `{descriptor['required_engine_revision']}` and pack `{pack}`.",
        "Load the six semantic slots in this exact order:",
        "",
        *(f"1. `{pack}/{slot}`" for slot in SLOT_ORDER),
        "",
        f"Registered aliases: {', '.join(f'`{alias}`' for alias in aliases)}.",
        "Fail closed with `DOMAIN_SLOT_MISSING` or `DOMAIN_ENGINE_REVISION_MISMATCH`",
        "before execution when the Catalog, engine, or any slot is unavailable.",
        "Use only the loaded pack's deliverable, gate, and reviewer routing; this",
        "trigger contains no independent domain policy.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def render_scaffold_manifest(catalog: Catalog) -> bytes:
    # The manifest is a full registry projection: it carries the lifecycle
    # column and init.sh materializes only scaffold_active rows. Do NOT use
    # the greenfield FilePlan here — that plan is lifecycle-filtered for
    # Python consumers (contract R5) and would hide repo_only rows that the
    # manifest must still report.
    lines = [f"# {GENERATED_MARKER}; source_revision={catalog.registry_revision}"]
    entries = [
        entry
        for entry in catalog.scaffold_file_plan("inspect-brownfield").entries
        if entry.precondition == "target-absent"
        and entry.materialization_action in {"copy", "render-pointer"}
    ]
    for entry in entries:
        fields = (
            entry.source_template,
            entry.target_relative_path,
            entry.ownership_class,
            entry.materialization_action,
            entry.project_contract_revision,
            entry.artifact_lifecycle,
        )
        if any(ch in field for field in fields for ch in UNSAFE_FIELD_CHARS):
            raise ValueError(f"unsafe manifest field in {entry.target_relative_path}")
        lines.append("\t".join(fields))
    return ("\n".join(lines) + "\n").encode("utf-8")


def expected_outputs(catalog: Catalog) -> dict[str, bytes]:
    outputs = {MANIFEST_PATH: render_scaffold_manifest(catalog)}
    for descriptor in catalog.domains():
        if descriptor["lifecycle"] != "active":
            continue
        destination = f"skills/{descriptor['trigger']['name']}/SKILL.md"
        if destination in outputs:
            raise CatalogLoadError(
                (Diagnostic("PROJECTION_DESTINATION_COLLISION", destination, "multiple projections target one path"),)
            )
        outputs[destination] = render_domain_trigger(catalog, descriptor)
    return dict(sorted(outputs.items()))


def _atomic_write(root: Path, relative: str, data: bytes) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise OSError(f"refusing to replace symlink projection {relative}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def write_outputs(root: Path, outputs: dict[str, bytes]) -> None:
    for relative, data in outputs.items():
        _atomic_write(root, relative, data)


def check_outputs(root: Path, outputs: dict[str, bytes]) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for relative, expected in outputs.items():
        path = root / relative
        try:
            actual = path.read_bytes()
        except OSError as exc:
            diagnostics.append(Diagnostic("PROJECTION_MISSING", relative, str(exc)))
            continue
        if actual != expected:
            diagnostics.append(Diagnostic("PROJECTION_BYTE_MISMATCH", relative, "committed bytes differ"))
    expected_paths = set(outputs)
    skills = root / "skills"
    if skills.is_dir():
        for path in skills.glob("*/SKILL.md"):
            relative = path.relative_to(root).as_posix()
            try:
                marked = GENERATED_MARKER.encode("utf-8") in path.read_bytes()
            except OSError:
                continue
            if marked and relative not in expected_paths:
                diagnostics.append(Diagnostic("PROJECTION_STALE_OUTPUT", relative, "no active descriptor owns this trigger"))
    return tuple(diagnostics)


def _emit(diagnostics: Iterable[Diagnostic]) -> int:
    items = tuple(diagnostics)
    for item in items:
        print(f"{item.code}: {item.path}: {item.message}")
    return 1 if items else 0


def main(argv: list[str] | None = None) -> int:
    # cp1252 trap (paid-for lesson): diagnostics may carry non-ASCII paths.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--check", action="store_true", help="compare every expected projection without writing")
    parser.add_argument("projection", nargs="?", choices=("domain-trigger", "scaffold-manifest", "all"))
    parser.add_argument("domain_id", nargs="?")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        catalog = Catalog.load_or_raise(root)
    except CatalogLoadError as exc:
        return _emit(exc.diagnostics)
    outputs = expected_outputs(catalog)
    if args.check:
        if args.projection is not None or args.domain_id is not None:
            parser.error("--check validates all projections and takes no projection arguments")
        return _emit(check_outputs(root, outputs))
    if args.projection is None:
        parser.error("projection is required unless --check is used")
    if args.projection == "domain-trigger":
        if args.domain_id is None:
            parser.error("domain-trigger requires <domain-id>")
        descriptors = {item["domain_id"]: item for item in catalog.domains()}
        descriptor = descriptors.get(args.domain_id)
        if descriptor is None:
            return _emit((Diagnostic("DOMAIN_NOT_FOUND", args.domain_id, "no registered domain"),))
        if descriptor["lifecycle"] != "active":
            return _emit((Diagnostic("DOMAIN_LIFECYCLE_INELIGIBLE", args.domain_id, "only active domains render"),))
        relative = f"skills/{descriptor['trigger']['name']}/SKILL.md"
        selected = {relative: outputs[relative]}
    elif args.projection == "scaffold-manifest":
        if args.domain_id is not None:
            parser.error("scaffold-manifest takes no domain ID")
        selected = {MANIFEST_PATH: outputs[MANIFEST_PATH]}
    else:
        if args.domain_id is not None:
            parser.error("all takes no domain ID")
        selected = outputs
    write_outputs(root, selected)
    for relative in selected:
        print(relative)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
