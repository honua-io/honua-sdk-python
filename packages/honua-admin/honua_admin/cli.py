"""``honua-admin`` command-line interface for the operator workflow.

A thin, dependency-free (stdlib :mod:`argparse`) CLI over
:class:`honua_admin.HonuaAdminClient`. Every command is one typed client call;
the CLI adds no HTTP of its own. The same command groups are mounted on the
``honua`` console script (``honua datasource ...``) when ``honua-admin`` is
installed.

Commands
--------
``datasource list | create | test``
    Secure datasource connections (``list_connections``,
    ``create_connection``, ``test_connection``). ``create`` never takes a
    password on the command line: use ``--password-env``, ``--password-stdin``,
    ``--secret-reference`` or a ``--body`` file.

``layer list | publish | unpublish | enable``
    Published layers of a connection (``list_layers``, ``publish_layer``,
    ``set_layer_enabled``). ``unpublish`` (alias ``disable``) turns a layer off
    so its data-plane URLs stop serving.

``proposal list | read | approve | reject``
    Guardrail-routed operation proposals (``list_proposals``, ``get_proposal``,
    ``approve_proposal``, ``reject_proposal``). Proposals are raised by the
    agent surface (the MCP ``honua_publish_service`` tool for a governed
    principal); the server has no REST call to submit one. ``read --wait``
    polls until the proposal reaches a terminal status.

Output and exit codes
---------------------
``--json`` prints the server-shaped JSON object (camelCase keys) on stdout;
without it a short table or ``key: value`` listing is printed. Exit ``0`` on
success; ``1`` when the server or transport refuses the call (stderr carries
``error: HTTP <status>: <message>``), when ``datasource test`` reports an
unhealthy connection, or when ``proposal read --wait`` times out; ``2`` for a
usage error.

The base URL is read from ``--base-url`` or ``HONUA_BASE_URL``; the key from
``--api-key``, ``HONUA_ADMIN_KEY`` or ``HONUA_API_KEY`` (first set wins).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, TextIO

from honua_sdk.errors import HonuaError

from . import __version__
from ._client import HonuaAdminClient
from ._models import (
    CreateSecureConnectionRequest,
    PublishLayerRequest,
    _camel_keys,
    _snake_keys,
)

_ENV_BASE_URL = "HONUA_BASE_URL"
_ENV_ADMIN_KEY = "HONUA_ADMIN_KEY"
_ENV_API_KEY = "HONUA_API_KEY"
_MAX_BODY_BYTES = 1024 * 1024
TERMINAL_PROPOSAL_STATUSES = frozenset({"Succeeded", "Failed", "Rejected", "RolledBack", "Cancelled"})
_POLL_INTERVAL_SECONDS = 1.0

Command = Callable[[argparse.Namespace, TextIO], int]


class CliUsageError(ValueError):
    """An operator input error; reported on stderr with exit code 2."""


# -- connection --------------------------------------------------------------


def _resolve_base_url(args: argparse.Namespace) -> str:
    base_url: str | None = args.base_url or os.environ.get(_ENV_BASE_URL)
    if not base_url:
        raise CliUsageError(f"a base URL is required (pass --base-url or set {_ENV_BASE_URL})")
    return base_url


def _resolve_api_key(args: argparse.Namespace) -> str | None:
    key: str | None = args.api_key or os.environ.get(_ENV_ADMIN_KEY) or os.environ.get(_ENV_API_KEY)
    return key


def _make_client(args: argparse.Namespace) -> HonuaAdminClient:
    return HonuaAdminClient(_resolve_base_url(args), api_key=_resolve_api_key(args), timeout=args.timeout)


# -- output ------------------------------------------------------------------


def _record(model: Any) -> dict[str, Any]:
    return _camel_keys(dataclasses.asdict(model))


def _emit_json(payload: Any, out: TextIO) -> None:
    json.dump(payload, out, indent=2, default=str)
    out.write("\n")


def _emit_record(model: Any, args: argparse.Namespace, out: TextIO) -> None:
    record = _record(model)
    if args.json:
        _emit_json(record, out)
        return
    for key, value in record.items():
        if value is None or value == []:
            continue
        out.write(f"{key}: {', '.join(value) if isinstance(value, list) else value}\n")


def _emit_rows(models: Sequence[Any], columns: Sequence[str], args: argparse.Namespace, out: TextIO) -> None:
    rows = [_record(model) for model in models]
    if args.json:
        _emit_json(rows, out)
        return
    if not rows:
        out.write("(no entries)\n")
        return
    widths = {col: max(len(col), *(len(_cell(row.get(col))) for row in rows)) for col in columns}
    out.write("  ".join(col.ljust(widths[col]) for col in columns).rstrip() + "\n")
    out.write("  ".join("-" * widths[col] for col in columns) + "\n")
    for row in rows:
        out.write("  ".join(_cell(row.get(col)).ljust(widths[col]) for col in columns).rstrip() + "\n")


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


# -- request bodies ----------------------------------------------------------


def _read_body(path: str | None) -> dict[str, Any]:
    """Read a JSON object from ``path`` (``-`` is stdin) with snake_case keys."""
    if path is None:
        return {}
    try:
        if path == "-":
            text = _read_stdin_body()
        else:
            source = Path(path.removeprefix("@"))
            if source.stat().st_size > _MAX_BODY_BYTES:
                raise CliUsageError("--body file exceeds 1 MiB")
            text = source.read_text(encoding="utf-8")
        payload = json.loads(text)
    except CliUsageError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CliUsageError("--body must name a readable JSON file ('-' for stdin)") from exc
    if not isinstance(payload, dict):
        raise CliUsageError("--body must contain a JSON object")
    return _snake_keys(payload)


def _read_stdin_body() -> str:
    """Read at most 1 MiB of raw stdin bytes, then decode, so the limit matches ``--body FILE``."""
    stream = getattr(sys.stdin, "buffer", None)
    if stream is None:  # a text-only replacement stream (embedding, tests): measure its encoded size
        text = str(sys.stdin.read(_MAX_BODY_BYTES + 1))
        if len(text.encode("utf-8")) > _MAX_BODY_BYTES:
            raise CliUsageError("--body stdin exceeds 1 MiB")
        return text
    raw = stream.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        raise CliUsageError("--body stdin exceeds 1 MiB")
    return bytes(raw).decode("utf-8")


def _build(model: type[Any], body: Mapping[str, Any], overrides: Mapping[str, Any]) -> Any:
    values = {**body, **{key: value for key, value in overrides.items() if value is not None}}
    known = {f.name for f in dataclasses.fields(model)}
    unknown = sorted(set(values) - known)
    if unknown:
        raise CliUsageError(f"unknown field(s) in --body: {', '.join(unknown)}")
    try:
        return model(**values)
    except TypeError as exc:
        raise CliUsageError(f"incomplete request: {exc}") from exc


def _password(args: argparse.Namespace) -> str | None:
    if args.password_env and args.password_stdin:
        raise CliUsageError("use either --password-env or --password-stdin, not both")
    if args.password_env:
        value = os.environ.get(args.password_env)
        if value is None:
            raise CliUsageError(f"environment variable {args.password_env} is not set")
        return value
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    return None


# -- datasource --------------------------------------------------------------


def _cmd_datasource_list(args: argparse.Namespace, out: TextIO) -> int:
    with _make_client(args) as client:
        connections = client.list_connections()
    _emit_rows(connections, ["connectionId", "name", "host", "databaseName", "healthStatus"], args, out)
    return 0


def _cmd_datasource_create(args: argparse.Namespace, out: TextIO) -> int:
    if args.password_stdin and args.body == "-":
        raise CliUsageError("--password-stdin and --body - both read stdin; put the password in the body instead")
    body = _read_body(args.body)
    overrides = {
        "name": args.name,
        "description": args.description,
        "host": args.host,
        "port": args.port,
        "database_name": args.database,
        "username": args.username,
        "password": _password(args),
        "secret_reference": args.secret_reference,
        "secret_type": args.secret_type,
        "ssl_required": True if args.ssl_required else None,
        "ssl_mode": args.ssl_mode,
    }
    request = _build(CreateSecureConnectionRequest, body, overrides)
    with _make_client(args) as client:
        created = client.create_connection(request)
    _emit_record(created, args, out)
    return 0


def _cmd_datasource_test(args: argparse.Namespace, out: TextIO) -> int:
    with _make_client(args) as client:
        result = client.test_connection(args.connection_id)
    _emit_record(result, args, out)
    return 0 if result.is_healthy else 1


# -- layer -------------------------------------------------------------------


def _cmd_layer_list(args: argparse.Namespace, out: TextIO) -> int:
    with _make_client(args) as client:
        layers = client.list_layers(args.connection_id, args.service_name)
    _emit_rows(layers, ["layerId", "layerName", "serviceName", "table", "enabled"], args, out)
    return 0


def _cmd_layer_publish(args: argparse.Namespace, out: TextIO) -> int:
    body = _read_body(args.body)
    if "fields" in body:
        body["fields_list"] = body.pop("fields")
    overrides = {
        "schema": args.schema,
        "table": args.table,
        "layer_name": args.layer_name,
        "description": args.description,
        "geometry_column": args.geometry_column,
        "geometry_type": args.geometry_type,
        "srid": args.srid,
        "primary_key": args.primary_key,
        "fields_list": args.field,
        "service_name": args.service_name,
        "enabled": False if args.disabled else None,
    }
    request = _build(PublishLayerRequest, body, overrides)
    if not request.table:
        raise CliUsageError("a table is required (pass --table or set it in --body)")
    with _make_client(args) as client:
        published = client.publish_layer(args.connection_id, request)
    _emit_record(published, args, out)
    return 0


def _set_enabled(args: argparse.Namespace, out: TextIO, *, enabled: bool) -> int:
    with _make_client(args) as client:
        summary = client.set_layer_enabled(args.connection_id, args.layer_id, enabled, args.service_name)
    _emit_record(summary, args, out)
    return 0


def _cmd_layer_unpublish(args: argparse.Namespace, out: TextIO) -> int:
    return _set_enabled(args, out, enabled=False)


def _cmd_layer_enable(args: argparse.Namespace, out: TextIO) -> int:
    return _set_enabled(args, out, enabled=True)


# -- proposal ----------------------------------------------------------------


def _cmd_proposal_list(args: argparse.Namespace, out: TextIO) -> int:
    with _make_client(args) as client:
        proposals = client.list_proposals(status=args.status, kind=args.kind, requested_by=args.requested_by)
    _emit_rows(proposals, ["proposalId", "kind", "status", "requestedBy", "summary"], args, out)
    return 0


def _cmd_proposal_read(args: argparse.Namespace, out: TextIO) -> int:
    if not math.isfinite(args.wait_timeout) or args.wait_timeout < 0:
        raise CliUsageError("--wait-timeout must be a finite, non-negative number of seconds")
    deadline = time.monotonic() + args.wait_timeout
    with _make_client(args) as client:
        proposal = client.get_proposal(args.proposal_id)
        while args.wait and proposal.status not in TERMINAL_PROPOSAL_STATUSES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))
            if time.monotonic() >= deadline:
                break
            proposal = client.get_proposal(args.proposal_id)
    _emit_record(proposal, args, out)
    if args.wait and proposal.status not in TERMINAL_PROPOSAL_STATUSES:
        sys.stderr.write(
            f"error: proposal {args.proposal_id} is still {proposal.status} after {args.wait_timeout:g}s\n"
        )
        return 1
    return 0


def _cmd_proposal_approve(args: argparse.Namespace, out: TextIO) -> int:
    with _make_client(args) as client:
        proposal = client.approve_proposal(args.proposal_id)
    _emit_record(proposal, args, out)
    return 0


def _cmd_proposal_reject(args: argparse.Namespace, out: TextIO) -> int:
    if not args.reason.strip():
        raise CliUsageError("--reason must not be blank")
    with _make_client(args) as client:
        proposal = client.reject_proposal(args.proposal_id, args.reason)
    _emit_record(proposal, args, out)
    return 0


# -- parser ------------------------------------------------------------------


def _common(parser: argparse.ArgumentParser, func: Command) -> argparse.ArgumentParser:
    parser.add_argument("--base-url", default=None, help=f"Honua server base URL (or set {_ENV_BASE_URL}).")
    parser.add_argument(
        "--api-key",
        default=None,
        help=f"Admin API key (or set {_ENV_ADMIN_KEY}, then {_ENV_API_KEY}).",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds (default: 30).")
    parser.add_argument("--json", action="store_true", help="Print the server-shaped JSON result.")
    parser.set_defaults(func=_guarded(func))
    return parser


def _guarded(func: Command) -> Command:
    """Report :class:`CliUsageError` as a usage failure (exit 2) instead of a traceback."""

    def run(args: argparse.Namespace, out: TextIO) -> int:
        try:
            return func(args, out)
        except CliUsageError as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 2

    return run


def _group_help(parser: argparse.ArgumentParser) -> Command:
    def run(_args: argparse.Namespace, _out: TextIO) -> int:
        parser.print_help(sys.stderr)
        return 2

    return run


def _add_datasource(subparsers: Any) -> None:
    group = subparsers.add_parser("datasource", help="Create, test and list secure datasource connections.")
    sub = group.add_subparsers(dest="datasource_command", metavar="<subcommand>")
    group.set_defaults(func=_group_help(group))

    _common(sub.add_parser("list", help="List datasource connections."), _cmd_datasource_list)

    create = _common(
        sub.add_parser(
            "create",
            help="Create a PostGIS datasource connection.",
            description="Create a datasource connection. Passwords are never accepted on the command line.",
        ),
        _cmd_datasource_create,
    )
    create.add_argument("--name", default=None, help="Connection name.")
    create.add_argument("--description", default=None)
    create.add_argument("--host", default=None, help="Database host.")
    create.add_argument("--port", type=int, default=None, help="Database port (default: 5432).")
    create.add_argument("--database", default=None, help="Database name.")
    create.add_argument("--username", default=None, help="Database user.")
    create.add_argument("--password-env", default=None, metavar="VAR", help="Read the password from env var VAR.")
    create.add_argument("--password-stdin", action="store_true", help="Read the password from the first stdin line.")
    create.add_argument("--secret-reference", default=None, help="Server-side secret reference instead of a password.")
    create.add_argument("--secret-type", default=None)
    create.add_argument("--ssl-required", action="store_true")
    create.add_argument("--ssl-mode", default=None, help="Npgsql SSL mode, e.g. Disable, Require, VerifyFull.")
    create.add_argument(
        "--body",
        default=None,
        metavar="FILE",
        help="JSON request body (camelCase or snake_case keys; '-' for stdin); flags override its fields.",
    )

    test = _common(sub.add_parser("test", help="Test a stored connection; exit 1 if unhealthy."), _cmd_datasource_test)
    test.add_argument("connection_id", help="Connection identifier.")


def _add_layer(subparsers: Any) -> None:
    group = subparsers.add_parser("layer", help="Publish, list and unpublish a connection's layers.")
    sub = group.add_subparsers(dest="layer_command", metavar="<subcommand>")
    group.set_defaults(func=_group_help(group))

    listing = _common(sub.add_parser("list", help="List a connection's published layers."), _cmd_layer_list)
    listing.add_argument("connection_id", help="Connection identifier.")
    listing.add_argument("--service-name", default=None, help="Restrict to one service.")

    publish = _common(sub.add_parser("publish", help="Publish a table as a layer."), _cmd_layer_publish)
    publish.add_argument("connection_id", help="Connection identifier.")
    publish.add_argument("--table", default=None, help="Source table.")
    publish.add_argument("--schema", default=None, help="Source schema (default: public).")
    publish.add_argument("--layer-name", default=None)
    publish.add_argument("--service-name", default=None, help="Service to publish into.")
    publish.add_argument("--description", default=None)
    publish.add_argument("--geometry-column", default=None)
    publish.add_argument("--geometry-type", default=None, help="e.g. Point, LineString, Polygon.")
    publish.add_argument("--srid", type=int, default=None)
    publish.add_argument("--primary-key", default=None)
    publish.add_argument("--field", action="append", default=None, help="Field to expose (repeatable).")
    publish.add_argument("--disabled", action="store_true", help="Publish the layer disabled.")
    publish.add_argument(
        "--body",
        default=None,
        metavar="FILE",
        help="JSON request body (camelCase or snake_case keys; '-' for stdin); flags override its fields.",
    )

    for name, aliases, func, text in (
        ("unpublish", ["disable"], _cmd_layer_unpublish, "Disable a published layer (stop serving it)."),
        ("enable", [], _cmd_layer_enable, "Re-enable a disabled layer."),
    ):
        toggle = _common(sub.add_parser(name, aliases=aliases, help=text), func)
        toggle.add_argument("connection_id", help="Connection identifier.")
        toggle.add_argument("layer_id", type=int, help="Numeric layer identifier.")
        toggle.add_argument("--service-name", default=None, help="Service that owns the layer.")


def _add_proposal(subparsers: Any) -> None:
    group = subparsers.add_parser("proposal", help="Read, approve and reject operation proposals.")
    sub = group.add_subparsers(dest="proposal_command", metavar="<subcommand>")
    group.set_defaults(func=_group_help(group))

    listing = _common(sub.add_parser("list", help="List operation proposals."), _cmd_proposal_list)
    listing.add_argument("--status", default=None, help="Lifecycle filter, e.g. AwaitingApproval.")
    listing.add_argument("--kind", default=None, help="Operation-class filter, e.g. AdminConfigChange.")
    listing.add_argument("--requested-by", default=None, help="Requesting principal filter.")

    read = _common(sub.add_parser("read", help="Read one proposal."), _cmd_proposal_read)
    read.add_argument("proposal_id", help="Proposal identifier.")
    read.add_argument("--wait", action="store_true", help="Poll until the status is terminal.")
    read.add_argument("--wait-timeout", type=float, default=120.0, help="Seconds to wait with --wait (default: 120).")

    approve = _common(sub.add_parser("approve", help="Approve a proposal (not your own)."), _cmd_proposal_approve)
    approve.add_argument("proposal_id", help="Proposal identifier.")

    reject = _common(sub.add_parser("reject", help="Reject a proposal with a reason."), _cmd_proposal_reject)
    reject.add_argument("proposal_id", help="Proposal identifier.")
    reject.add_argument("--reason", required=True, help="Rejection reason recorded on the proposal.")


def add_operator_commands(subparsers: Any) -> None:
    """Mount the ``datasource``, ``layer`` and ``proposal`` groups on ``subparsers``.

    Each leaf parser sets ``func(args, out) -> int``. The ``honua`` console
    script calls this so both programs expose the same commands.
    """
    _add_datasource(subparsers)
    _add_layer(subparsers)
    _add_proposal(subparsers)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``honua-admin`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="honua-admin",
        description="Operator commands for the Honua control plane: datasources, layers and proposals.",
    )
    parser.add_argument("--version", action="version", version=f"honua-admin {__version__}")
    add_operator_commands(parser.add_subparsers(dest="command", metavar="<command>"))
    return parser


def run_command(args: argparse.Namespace, out: TextIO) -> int:
    """Run a parsed command; server and transport refusals exit ``1``."""
    try:
        return int(args.func(args, out))
    except HonuaError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``honua-admin`` console script."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 2
    return run_command(args, sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
