"""``honua`` command-line interface.

A thin, dependency-free (stdlib :mod:`argparse`) CLI that mirrors the core
browse/list/style surface of the JS ``@honua/sdk-js`` CLI on top of the
existing :class:`honua_sdk.HonuaClient`. It deliberately stays inside what the
data-plane client already supports and invents no server features.

Commands
--------
``honua services``
    Browse the GeoServices catalog (service / dataset browse). Mirrors the JS
    CLI service-explorer surface via :meth:`HonuaClient.list_service_summaries`.

``honua layers SERVICE_ID``
    List the layers and tables (sources) advertised by a FeatureServer's
    metadata document. Mirrors the JS layer / source listing via
    :meth:`HonuaClient.feature_server`.

``honua style apply SERVICE_ID``
    Render a MapServer ``export`` image applying a named renderer/style. This
    is the closest capability the data-plane client exposes to the JS CLI's
    ``style apply``; the bytes are written to ``--out`` (or stdout). It relies
    on :meth:`HonuaClient.export_map`.

``honua doctor``
    Emit or read-only replay a canonical, sanitized diagnostic bundle for local
    support review. It never uploads or persists raw HTTP traffic.

The base URL is read from ``--base-url`` or the ``HONUA_BASE_URL`` environment
variable; an optional API key from ``--api-key`` or ``HONUA_API_KEY``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import __version__
from .client import HonuaClient
from .diagnostics import (
    DIAGNOSTIC_SCHEMA_SHA256,
    DIAGNOSTIC_SCHEMA_URL,
    DiagnosticError,
    assert_diagnostic_bundle,
    create_diagnostic_bundle,
    probe_capabilities,
    replay_diagnostic_bundle,
)
from .errors import HonuaError

if TYPE_CHECKING:
    from .models import ServiceSummary

_ENV_BASE_URL = "HONUA_BASE_URL"
_ENV_API_KEY = "HONUA_API_KEY"
_MAX_DIAGNOSTIC_INPUT_BYTES = 30 * 1024 * 1024


class _DoctorCliError(ValueError):
    """Safe command error whose message contains no captured input."""


def _resolve_base_url(args: argparse.Namespace) -> str:
    base_url = args.base_url or os.environ.get(_ENV_BASE_URL)
    if not base_url:
        raise SystemExit(
            f"error: a base URL is required (pass --base-url or set {_ENV_BASE_URL})",
        )
    return base_url


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    return args.api_key or os.environ.get(_ENV_API_KEY)


def _make_client(args: argparse.Namespace) -> HonuaClient:
    return HonuaClient(_resolve_base_url(args), api_key=_resolve_api_key(args))


def _emit_json(payload: Any, out: Any) -> None:
    json.dump(payload, out, indent=2, default=str)
    out.write("\n")


def _service_rows(summaries: Sequence[ServiceSummary]) -> list[dict[str, Any]]:
    return [{"name": s.name, "type": s.type, "url": s.url} for s in summaries]


def _print_table(rows: Sequence[dict[str, Any]], columns: Sequence[str], out: Any) -> None:
    if not rows:
        out.write("(no entries)\n")
        return
    widths = {col: len(col) for col in columns}
    for row in rows:
        for col in columns:
            widths[col] = max(widths[col], len(str(row.get(col, "") or "")))
    header = "  ".join(col.ljust(widths[col]) for col in columns)
    out.write(header.rstrip() + "\n")
    out.write("  ".join("-" * widths[col] for col in columns) + "\n")
    for row in rows:
        out.write("  ".join(str(row.get(col, "") or "").ljust(widths[col]) for col in columns).rstrip() + "\n")


def _layer_rows(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in ("layers", "tables"):
        for entry in metadata.get(kind) or []:
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "type": entry.get("type") or ("Table" if kind == "tables" else None),
                    "geometryType": entry.get("geometryType"),
                }
            )
    return rows


def _cmd_services(args: argparse.Namespace, out: Any) -> int:
    with _make_client(args) as client:
        summaries = client.list_service_summaries()
    rows = _service_rows(summaries)
    if args.format == "table":
        _print_table(rows, ["name", "type", "url"], out)
    else:
        _emit_json(rows, out)
    return 0


def _cmd_layers(args: argparse.Namespace, out: Any) -> int:
    with _make_client(args) as client:
        metadata = client.feature_server(args.service_id).metadata()
    rows = _layer_rows(metadata)
    if args.format == "table":
        _print_table(rows, ["id", "name", "type", "geometryType"], out)
    else:
        _emit_json(rows, out)
    return 0


def _cmd_style_apply(args: argparse.Namespace, out: Any) -> int:
    extra_params: dict[str, Any] = {}
    if args.style is not None:
        # MapServer/dynamicLayers carry the named renderer; forward it verbatim
        # so the server applies the style during rendering.
        extra_params["style"] = args.style
    if args.layers is not None:
        extra_params["layers"] = args.layers
    with _make_client(args) as client:
        image = client.export_map(
            args.service_id,
            args.bbox,
            image_format=args.image_format,
            extra_params=extra_params or None,
        )
    if args.out is None or args.out == "-":
        sys.stdout.buffer.write(image)
    else:
        with open(args.out, "wb") as handle:
            handle.write(image)
        out.write(f"wrote {len(image)} bytes to {args.out}\n")
    return 0


def _cmd_doctor(args: argparse.Namespace, out: Any) -> int:
    if args.replay:
        if args.exchange:
            raise _DoctorCliError("doctor accepts either --replay or --exchange, not both")
        base_url = args.base_url or os.environ.get(_ENV_BASE_URL)
        if not base_url:
            raise _DoctorCliError("doctor replay requires --base-url or HONUA_BASE_URL")
        source_bundle = _read_diagnostic_json(args.replay)
        assert_diagnostic_bundle(source_bundle)
        replayed = replay_diagnostic_bundle(source_bundle, base_url, timeout=args.timeout)
        _write_diagnostic_bundle_safe(args.output, replayed)
        _emit_doctor_result(out, replayed, outcome="replayed", capability_probe="not-applicable")
        return 0

    if args.classification is None or args.redaction_acknowledged is None or args.share_with_support is None:
        raise _DoctorCliError("doctor emission requires classification and both explicit consent values")
    exchanges: list[dict[str, Any]] = []
    base_url = args.base_url or os.environ.get(_ENV_BASE_URL)
    if base_url:
        exchanges.append(probe_capabilities(base_url, timeout=args.timeout))
    if args.exchange:
        exchanges.append(_captured_exchange(_read_diagnostic_json(args.exchange)))
    if not exchanges:
        raise _DoctorCliError("doctor requires --base-url/HONUA_BASE_URL or --exchange")

    bundle = create_diagnostic_bundle(
        content_classification=args.classification,
        redaction_acknowledged=_explicit_bool(args.redaction_acknowledged),
        share_with_support=_explicit_bool(args.share_with_support),
        exchanges=exchanges,
        bundle_id=args.bundle_id,
        granted_by=args.granted_by,
    )
    _write_diagnostic_bundle_safe(args.output, bundle)
    _emit_doctor_result(
        out,
        bundle,
        outcome="emitted",
        capability_probe="attempted" if base_url else "not-configured",
    )
    return 0


def _emit_doctor_result(
    out: Any,
    bundle: Mapping[str, Any],
    *,
    outcome: str,
    capability_probe: str,
) -> None:
    result = {
        "format": "honua.doctor-result.v1",
        "outcome": outcome,
        "outputWritten": True,
        "envelopeCount": len(bundle["envelopes"]),
        "capabilityProbe": capability_probe,
        "runtime": {"python": platform.python_version(), "platform": sys.platform},
        "sdk": {"package": "honua-sdk", "version": __version__},
        "schema": DIAGNOSTIC_SCHEMA_URL,
        "schemaSha256": DIAGNOSTIC_SCHEMA_SHA256,
        "uploaded": False,
    }
    _emit_json(result, out)


def _read_diagnostic_json(path: str) -> object:
    try:
        source = Path(path)
        size = source.stat().st_size
        if not source.is_file() or size > _MAX_DIAGNOSTIC_INPUT_BYTES:
            raise _DoctorCliError("diagnostic input is not a regular file or exceeds 30 MiB")
        with source.open(encoding="utf-8") as handle:
            return json.load(handle)
    except _DoctorCliError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _DoctorCliError("diagnostic input could not be read as JSON") from exc


def _captured_exchange(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _DoctorCliError("captured exchange must be a JSON object")
    request = value.get("request")
    response = value.get("response")
    if not isinstance(request, dict):
        raise _DoctorCliError("captured exchange requires a request object")
    method = request.get("method")
    url = request.get("url")
    if not isinstance(method, str) or not isinstance(url, str):
        raise _DoctorCliError("captured exchange requires request.method and request.url strings")
    exchange: dict[str, Any] = {"method": method, "url": url}
    if "headers" in request:
        exchange["requestHeaders"] = request["headers"]
    if "body" in request:
        exchange["requestBody"] = request["body"]
    if response is not None:
        _copy_captured_response(response, exchange)
    for name in ("correlationId", "traceId", "capturedAt"):
        if name in value:
            exchange[name] = value[name]
    return exchange


def _copy_captured_response(value: object, exchange: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise _DoctorCliError("captured response must be a JSON object")
    status = value.get("statusCode", value.get("status"))
    if status is not None:
        exchange["statusCode"] = status
    for source_name, target_name in (
        ("mediaType", "mediaType"),
        ("headers", "responseHeaders"),
        ("body", "responseBody"),
    ):
        if source_name in value:
            exchange[target_name] = value[source_name]


def _write_diagnostic_bundle(path: str, bundle: object) -> None:
    assert_diagnostic_bundle(bundle)
    serialized = json.dumps(bundle, indent=2, sort_keys=True) + "\n"
    assert_diagnostic_bundle(json.loads(serialized))
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            with contextlib.suppress(AttributeError, OSError):
                os.fchmod(handle.fileno(), 0o600)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        with contextlib.suppress(OSError):
            destination.chmod(0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _write_diagnostic_bundle_safe(path: str, bundle: object) -> None:
    try:
        _write_diagnostic_bundle(path, bundle)
    except OSError as exc:
        raise _DoctorCliError("diagnostic output could not be written safely") from exc


def _explicit_bool(value: str) -> bool:
    if value not in {"true", "false"}:
        raise _DoctorCliError("doctor consent values must be explicitly true or false")
    return value == "true"


def _add_common_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"Honua server base URL (or set {_ENV_BASE_URL}).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=f"API key for authentication (or set {_ENV_API_KEY}).",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``honua`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="honua",
        description="Command-line interface for the Honua geospatial platform.",
    )
    parser.add_argument("--version", action="version", version=f"honua {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # honua services
    services = subparsers.add_parser(
        "services",
        help="List services in the GeoServices catalog (service/dataset browse).",
    )
    _add_common_connection_args(services)
    services.add_argument("--format", choices=("json", "table"), default="json")
    services.set_defaults(func=_cmd_services)

    # honua layers SERVICE_ID
    layers = subparsers.add_parser(
        "layers",
        help="List a FeatureServer's layers and tables (layer/source list).",
    )
    _add_common_connection_args(layers)
    layers.add_argument("service_id", help="Catalog service identifier.")
    layers.add_argument("--format", choices=("json", "table"), default="json")
    layers.set_defaults(func=_cmd_layers)

    # honua style apply SERVICE_ID
    style = subparsers.add_parser("style", help="Style operations.")
    style_sub = style.add_subparsers(dest="style_command", metavar="<subcommand>")
    style_apply = style_sub.add_parser(
        "apply",
        help="Render a map applying a named style (MapServer export).",
    )
    _add_common_connection_args(style_apply)
    style_apply.add_argument("service_id", help="Catalog service identifier.")
    style_apply.add_argument(
        "--bbox",
        required=True,
        help="Bounding box 'xmin,ymin,xmax,ymax'.",
    )
    style_apply.add_argument(
        "--style",
        default=None,
        help="Named style / renderer to apply during rendering.",
    )
    style_apply.add_argument(
        "--layers",
        default=None,
        help="Optional layers selector forwarded to the export request.",
    )
    style_apply.add_argument("--image-format", default="png", help="Output image format (default: png).")
    style_apply.add_argument(
        "--out",
        default=None,
        help="Output file path for the rendered image ('-' or omit for stdout).",
    )
    style_apply.set_defaults(func=_cmd_style_apply)
    style.set_defaults(func=_dispatch_style)

    # honua doctor
    doctor = subparsers.add_parser(
        "doctor",
        help="Write a local sanitized diagnostic-bundle.v1 support artifact.",
        description="Write a local sanitized diagnostic-bundle.v1 support artifact; the command never uploads.",
    )
    doctor.add_argument("--base-url", default=None, help=f"Anonymous capability probe URL (or {_ENV_BASE_URL}).")
    doctor.add_argument("--exchange", default=None, help="Captured failing exchange JSON read only in memory.")
    doctor.add_argument("--replay", default=None, help="Validated bundle to replay as one anonymous GET/HEAD.")
    doctor.add_argument(
        "--classification",
        required=False,
        choices=("unknown", "public", "internal", "customer-data", "secret-suspected"),
    )
    doctor.add_argument("--redaction-acknowledged", required=False, choices=("true", "false"))
    doctor.add_argument("--share-with-support", required=False, choices=("true", "false"))
    doctor.add_argument("--granted-by", default=None)
    doctor.add_argument("--bundle-id", default=None)
    doctor.add_argument("--timeout", type=float, default=10.0)
    doctor.add_argument("--output", required=True, help="Destination JSON file. The command never uploads.")
    doctor.set_defaults(func=_cmd_doctor)

    return parser


def _dispatch_style(args: argparse.Namespace, out: Any) -> int:
    # ``honua style`` with no subcommand: show help for the style group.
    out.write("error: 'style' requires a subcommand (apply)\n")
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``honua`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        result = func(args, sys.stdout)
    except SystemExit:
        raise
    except HonuaError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except (DiagnosticError, _DoctorCliError):
        sys.stderr.write("error: doctor refused unsafe or invalid diagnostic input\n")
        return 1
    return int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
