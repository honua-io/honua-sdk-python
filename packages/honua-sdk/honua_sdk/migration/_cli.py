"""Command-line entrypoint for the ArcPy -> Honua GP migration codemod.

Usage (either form works once the SDK is installed)::

    honua-migrate scan path/to/script.py
    python -m honua_sdk.migration scan path/to/script.py
    honua-migrate translate path/to/script.py --evidence out.json
    honua-migrate translate path/to/toolbox.pyt --server https://example.test
    honua-migrate run path/to/script.py --server https://example.test
    honua-migrate pyt path/to/toolbox.pyt
    honua-migrate atbx path/to/toolbox.atbx --evidence out.json
    honua-migrate gpservice path/to/GPServer.json --url https://host/GPServer

The ``scan``, ``translate``, ``pyt``, ``atbx``, and ``gpservice`` commands work
offline (no ArcGIS or network). The ``run`` command executes the translatable
steps through ``HonuaClient.ogc_processes().execute(...)`` against ``--server``.

**Server attestation.** ``translate``/``pyt``/``atbx`` classify a toolbox from
the SDK's own view of the Honua process catalog, which can drift from the server
that would run the job. Pass ``--server`` (plus admin credentials) to have the
server's canonical catalog classify every tool instead; the emitted report then
carries ``verdictSource: "server-attested"``. Without ``--server`` -- or when the
server cannot be reached -- the report still emits, marked
``verdictSource: "local-only"`` with the reason. A local verdict is never
presented as attested. See ``honua_sdk.migration.attestation``.

Attestation needs the ``honua-admin`` package (the endpoint is an admin one and
reuses the admin credential path); everything else here runs with ``honua-sdk``
alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .arcpy import (
    ArcPyProcessRunner,
    build_parity_evidence,
    scan_arcpy_file,
    translate_arcpy_report,
)
from .attestation import (
    SOURCE_FORMAT_ATBX,
    SOURCE_FORMAT_PYT,
    AttestedTranslationReport,
    TranslationManifest,
    TranslationValidator,
    attest_translation,
    build_atbx_translation_manifest,
    build_pyt_translation_manifest,
    source_format_for_path,
)
from .modelbuilder import (
    UnsupportedModelFormatError,
    build_atbx_parity_evidence,
    build_gp_service_parity_evidence,
    parse_atbx_toolbox,
    parse_gp_service_definition,
)
from .pyt import (
    UnsupportedToolboxError,
    build_pyt_parity_evidence,
    parse_binary_toolbox,
    parse_pyt_file,
)

# .atbx is now handled clean-room by the modelbuilder reader; only the
# proprietary binary .tbx remains an explicit stub in the ``pyt`` command.
_BINARY_TOOLBOX_SUFFIXES = {".tbx"}

#: Environment fallback for ``--api-key`` so a credential never has to appear in
#: shell history or a CI command line.
ADMIN_API_KEY_ENV = "HONUA_ADMIN_API_KEY"

#: Exit code for ``--require-attested`` when the verdict stayed local-only.
EXIT_NOT_ATTESTED = 4


def _emit(obj: object, *, out: Path | None) -> None:
    text = json.dumps(obj, indent=2, sort_keys=False)
    if out is None:
        print(text)
    else:
        out.write_text(text + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Server attestation
# ---------------------------------------------------------------------------


@contextmanager
def _server_validator(args: argparse.Namespace) -> Iterator[TranslationValidator | None]:
    """Yield a validator bound to ``--server``, or ``None`` when offline.

    The endpoint lives in the admin import group, so this reuses the existing
    admin credential path (``HonuaAdminClient(api_key=...)``) rather than
    introducing a second auth mechanism. ``honua_admin`` is imported lazily and
    is an optional dependency: every other command in this CLI runs with
    ``honua-sdk`` alone.
    """

    server = getattr(args, "server", None)
    if not server:
        yield None
        return

    # Lazy + optional: honua-admin is not a honua-sdk dependency, so every other
    # command in this CLI keeps working without it installed.
    from honua_admin import HonuaAdminClient

    api_key = getattr(args, "api_key", None) or os.environ.get(ADMIN_API_KEY_ENV)
    with HonuaAdminClient(server, api_key=api_key, timeout=args.attest_timeout) as client:

        def validate(manifest: TranslationManifest) -> dict[str, Any]:
            return client.validate_toolbox_translation(_admin_manifest(manifest)).to_dict()

        yield validate


def _admin_manifest(manifest: TranslationManifest) -> Any:
    """Map the codemod's manifest onto the admin client's request model."""

    from honua_admin import (
        ToolboxParameterMapping,
        ToolboxToolDescriptor,
        ToolboxTranslationManifest,
    )

    return ToolboxTranslationManifest(
        toolbox_name=manifest.toolbox_name,
        source_format=manifest.source_format,
        source_label=manifest.source_label,
        tools=[
            ToolboxToolDescriptor(
                tool_name=tool.tool_name,
                display_name=tool.display_name,
                target_process_id=tool.target_process_id,
                parameter_mappings=[
                    ToolboxParameterMapping(
                        source_name=mapping.source_name,
                        target_parameter=mapping.target_parameter,
                        source_data_type=mapping.source_data_type,
                    )
                    for mapping in tool.parameter_mappings
                ],
                unsupported_constructs=list(tool.unsupported_constructs),
            )
            for tool in manifest.tools
        ],
    )


def _attest(manifest: TranslationManifest, args: argparse.Namespace) -> AttestedTranslationReport:
    """Attest a manifest, degrading to a marked local-only verdict on failure."""

    server = getattr(args, "server", None)
    try:
        with _server_validator(args) as validator:
            return attest_translation(manifest, validator=validator, server=server)
    except Exception as exc:
        # Reaching a server is optional by design, so even a failure to *build*
        # the client (honua-admin missing, malformed base URL) leaves a usable
        # local-only report rather than aborting the migration run.
        return attest_translation(manifest, validator=_failing_validator(exc), server=server)


def _failing_validator(exc: BaseException) -> TranslationValidator:
    def validate(manifest: TranslationManifest) -> dict[str, Any]:
        raise exc

    return validate


def _report_attestation(report: AttestedTranslationReport, args: argparse.Namespace) -> int:
    """Attach the attestation to the output, print a summary, and pick an exit code."""

    if args.attestation is not None:
        _emit(report.to_dict(), out=args.attestation)

    summary = report.to_dict()["summary"]
    if report.attested:
        print(
            f"attestation: server-attested by {report.server} -- "
            f"{summary['translatedCount']} translated, "
            f"{summary['partiallyTranslatedCount']} partial, "
            f"{summary['unsupportedCount']} unsupported, "
            f"{summary['disagreementCount']} disagreeing with the local verdict",
            file=sys.stderr,
        )
        for disagreement in report.disagreements:
            print(
                f"  disagreement: {disagreement.tool_name} "
                f"local={disagreement.local_classification} "
                f"server={disagreement.server_classification} (server wins)",
                file=sys.stderr,
            )
        return 0

    print(f"attestation: local-only (NOT server-attested) -- {report.fallback_reason}", file=sys.stderr)
    if args.require_attested:
        print(
            "--require-attested was set, so a local-only verdict is a failure.",
            file=sys.stderr,
        )
        return EXIT_NOT_ATTESTED
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    report = scan_arcpy_file(args.path)
    _emit(report.to_dict(), out=args.output)
    if report.syntax_error is not None:
        print(f"syntax error: {report.syntax_error}", file=sys.stderr)
        return 2
    return 0


def _cmd_translate(args: argparse.Namespace) -> int:
    # The validation endpoint's contract is toolbox-scoped, so `translate` routes
    # a toolbox container to the toolbox lane and keeps the arcpy-script lane for
    # a plain .py script.
    if source_format_for_path(args.path) is not None:
        return _translate_toolbox(args)

    if args.server:
        print(
            f"--server cannot attest {args.path}: the server validation endpoint takes a "
            "toolbox manifest (sourceFormat pyt/atbx/tbx), and a bare arcpy .py script is a "
            "script rather than a toolbox. Run it without --server for the local plan, or "
            "point translate at a .pyt / .atbx toolbox to get a server-attested verdict.",
            file=sys.stderr,
        )
        return 2

    report = scan_arcpy_file(args.path)
    if report.syntax_error is not None:
        print(f"syntax error: {report.syntax_error}", file=sys.stderr)
        return 2
    plan = translate_arcpy_report(report)
    evidence = build_parity_evidence(plan)
    if args.evidence is not None:
        _emit(evidence, out=args.evidence)
        _emit(plan.to_dict(), out=args.output)
    else:
        _emit(plan.to_dict(), out=args.output)

    summary = evidence["summary"]
    print(
        f"coverage: {summary['translatableCalls']}/{summary['totalCalls']} translatable "
        f"({summary['coveragePercent']}%), {summary['manualReviewCalls']} manual-review, "
        f"{summary['unsupportedCalls']} unsupported",
        file=sys.stderr,
    )
    return 0


def _translate_toolbox(args: argparse.Namespace) -> int:
    """Translate a ``.pyt`` / ``.atbx`` toolbox and (optionally) attest it."""

    source_format = source_format_for_path(args.path)
    if Path(args.path).suffix.lower() in _BINARY_TOOLBOX_SUFFIXES:
        try:
            parse_binary_toolbox(args.path)
        except UnsupportedToolboxError as exc:
            print(str(exc), file=sys.stderr)
            return 3
        return 3  # pragma: no cover -- parse_binary_toolbox always raises for .tbx

    if source_format == SOURCE_FORMAT_ATBX:
        try:
            atbx = parse_atbx_toolbox(args.path)
        except UnsupportedModelFormatError as exc:
            print(str(exc), file=sys.stderr)
            return 3
        document = atbx.to_dict()
        manifest = build_atbx_translation_manifest(atbx)
        evidence = build_atbx_parity_evidence(atbx)
        parse_error = atbx.parse_error
    else:
        toolbox = parse_pyt_file(args.path)
        document = toolbox.to_dict()
        manifest = build_pyt_translation_manifest(toolbox)
        evidence = build_pyt_parity_evidence(toolbox)
        parse_error = toolbox.syntax_error

    if args.evidence is not None:
        _emit(evidence, out=args.evidence)

    attestation = _attest(manifest, args)
    document["translationManifest"] = manifest.to_dict()
    document["attestation"] = attestation.to_dict()
    _emit(document, out=args.output)

    if parse_error is not None:
        print(f"parse error: {parse_error}", file=sys.stderr)
        return 2
    return _report_attestation(attestation, args)


def _cmd_run(args: argparse.Namespace) -> int:
    # Imported lazily so scan/translate/pyt work without httpx/network deps wired.
    from honua_sdk import HonuaClient

    report = scan_arcpy_file(args.path)
    plan = translate_arcpy_report(report)
    # Only execute the steps the reconciled server can job-execute. Supported
    # but non-job-executable tools (manual-review) are reported as skipped.
    runnable = tuple(t for t in plan.translations if t.call.translatable)
    skipped = [c.qualified_name for c in plan.manual_review_calls]
    if not runnable:
        print("no translatable ArcPy calls to execute", file=sys.stderr)
        _emit({"executions": [], "skipped": skipped}, out=args.output)
        return 0

    if args.dry_run:
        _emit(
            {
                "dryRun": True,
                "server": args.server,
                "executions": [t.to_dict() for t in runnable],
                "skipped": skipped,
            },
            out=args.output,
        )
        return 0

    results: list[dict[str, Any]] = []
    with HonuaClient(args.server) as client:
        runner = ArcPyProcessRunner(client)
        for translation in runnable:
            execution = runner.execute(translation)
            results.append(
                {
                    "processId": execution.translation.process_id,
                    "jobProcessId": execution.translation.job_process_id,
                    "qualifiedName": execution.translation.call.qualified_name,
                    "result": execution.result,
                }
            )
    _emit({"server": args.server, "executions": results, "skipped": skipped}, out=args.output)
    return 0


def _cmd_pyt(args: argparse.Namespace) -> int:
    suffix = Path(args.path).suffix.lower()
    if suffix in _BINARY_TOOLBOX_SUFFIXES:
        try:
            parse_binary_toolbox(args.path)
        except UnsupportedToolboxError as exc:
            print(str(exc), file=sys.stderr)
            return 3

    toolbox = parse_pyt_file(args.path)
    if args.evidence is not None:
        _emit(build_pyt_parity_evidence(toolbox), out=args.evidence)

    document = toolbox.to_dict()
    attestation = _attest(build_pyt_translation_manifest(toolbox, source_format=SOURCE_FORMAT_PYT), args)
    document["attestation"] = attestation.to_dict()
    _emit(document, out=args.output)

    if toolbox.syntax_error is not None:
        print(f"syntax error: {toolbox.syntax_error}", file=sys.stderr)
        return 2
    return _report_attestation(attestation, args)


def _cmd_atbx(args: argparse.Namespace) -> int:
    try:
        toolbox = parse_atbx_toolbox(args.path)
    except UnsupportedModelFormatError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if args.evidence is not None:
        _emit(build_atbx_parity_evidence(toolbox), out=args.evidence)

    document = toolbox.to_dict()
    attestation = _attest(build_atbx_translation_manifest(toolbox, source_format=SOURCE_FORMAT_ATBX), args)
    document["attestation"] = attestation.to_dict()
    _emit(document, out=args.output)

    if toolbox.parse_error is not None:
        print(f"parse error: {toolbox.parse_error}", file=sys.stderr)
        return 2
    return _report_attestation(attestation, args)


def _cmd_gpservice(args: argparse.Namespace) -> int:
    text = Path(args.path).read_text(encoding="utf-8")
    try:
        service = parse_gp_service_definition(text, url=args.url)
    except (UnsupportedModelFormatError, json.JSONDecodeError) as exc:
        print(f"could not parse GP service definition: {exc}", file=sys.stderr)
        return 2
    if args.evidence is not None:
        _emit(build_gp_service_parity_evidence(service), out=args.evidence)
    _emit(service.to_dict(), out=args.output)
    return 0


def _add_attestation_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared ``--server`` attestation options to a toolbox command.

    Without ``--server`` the command stays fully offline and emits a report
    marked ``local-only``; a local verdict is never labelled attested.
    """

    group = parser.add_argument_group(
        "server attestation",
        "Have the server's canonical process catalog classify each tool, instead of "
        "relying on the SDK's local view of it. Requires the honua-admin package.",
    )
    group.add_argument(
        "--server",
        default=None,
        help=(
            "Honua server base URL to validate the translated toolbox against. "
            "Omit to stay offline (the report is then marked local-only)."
        ),
    )
    group.add_argument(
        "--api-key",
        default=None,
        help=f"Admin API key for --server (default: ${ADMIN_API_KEY_ENV}).",
    )
    group.add_argument(
        "--attest-timeout",
        type=float,
        default=30.0,
        help="Request timeout in seconds for the validation call (default: 30).",
    )
    group.add_argument(
        "--attestation",
        type=Path,
        default=None,
        help="Also write the attestation report JSON to this path.",
    )
    group.add_argument(
        "--require-attested",
        action="store_true",
        help=(
            f"Exit {EXIT_NOT_ATTESTED} when the verdict could not be server-attested, "
            "instead of accepting the local-only fallback."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honua-migrate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Classify ArcPy calls in a Python script (offline).")
    scan.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    scan.add_argument("--output", type=Path, default=None, help="Write JSON report to this path (default: stdout).")
    scan.set_defaults(func=_cmd_scan)

    translate = sub.add_parser(
        "translate",
        help=(
            "Translate an arcpy .py script or a .pyt/.atbx toolbox; emits OGC Processes "
            "payloads + parity evidence, and a server-attested verdict with --server."
        ),
    )
    translate.add_argument(
        "path",
        type=Path,
        help="Path to an arcpy .py script, a .pyt Python toolbox, or a .atbx ModelBuilder toolbox.",
    )
    translate.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the migration plan JSON here (default: stdout).",
    )
    translate.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Write the parity-evidence JSON report to this path.",
    )
    _add_attestation_arguments(translate)
    translate.set_defaults(func=_cmd_translate)

    run = sub.add_parser("run", help="Execute translatable steps via ArcPyProcessRunner against --server.")
    run.add_argument("path", type=Path, help="Path to an arcpy .py script.")
    run.add_argument("--server", required=True, help="Honua server base URL.")
    run.add_argument("--output", type=Path, default=None, help="Write execution results JSON here (default: stdout).")
    run.add_argument("--dry-run", action="store_true", help="Emit payloads without contacting the server.")
    run.set_defaults(func=_cmd_run)

    pyt = sub.add_parser("pyt", help="Parse a .pyt Python toolbox and classify its tools' GP calls.")
    pyt.add_argument("path", type=Path, help="Path to a .pyt Python toolbox (or .tbx to see the binary-format stub).")
    pyt.add_argument("--output", type=Path, default=None, help="Write the toolbox JSON here (default: stdout).")
    pyt.add_argument("--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here.")
    _add_attestation_arguments(pyt)
    pyt.set_defaults(func=_cmd_pyt)

    atbx = sub.add_parser(
        "atbx",
        help="Parse a .atbx ModelBuilder toolbox clean-room and classify its models' GP steps.",
    )
    atbx.add_argument("path", type=Path, help="Path to a .atbx ModelBuilder toolbox.")
    atbx.add_argument("--output", type=Path, default=None, help="Write the toolbox JSON here (default: stdout).")
    atbx.add_argument("--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here.")
    _add_attestation_arguments(atbx)
    atbx.set_defaults(func=_cmd_atbx)

    gpservice = sub.add_parser(
        "gpservice",
        help="Parse an ArcGIS REST GPServer service-definition JSON and classify its tasks (offline).",
    )
    gpservice.add_argument("path", type=Path, help="Path to a GPServer service-definition JSON (.../GPServer?f=json).")
    gpservice.add_argument("--url", default=None, help="Original service URL to record in the report.")
    gpservice.add_argument("--output", type=Path, default=None, help="Write the service JSON here (default: stdout).")
    gpservice.add_argument(
        "--evidence", type=Path, default=None, help="Write the aggregated parity-evidence JSON here."
    )
    gpservice.set_defaults(func=_cmd_gpservice)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code: int = args.func(args)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
