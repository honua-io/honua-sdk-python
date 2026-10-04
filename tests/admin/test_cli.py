"""Tests for the ``honua-admin`` operator CLI (honua-sdk-python#258).

Every command runs through :func:`honua_admin.cli.main` against an in-memory
admin server behind :class:`httpx.MockTransport`, so the argument parsing,
the typed client call, the wire request, the stdout shape and the exit code are
all exercised together.
"""

from __future__ import annotations

import argparse
import io
import json
import re
from typing import Any

import httpx
import pytest

from honua_admin import HonuaAdminClient, OperationProposalDetail, OperationProposalSummary
from honua_admin import cli

from .conftest import make_api_response

BASE = "http://admin.test"
ROOT_KEY = "root-key"
PROPOSER_KEY = "proposer-key"
APPROVER_KEY = "approver-key"


class FakeAdminServer:
    """Just enough of the admin API to run the operator workflow."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.connections: dict[str, dict[str, Any]] = {}
        self.layers: dict[str, list[dict[str, Any]]] = {}
        self.healthy = True
        self.reads_until_terminal = 1
        self.proposals: dict[str, dict[str, Any]] = {
            "prop-1": self._proposal("prop-1", requested_by="proposer"),
        }

    @staticmethod
    def _proposal(proposal_id: str, *, requested_by: str) -> dict[str, Any]:
        return {
            "proposalId": proposal_id,
            "kind": "AdminConfigChange",
            "status": "AwaitingApproval",
            "requestedBy": requested_by,
            "summary": "Publish service proposal_sites",
            "diff": ["+ layer proposal_sites"],
            "dryRun": [],
            "riskLevel": "Medium",
            "blockingReasons": [],
            "warnings": [],
            "guardrailTier": "Approval",
            "createdAt": "2026-10-04T00:00:00Z",
            "updatedAt": "2026-10-04T00:00:00Z",
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1/admin")
        key = request.headers.get("X-API-Key")
        body = json.loads(request.content) if request.content else None
        for pattern, handler in self._routes():
            match = re.fullmatch(pattern, f"{request.method} {path}")
            if match:
                return handler(key, body, request, *match.groups())
        return httpx.Response(404, json={"title": "Not Found"})

    def _routes(self) -> list[tuple[str, Any]]:
        return [
            (r"GET /connections", self._list_connections),
            (r"POST /connections", self._create_connection),
            (r"POST /connections/([^/]+)/test", self._test_connection),
            (r"GET /connections/([^/]+)/layers", self._list_layers),
            (r"POST /connections/([^/]+)/layers", self._publish_layer),
            (r"PUT /connections/([^/]+)/layers/(\d+)/enabled", self._set_enabled),
            (r"GET /proposals", self._list_proposals),
            (r"GET /proposals/([^/]+)", self._get_proposal),
            (r"POST /proposals/([^/]+)/approve", self._approve),
            (r"POST /proposals/([^/]+)/reject", self._reject),
        ]

    def _list_connections(self, *_: Any) -> httpx.Response:
        return httpx.Response(200, json=make_api_response(list(self.connections.values())))

    def _create_connection(self, _key: Any, body: dict[str, Any], *_: Any) -> httpx.Response:
        connection_id = f"conn-{len(self.connections) + 1}"
        summary = {
            "connectionId": connection_id,
            "name": body["name"],
            "description": body.get("description"),
            "host": body["host"],
            "port": body["port"],
            "databaseName": body["databaseName"],
            "username": body["username"],
            "sslRequired": body["sslRequired"],
            "sslMode": body.get("sslMode"),
            "storageType": "Encrypted",
            "isActive": True,
            "healthStatus": "Unknown",
            "lastHealthCheck": None,
            "createdAt": "2026-10-04T00:00:00Z",
            "createdBy": "root",
        }
        self.connections[connection_id] = summary
        return httpx.Response(201, json=make_api_response(summary))

    def _test_connection(self, _key: Any, _body: Any, _request: Any, connection_id: str) -> httpx.Response:
        if connection_id not in self.connections:
            return httpx.Response(404, json={"title": "Not Found"})
        return httpx.Response(
            200,
            json=make_api_response(
                {
                    "connectionId": connection_id,
                    "connectionName": self.connections[connection_id]["name"],
                    "isHealthy": self.healthy,
                    "testedAt": "2026-10-04T00:00:01Z",
                    "message": "ok" if self.healthy else "password authentication failed",
                }
            ),
        )

    def _list_layers(self, _key: Any, _body: Any, request: httpx.Request, connection_id: str) -> httpx.Response:
        service = request.url.params.get("serviceName")
        rows = [row for row in self.layers.get(connection_id, []) if service in (None, row["serviceName"])]
        return httpx.Response(200, json=make_api_response(rows))

    def _publish_layer(self, _key: Any, body: dict[str, Any], _request: Any, connection_id: str) -> httpx.Response:
        rows = self.layers.setdefault(connection_id, [])
        layer = {
            "layerId": len(rows) + 1,
            "layerName": body.get("layerName") or body["table"],
            "schema": body["schema"],
            "table": body["table"],
            "description": body.get("description"),
            "geometryType": body.get("geometryType"),
            "srid": body.get("srid"),
            "primaryKey": body.get("primaryKey"),
            "fieldCount": len(body.get("fields") or []) or 3,
            "enabled": body["enabled"],
            "serviceName": body.get("serviceName"),
        }
        rows.append(layer)
        return httpx.Response(201, json=make_api_response(layer))

    def _set_enabled(
        self, _key: Any, body: dict[str, Any], _request: Any, connection_id: str, layer_id: str
    ) -> httpx.Response:
        for row in self.layers.get(connection_id, []):
            if row["layerId"] == int(layer_id):
                row["enabled"] = body["enabled"]
                return httpx.Response(200, json=make_api_response(row))
        return httpx.Response(404, json={"title": "Not Found"})

    def _list_proposals(self, _key: Any, _body: Any, request: httpx.Request) -> httpx.Response:
        status = request.url.params.get("status")
        rows = [
            {k: v for k, v in p.items() if k not in {"diff", "dryRun", "blockingReasons", "warnings"}}
            for p in self.proposals.values()
            if status in (None, p["status"])
        ]
        return httpx.Response(200, json={"proposals": rows})

    def _get_proposal(self, _key: Any, _body: Any, _request: Any, proposal_id: str) -> httpx.Response:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return httpx.Response(404)
        if proposal["status"] == "Executing":
            self.reads_until_terminal -= 1
            if self.reads_until_terminal < 0:
                proposal["status"] = "Succeeded"
        return httpx.Response(200, json=proposal)

    def _approve(self, key: str | None, _body: Any, _request: Any, proposal_id: str) -> httpx.Response:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            return httpx.Response(404)
        if key == PROPOSER_KEY:
            return httpx.Response(403, json={"title": "Forbidden", "detail": "The requester cannot approve."})
        proposal.update(status="Executing", resolvedBy="approver", resolvedAt="2026-10-04T00:00:02Z")
        return httpx.Response(200, json=proposal)

    def _reject(self, _key: Any, body: dict[str, Any], _request: Any, proposal_id: str) -> httpx.Response:
        proposal = self.proposals[proposal_id]
        proposal.update(status="Rejected", resolvedBy="approver", resolutionReason=body["reason"])
        return httpx.Response(200, json=proposal)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeAdminServer:
    fake = FakeAdminServer()
    monkeypatch.setenv("HONUA_BASE_URL", BASE)
    monkeypatch.delenv("HONUA_ADMIN_KEY", raising=False)
    monkeypatch.delenv("HONUA_API_KEY", raising=False)

    def make_client(args: argparse.Namespace) -> HonuaAdminClient:
        return HonuaAdminClient(
            cli._resolve_base_url(args),
            api_key=cli._resolve_api_key(args),
            transport=httpx.MockTransport(fake),
        )

    monkeypatch.setattr(cli, "_make_client", make_client)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    return fake


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_json(capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    code, out, err = run(capsys, *argv, "--json")
    assert code == 0, err
    return json.loads(out)


def test_operator_workflow_end_to_end(
    server: FakeAdminServer, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("HONUA_ADMIN_KEY", ROOT_KEY)
    monkeypatch.setenv("FIXTURE_DB_PASSWORD", "s3cret")

    created = run_json(
        capsys,
        "datasource", "create",
        "--name", "lifecycle", "--host", "db", "--port", "5433", "--database", "fixture",
        "--username", "honua", "--password-env", "FIXTURE_DB_PASSWORD", "--ssl-mode", "Disable",
    )  # fmt: skip
    assert created["connectionId"] == "conn-1"
    assert created["port"] == 5433
    assert "password" not in json.dumps(created)
    sent = json.loads(server.requests[-1].content)
    assert sent["password"] == "s3cret"
    assert sent["databaseName"] == "fixture"
    assert server.requests[-1].headers["X-API-Key"] == ROOT_KEY

    tested = run_json(capsys, "datasource", "test", "conn-1")
    assert tested["isHealthy"] is True

    body = tmp_path / "layer.json"
    body.write_text(json.dumps({"schema": "honua_data", "table": "life", "geometryType": "Point", "srid": 4326}))
    published = run_json(
        capsys,
        "layer", "publish", "conn-1", "--body", f"@{body}",
        "--layer-name", "lifecycle_sites", "--service-name", "lifecycle", "--geometry-column", "geom",
        "--primary-key", "gid",
    )  # fmt: skip
    assert {k: published[k] for k in ("layerId", "layerName", "serviceName", "enabled")} == {
        "layerId": 1,
        "layerName": "lifecycle_sites",
        "serviceName": "lifecycle",
        "enabled": True,
    }
    assert json.loads(server.requests[-1].content)["schema"] == "honua_data"

    listed = run_json(capsys, "layer", "list", "conn-1", "--service-name", "lifecycle")
    assert [(row["layerId"], row["enabled"]) for row in listed] == [(1, True)]
    assert server.requests[-1].url.params["serviceName"] == "lifecycle"

    disabled = run_json(capsys, "layer", "unpublish", "conn-1", "1", "--service-name", "lifecycle")
    assert disabled["enabled"] is False
    assert server.requests[-1].method == "PUT"
    assert json.loads(server.requests[-1].content) == {"enabled": False}

    enabled = run_json(capsys, "layer", "enable", "conn-1", "1")
    assert enabled["enabled"] is True


def test_self_approval_refused_then_separate_approver_succeeds(
    server: FakeAdminServer, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(capsys, "proposal", "approve", "prop-1", "--api-key", PROPOSER_KEY, "--json")
    assert code == 1
    assert out == ""
    assert re.search(r"\bHTTP 403\b", err)
    assert server.proposals["prop-1"]["status"] == "AwaitingApproval"

    approved = run_json(capsys, "proposal", "approve", "prop-1", "--api-key", APPROVER_KEY)
    assert approved["status"] == "Executing"
    assert server.requests[-1].url.path == "/api/v1/admin/proposals/prop-1/approve"
    assert server.requests[-1].content == b""

    resolved = run_json(capsys, "proposal", "read", "prop-1", "--wait", "--api-key", APPROVER_KEY)
    assert {k: resolved[k] for k in ("status", "kind", "requestedBy", "resolvedBy")} == {
        "status": "Succeeded",
        "kind": "AdminConfigChange",
        "requestedBy": "proposer",
        "resolvedBy": "approver",
    }


def test_proposal_read_wait_times_out(server: FakeAdminServer, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "proposal", "read", "prop-1", "--wait", "--wait-timeout", "0", "--json")
    assert code == 1
    assert json.loads(out)["status"] == "AwaitingApproval"
    assert "still AwaitingApproval after 0s" in err


def test_proposal_read_without_wait_and_unknown_id(
    server: FakeAdminServer, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run(capsys, "proposal", "read", "prop-1")
    assert code == 0
    assert "status: AwaitingApproval" in out
    assert "diff: + layer proposal_sites" in out
    assert "dryRun" not in out

    code, out, err = run(capsys, "proposal", "read", "missing")
    assert code == 1
    assert "HTTP 404" in err


def test_proposal_list_filters_and_table(server: FakeAdminServer, capsys: pytest.CaptureFixture[str]) -> None:
    rows = run_json(capsys, "proposal", "list", "--status", "AwaitingApproval", "--requested-by", "proposer")
    assert [row["proposalId"] for row in rows] == ["prop-1"]
    assert dict(server.requests[-1].url.params) == {"status": "AwaitingApproval", "requestedBy": "proposer"}

    code, out, _ = run(capsys, "proposal", "list", "--kind", "Deploy")
    assert code == 0
    assert out.splitlines()[0].split() == ["proposalId", "kind", "status", "requestedBy", "summary"]
    assert "prop-1" in out

    code, out, _ = run(capsys, "proposal", "list", "--status", "Succeeded")
    assert (code, out) == (0, "(no entries)\n")


def test_proposal_reject(server: FakeAdminServer, capsys: pytest.CaptureFixture[str]) -> None:
    rejected = run_json(capsys, "proposal", "reject", "prop-1", "--reason", "wrong table")
    assert rejected["status"] == "Rejected"
    assert rejected["resolutionReason"] == "wrong table"
    assert json.loads(server.requests[-1].content) == {"reason": "wrong table"}

    code, _, err = run(capsys, "proposal", "reject", "prop-1", "--reason", "  ")
    assert code == 2
    assert "--reason must not be blank" in err


def test_datasource_test_unhealthy_exits_1(server: FakeAdminServer, capsys: pytest.CaptureFixture[str]) -> None:
    server.connections["conn-9"] = {"connectionId": "conn-9", "name": "broken"}
    server.healthy = False
    code, out, _ = run(capsys, "datasource", "test", "conn-9", "--json")
    assert code == 1
    assert json.loads(out)["isHealthy"] is False


def test_datasource_list_table_and_password_stdin(
    server: FakeAdminServer, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out, _ = run(capsys, "datasource", "list")
    assert (code, out) == (0, "(no entries)\n")

    monkeypatch.setattr("sys.stdin", io.StringIO("from-stdin\nignored\n"))
    code, out, _ = run(
        capsys,
        "datasource", "create", "--name", "n", "--host", "h", "--database", "d", "--username", "u",
        "--password-stdin", "--ssl-required",
    )  # fmt: skip
    assert code == 0
    assert "connectionId: conn-1" in out
    sent = json.loads(server.requests[-1].content)
    assert sent["password"] == "from-stdin"
    assert sent["sslRequired"] is True
    assert sent["port"] == 5432

    code, out, _ = run(capsys, "datasource", "list")
    assert "conn-1" in out


def test_datasource_create_body_from_stdin(
    server: FakeAdminServer, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    body = {
        "name": "lifecycle",
        "host": "db",
        "port": 5432,
        "databaseName": "fixture",
        "username": "honua",
        "password": "pw",
        "sslRequired": False,
        "sslMode": "Disable",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(body)))
    created = run_json(capsys, "datasource", "create", "--body", "-", "--name", "override")
    assert created["name"] == "override"
    assert json.loads(server.requests[-1].content)["password"] == "pw"


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--password-env", "A", "--password-stdin"], "either --password-env or --password-stdin"),
        (["--password-env", "UNSET_PASSWORD_VAR"], "UNSET_PASSWORD_VAR is not set"),
        (["--password-stdin", "--body", "-"], "both read stdin"),
        (["--body", "/nonexistent/body.json"], "readable JSON file"),
    ],
)
def test_datasource_create_usage_errors(
    server: FakeAdminServer,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    message: str,
) -> None:
    monkeypatch.delenv("UNSET_PASSWORD_VAR", raising=False)
    code, _, err = run(capsys, "datasource", "create", "--name", "n", *argv)
    assert code == 2
    assert message in err
    assert server.requests == []


def test_body_validation(server: FakeAdminServer, capsys: pytest.CaptureFixture[str], tmp_path: Any) -> None:
    not_object = tmp_path / "list.json"
    not_object.write_text("[1, 2]")
    code, _, err = run(capsys, "layer", "publish", "conn-1", "--body", str(not_object))
    assert (code, "must contain a JSON object" in err) == (2, True)

    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"table": "t", "colour": "red"}))
    code, _, err = run(capsys, "layer", "publish", "conn-1", "--body", str(unknown))
    assert (code, "unknown field(s) in --body: colour" in err) == (2, True)

    code, _, err = run(capsys, "layer", "publish", "conn-1")
    assert (code, "a table is required" in err) == (2, True)

    code, _, err = run(capsys, "datasource", "create", "--host", "h")
    assert (code, "incomplete request" in err) == (2, True)

    huge = tmp_path / "huge.json"
    huge.write_text(" " * (cli._MAX_BODY_BYTES + 1))
    code, _, err = run(capsys, "layer", "publish", "conn-1", "--body", str(huge))
    assert (code, "exceeds 1 MiB" in err) == (2, True)
    assert server.requests == []


def test_layer_publish_fields_and_disabled(
    server: FakeAdminServer, capsys: pytest.CaptureFixture[str], tmp_path: Any
) -> None:
    body = tmp_path / "layer.json"
    body.write_text(json.dumps({"table": "t", "fields": ["a"]}))
    published = run_json(capsys, "layer", "publish", "conn-1", "--body", str(body), "--disabled")
    sent = json.loads(server.requests[-1].content)
    assert sent["fields"] == ["a"]
    assert sent["enabled"] is False
    assert published["enabled"] is False

    run_json(capsys, "layer", "publish", "conn-1", "--table", "t2", "--field", "a", "--field", "b")
    assert json.loads(server.requests[-1].content)["fields"] == ["a", "b"]

    code, out, _ = run(capsys, "layer", "list", "conn-1")
    assert code == 0
    assert out.splitlines()[0].split() == ["layerId", "layerName", "serviceName", "table", "enabled"]

    code, _, err = run(capsys, "layer", "disable", "conn-1", "99")
    assert (code, "HTTP 404" in err) == (1, True)


def test_credentials_and_base_url_resolution(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    parser = cli.build_parser()
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    monkeypatch.delenv("HONUA_ADMIN_KEY", raising=False)
    monkeypatch.delenv("HONUA_API_KEY", raising=False)

    code, _, err = run(capsys, "datasource", "list")
    assert code == 2
    assert "a base URL is required" in err

    args = parser.parse_args(["datasource", "list"])
    assert cli._resolve_api_key(args) is None
    monkeypatch.setenv("HONUA_API_KEY", "data-key")
    assert cli._resolve_api_key(args) == "data-key"
    monkeypatch.setenv("HONUA_ADMIN_KEY", "admin-key")
    assert cli._resolve_api_key(args) == "admin-key"
    assert cli._resolve_api_key(parser.parse_args(["datasource", "list", "--api-key", "flag"])) == "flag"

    monkeypatch.setenv("HONUA_BASE_URL", BASE)
    with cli._make_client(parser.parse_args(["datasource", "list", "--timeout", "5"])) as client:
        assert isinstance(client, HonuaAdminClient)


def test_transport_failure_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        cli,
        "_make_client",
        lambda _args: HonuaAdminClient(BASE, transport=httpx.MockTransport(refuse), max_retries=0),
    )
    code, _, err = run(capsys, "proposal", "list")
    assert code == 1
    assert err.startswith("error: ")


def test_groups_without_subcommand_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    for group in ("datasource", "layer", "proposal"):
        code, _, err = run(capsys, group)
        assert code == 2
        assert f"honua-admin {group}" in err
    code, _, err = run(capsys)
    assert code == 2
    assert "datasource" in err
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("honua-admin ")


def test_proposal_models_from_server_shapes() -> None:
    summary = OperationProposalSummary.from_dict(
        {
            "proposalId": "p",
            "kind": "Deploy",
            "status": "Planned",
            "summary": "s",
            "riskLevel": "Low",
            "createdAt": "t",
            "updatedAt": "t",
            "futureField": 1,
        }
    )
    assert summary.proposal_id == "p"
    assert summary.requested_by is None

    detail = OperationProposalDetail.from_dict(
        {"proposalId": "p", "kind": "Deploy", "status": "Planned", "summary": "s", "riskLevel": "Low", "diff": None}
    )
    assert detail.diff == []
    assert detail.warnings == []


def test_list_proposals_tolerates_non_list_payload() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"proposals": None})

    with HonuaAdminClient(BASE, transport=httpx.MockTransport(handler)) as client:
        assert client.list_proposals() == []
