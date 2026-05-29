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

The base URL is read from ``--base-url`` or the ``HONUA_BASE_URL`` environment
variable; an optional API key from ``--api-key`` or ``HONUA_API_KEY``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from . import __version__
from .client import HonuaClient
from .errors import HonuaError

if TYPE_CHECKING:
    from .models import ServiceSummary

_ENV_BASE_URL = "HONUA_BASE_URL"
_ENV_API_KEY = "HONUA_API_KEY"


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
    return int(result)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
