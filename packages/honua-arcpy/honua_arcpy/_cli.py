"""``honua-arcpy`` console entry point.

Subcommands:

* ``assess`` -- read an ``ArcPyScriptInventoryArtifact`` produced by
  ``honua_admin.scan_arcpy_script(...)`` (or the workflow-level
  ``honua_sdk.migration.scan_arcpy_file``) and pivot it against the
  compatibility manifest. Prints a per-call TODO list with replacement
  hints, and writes ``honua-arcpy-assessment.json`` for the migration tool.
* ``matrix`` -- regenerate the compatibility matrix markdown from the
  in-code manifest (useful in local development and as a CI doc-gate).

Both subcommands work without network access.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._compat import COMPAT, FunctionEntry, anchor_for


# ---------------------------------------------------------------------------
# Assess
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssessmentRow:
    qualified_name: str
    occurrences: int
    status: str  # "supported" | "stub" | "out-of-scope"
    backend: str
    notes: str
    replacement_hint: str | None
    tracking: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualifiedName": self.qualified_name,
            "occurrences": self.occurrences,
            "status": self.status,
            "backend": self.backend,
            "notes": self.notes,
            "replacementHint": self.replacement_hint,
            "tracking": self.tracking,
        }


def _iter_tool_calls(inventory: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    # ``toolCalls`` / ``tool_calls`` is the honua_admin.scan_arcpy_script
    # inventory shape; ``calls`` is the honua_sdk.migration.scan_arcpy_source
    # report shape (both are documented inputs for ``assess``).
    raw = (
        inventory.get("toolCalls")
        or inventory.get("tool_calls")
        or inventory.get("calls")
        or []
    )
    if isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, Mapping):
                yield entry


def _qualified_name(entry: Mapping[str, Any]) -> str | None:
    """Return ``family.Function`` matching the COMPAT manifest keys."""

    call = entry.get("call") or entry.get("qualifiedName") or entry.get("qualified_name")
    tool = entry.get("tool") or entry.get("toolName")
    toolbox = entry.get("toolbox") or entry.get("family")
    if isinstance(call, str) and call.startswith("arcpy."):
        parts = call.split(".")
        if len(parts) >= 3:
            return _canonicalize(f"{parts[1]}.{parts[-1]}")
    if isinstance(toolbox, str) and isinstance(tool, str):
        family = toolbox if toolbox in {"analysis", "management", "da"} else _family_for_toolbox(toolbox)
        if family is not None:
            return _canonicalize(f"{family}.{tool}")
    return None


# Names that the scanner emits but COMPAT stores under a shared key (e.g.
# ``arcpy.management.CopyFeatures`` resolves through the shim's ``Copy``
# entry). Keep the table tiny -- it is only for honest synonyms, not for
# hiding stubs.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "management.CopyFeatures": "management.Copy",
}


def _canonicalize(qualified_name: str) -> str:
    return _ALIAS_TO_CANONICAL.get(qualified_name, qualified_name)


_TOOLBOX_FAMILY: dict[str, str] = {
    "analysis": "analysis",
    "management": "management",
    "data_management": "management",
    "da": "da",
    "sa": "sa",
    "na": "na",
    "ddd": "ddd",
}


def _family_for_toolbox(value: str) -> str | None:
    if value in _TOOLBOX_FAMILY:
        return _TOOLBOX_FAMILY[value]
    return None


def assess_inventory(inventory: Mapping[str, Any]) -> list[AssessmentRow]:
    """Pivot a scanner inventory against ``COMPAT`` and return rows."""

    counts: dict[str, int] = {}
    for entry in _iter_tool_calls(inventory):
        name = _qualified_name(entry)
        if name is None:
            continue
        counts[name] = counts.get(name, 0) + 1

    rows: list[AssessmentRow] = []
    for name, occurrences in sorted(counts.items()):
        entry = COMPAT.get(name)
        if entry is not None:
            status = "supported" if entry.is_supported else "stub"
            rows.append(
                AssessmentRow(
                    qualified_name=name,
                    occurrences=occurrences,
                    status=status,
                    backend=entry.backend,
                    notes=entry.notes,
                    replacement_hint=entry.replacement_hint,
                    tracking=entry.tracking,
                )
            )
        else:
            rows.append(
                AssessmentRow(
                    qualified_name=name,
                    occurrences=occurrences,
                    status="out-of-scope",
                    backend="unknown",
                    notes="Not in honua-arcpy MVP scope (sa/na/ddd/mp).",
                    replacement_hint="Open a backlog ticket; see docs/honua-arcpy/scanner-handoff.md.",
                    tracking=None,
                )
            )
    return rows


def render_assessment(rows: Sequence[AssessmentRow]) -> str:
    """Format the assessment as a human-readable summary."""

    if not rows:
        return "No arcpy tool calls detected in the supplied inventory."

    buckets: dict[str, list[AssessmentRow]] = {"supported": [], "stub": [], "out-of-scope": []}
    for row in rows:
        buckets.setdefault(row.status, []).append(row)

    out: list[str] = []
    out.append("honua-arcpy assessment")
    out.append("=" * len(out[-1]))
    out.append("")
    out.append(f"Supported: {len(buckets['supported'])}  Stubs: {len(buckets['stub'])}  Out-of-scope: {len(buckets['out-of-scope'])}")
    out.append("")

    for bucket_name, label in (
        ("supported", "Supported (run unchanged)"),
        ("stub", "Stubs (will raise -- replacement hint shown)"),
        ("out-of-scope", "Out of MVP scope"),
    ):
        bucket = buckets[bucket_name]
        if not bucket:
            continue
        out.append(label)
        out.append("-" * len(label))
        for row in sorted(bucket, key=lambda item: (-item.occurrences, item.qualified_name)):
            line = f"  [{row.occurrences:>3}x] {row.qualified_name}  --  {row.notes}"
            out.append(line)
            if row.replacement_hint:
                out.append(f"       hint: {row.replacement_hint}")
            if row.tracking:
                out.append(f"       tracking: {row.tracking}")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def _load_inventory(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Inventory file not found: {path}")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def _assess(args: argparse.Namespace) -> int:
    inventory = _load_inventory(args.inventory)
    rows = assess_inventory(inventory)
    output_dir = args.output_dir
    if output_dir is None:
        output_dir = args.inventory.parent
    machine_path = output_dir / "honua-arcpy-assessment.json"
    machine_path.parent.mkdir(parents=True, exist_ok=True)
    machine_path.write_text(
        json.dumps(
            {
                "rows": [row.to_dict() for row in rows],
                "summary": _assessment_summary(rows),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    sys.stdout.write(render_assessment(rows))
    return 0


def _assessment_summary(rows: Sequence[AssessmentRow]) -> dict[str, Any]:
    counts = {"supported": 0, "stub": 0, "out-of-scope": 0}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------


def render_compat_matrix() -> str:
    """Render the compatibility manifest as a Markdown document."""

    families = ("analysis", "management", "da")
    lines: list[str] = []
    lines.append("# honua-arcpy compatibility matrix")
    lines.append("")
    lines.append(
        "Generated from the in-code ``COMPAT`` manifest by "
        "``scripts/render_compat_matrix.py`` (re-run after manifest edits)."
    )
    lines.append("")
    lines.append(_status_legend())
    lines.append("")

    for family in families:
        lines.append(f"## arcpy.{family}.*")
        lines.append("")
        lines.append("| Function | Status | Backend | Replacement / notes |")
        lines.append("| --- | --- | --- | --- |")
        for name, entry in sorted(_filter_family(family).items()):
            anchor_id = name.replace(".", "").lower()
            status = entry.status.capitalize()
            backend = entry.backend.replace("_", "-")
            cell = entry.notes
            if entry.replacement_hint:
                cell = f"{cell}<br>**hint:** {entry.replacement_hint}"
            if entry.tracking:
                cell = f"{cell}<br>**tracking:** `{entry.tracking}`"
            lines.append(
                f"| <a id=\"{anchor_id}\"></a>`arcpy.{name}` | {status} | `{backend}` | {cell} |"
            )
        lines.append("")

    lines.append("## Coverage")
    lines.append("")
    supported = sum(1 for entry in COMPAT.values() if entry.is_supported)
    stubs = sum(1 for entry in COMPAT.values() if entry.status == "stub")
    lines.append(f"* Total functions: {len(COMPAT)}")
    lines.append(f"* Supported / partial: {supported}")
    lines.append(f"* Stubbed (raise ``HonuaArcpyUnsupportedError``): {stubs}")
    lines.append("")
    lines.append(
        "Stubs intentionally raise rather than silently fail so customer scripts surface gaps "
        "before the migration tool ingests the audit JSONL."
    )
    return "\n".join(lines).rstrip() + "\n"


def _status_legend() -> str:
    return (
        "Statuses: **Supported** runs against Honua, **Partial** runs with documented deviations, "
        "**Stub** raises ``HonuaArcpyUnsupportedError`` with a replacement hint and tracking ticket."
    )


def _filter_family(family: str) -> dict[str, FunctionEntry]:
    return {name: entry for name, entry in COMPAT.items() if name.startswith(f"{family}.")}


def _matrix(args: argparse.Namespace) -> int:
    text = render_compat_matrix()
    # ``--check`` runs against the committed file *before* any ``--output``
    # write so a caller that points both flags at the same path (CI used to
    # do this) cannot rewrite the committed file with fresh-rendered text
    # and then compare it to itself, masking real drift.
    if args.check is not None:
        existing = args.check.read_text(encoding="utf-8") if args.check.exists() else ""
        if existing != text:
            sys.stderr.write(
                f"Compatibility matrix drift detected at {args.check}. "
                "Re-run `honua-arcpy matrix --output <path>` and commit the result.\n"
            )
            return 1
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honua-arcpy", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    assess = sub.add_parser(
        "assess",
        help="Pivot a scanner inventory against the compatibility matrix.",
    )
    assess.add_argument("inventory", type=Path, help="ArcPyScriptInventoryArtifact JSON path.")
    assess.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write honua-arcpy-assessment.json (default: alongside the inventory).",
    )
    assess.set_defaults(func=_assess)

    matrix = sub.add_parser(
        "matrix",
        help="Render docs/compatibility-matrix.md from the in-code manifest.",
    )
    matrix.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write the rendered markdown (default: stdout).",
    )
    matrix.add_argument(
        "--check",
        type=Path,
        default=None,
        help="Compare against an existing file and exit non-zero on drift (CI doc gate).",
    )
    matrix.set_defaults(func=_matrix)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
