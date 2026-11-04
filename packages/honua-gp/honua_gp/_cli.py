"""``honua-gp`` compatibility-matrix command line tool."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from ._compat import COMPAT, FunctionEntry


# ---------------------------------------------------------------------------
# Matrix
# ---------------------------------------------------------------------------


def render_compat_matrix() -> str:
    """Render the compatibility manifest as a Markdown document."""

    families = ("analysis", "management", "da", "sa")
    lines: list[str] = []
    # OKF v0.2 frontmatter. This matrix is real consumer documentation - it is
    # what someone checks before committing to a migration - so it belongs in
    # the documentation bundle. It is also generated and compared against this
    # output by a test, so the frontmatter has to come from here rather than be
    # added by hand. See docs/okf-bundle.v1.json.
    lines.append("---")
    lines.append("type: reference")
    lines.append('title: "honua-gp compatibility matrix"')
    lines.append(
        'description: "Which gp surfaces the shim supports, which run with '
        'documented deviations, and which raise rather than fail silently. Check '
        'this before committing to a migration."'
    )
    # `resource` points at the shim's source rather than PyPI: honua-gp is not
    # published there, and a resource that 404s is worse than none.
    lines.append(
        'resource: "https://github.com/honua-io/honua-sdk-python/tree/trunk/packages/honua-gp"'
    )
    lines.append("tags: [honua-gp, gp, compatibility, generated]")
    lines.append("---")
    lines.append("# honua-gp compatibility matrix")
    lines.append("")
    lines.append(
        "Generated from the in-code ``COMPAT`` manifest by "
        "``scripts/render_compat_matrix.py`` (re-run after manifest edits)."
    )
    lines.append("")
    lines.append(_status_legend())
    lines.append("")

    for family in families:
        lines.append(f"## gp.{family}.*")
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
                f"| <a id=\"{anchor_id}\"></a>`gp.{name}` | {status} | `{backend}` | {cell} |"
            )
        lines.append("")

    lines.append("## Coverage")
    lines.append("")
    supported = sum(1 for entry in COMPAT.values() if entry.is_supported)
    stubs = sum(1 for entry in COMPAT.values() if entry.status == "stub")
    lines.append(f"* Total functions: {len(COMPAT)}")
    lines.append(f"* Supported / partial: {supported}")
    lines.append(f"* Stubbed (raise ``HonuaGpUnsupportedError``): {stubs}")
    lines.append("")
    lines.append(
        "Stubs intentionally raise rather than silently fail so callers can identify unsupported "
        "operations before runtime."
    )
    return "\n".join(lines).rstrip() + "\n"


def _status_legend() -> str:
    return (
        "Statuses: **Supported** runs against Honua, **Partial** runs with documented deviations, "
        "**Stub** raises ``HonuaGpUnsupportedError`` with a replacement hint and tracking ticket."
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
                "Re-run `honua-gp matrix --output <path>` and commit the result.\n"
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
    parser = argparse.ArgumentParser(prog="honua-gp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

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
