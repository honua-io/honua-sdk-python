"""Tests for the admin operation-proposal endpoints (sync and async clients)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient, OperationProposalDetail, OperationProposalSummary
from honua_sdk import HonuaHttpError

_DETAIL = {
    "proposalId": "prop/1",
    "kind": "AdminConfigChange",
    "status": "AwaitingApproval",
    "requestedBy": "proposer",
    "summary": "Publish service proposal_sites",
    "diff": ["+ layer"],
    "dryRun": ["ok"],
    "riskLevel": "Medium",
    "blockingReasons": [],
    "warnings": ["large table"],
    "createdAt": "2026-10-04T00:00:00Z",
    "updatedAt": "2026-10-04T00:00:00Z",
}


def _handler(seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.raw_path.decode().split("?")[0]
        if path == "/api/v1/admin/proposals":
            return httpx.Response(200, json={"proposals": [{k: v for k, v in _DETAIL.items() if k != "diff"}]})
        if path.endswith("/approve") and request.headers.get("X-API-Key") == "proposer":
            return httpx.Response(403, json={"title": "Forbidden"})
        if path.endswith("/approve"):
            return httpx.Response(200, json={**_DETAIL, "status": "Executing", "resolvedBy": "approver"})
        if path.endswith("/reject"):
            reason = json.loads(request.content)["reason"]
            return httpx.Response(200, json={**_DETAIL, "status": "Rejected", "resolutionReason": reason})
        return httpx.Response(200, json=_DETAIL)

    return handler


def test_sync_proposal_calls() -> None:
    seen: list[httpx.Request] = []
    with HonuaAdminClient("http://test.honua.io", api_key="approver", transport=httpx.MockTransport(_handler(seen))) as c:
        rows = c.list_proposals(status="AwaitingApproval", kind="AdminConfigChange", requested_by="proposer")
        detail = c.get_proposal("prop/1")
        approved = c.approve_proposal("prop/1")
        rejected = c.reject_proposal("prop/1", "no")

    assert isinstance(rows[0], OperationProposalSummary)
    assert rows[0].requested_by == "proposer"
    assert dict(seen[0].url.params) == {
        "status": "AwaitingApproval",
        "kind": "AdminConfigChange",
        "requestedBy": "proposer",
    }
    assert isinstance(detail, OperationProposalDetail)
    assert (detail.dry_run, detail.warnings) == (["ok"], ["large table"])
    assert seen[1].url.raw_path == b"/api/v1/admin/proposals/prop%2F1"
    assert (seen[2].method, seen[2].content) == ("POST", b"")
    assert (approved.status, approved.resolved_by) == ("Executing", "approver")
    assert (rejected.status, rejected.resolution_reason) == ("Rejected", "no")


def test_sync_list_without_filters_sends_no_params() -> None:
    seen: list[httpx.Request] = []
    with HonuaAdminClient("http://test.honua.io", transport=httpx.MockTransport(_handler(seen))) as c:
        c.list_proposals()
    assert seen[0].url.query == b""


def test_sync_self_approval_raises_403() -> None:
    seen: list[httpx.Request] = []
    with HonuaAdminClient("http://test.honua.io", api_key="proposer", transport=httpx.MockTransport(_handler(seen))) as c:
        with pytest.raises(HonuaHttpError) as excinfo:
            c.approve_proposal("prop/1")
    assert excinfo.value.status_code == 403


@pytest.mark.anyio
async def test_async_proposal_calls() -> None:
    seen: list[httpx.Request] = []
    async with AsyncHonuaAdminClient(
        "http://test.honua.io", api_key="approver", transport=httpx.MockTransport(_handler(seen))
    ) as c:
        rows = await c.list_proposals(status="AwaitingApproval")
        detail = await c.get_proposal("prop/1")
        approved = await c.approve_proposal("prop/1")
        rejected = await c.reject_proposal("prop/1", "no")
    assert rows[0].proposal_id == "prop/1"
    assert detail.diff == ["+ layer"]
    assert approved.status == "Executing"
    assert rejected.resolution_reason == "no"
    assert json.loads(seen[-1].content) == {"reason": "no"}


@pytest.mark.anyio
async def test_async_list_tolerates_non_object_payload() -> None:
    async with AsyncHonuaAdminClient(
        "http://test.honua.io", transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=[]))
    ) as c:
        assert await c.list_proposals() == []


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
