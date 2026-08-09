"""Tests for the admin toolbox-translation validation endpoint client.

Wire contract: ``POST /api/v1/admin/import/toolbox/translation/validate``
(honua-server#2145 / #3040). The server owns the round-trip proof against the
canonical process catalog; this client only has to speak the manifest/report
shapes exactly and go through the existing admin credential path.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_admin import (
    TOOLBOX_TRANSLATION_MANIFEST_KIND,
    TOOLBOX_TRANSLATION_REPORT_KIND,
    AsyncHonuaAdminClient,
    HonuaAdminClient,
    ToolboxParameterMapping,
    ToolboxToolDescriptor,
    ToolboxTranslationManifest,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


_REPORT = {
    "artifactKind": TOOLBOX_TRANSLATION_REPORT_KIND,
    "artifactVersion": "1.0",
    "toolboxName": "VectorAnalysisToolbox",
    "sourceFormat": "pyt",
    "summary": {
        "toolCount": 2,
        "translatedCount": 1,
        "partiallyTranslatedCount": 0,
        "unsupportedCount": 1,
    },
    "tools": [
        {
            "toolName": "BufferGeometry",
            "classification": "translated",
            "processId": "geometry.buffer",
            "parameterBindings": [
                {"sourceName": "in_geometry", "targetParameter": "wkb", "valueType": "Wkb", "required": True},
                {"sourceName": "buffer_distance", "targetParameter": "distance", "valueType": "FloatingPoint",
                 "required": True},
            ],
            "issues": [],
        },
        {
            "toolName": "RunCustomScript",
            "classification": "unsupported",
            "processId": None,
            "parameterBindings": [],
            "issues": [
                {
                    "code": "no-native-executor",
                    "message": "The scanner proposed no native Honua process for this tool.",
                },
                {
                    "code": "unsupported-construct",
                    "message": "Source construct cannot be translated: custom Python execution body.",
                    "parameterName": None,
                },
            ],
        },
    ],
}


def _manifest() -> ToolboxTranslationManifest:
    return ToolboxTranslationManifest(
        toolbox_name="VectorAnalysisToolbox",
        source_format="pyt",
        source_label="vector_analysis.pyt",
        tools=[
            ToolboxToolDescriptor(
                tool_name="BufferGeometry",
                display_name="Buffer Geometry",
                target_process_id="geometry.buffer",
                parameter_mappings=[
                    ToolboxParameterMapping("in_geometry", "wkb", "GPGeometry"),
                    ToolboxParameterMapping("buffer_distance", "distance"),
                ],
            ),
            ToolboxToolDescriptor(tool_name="RunCustomScript", unsupported_constructs=["custom Python execution body"]),
        ],
    )


def test_manifest_serialises_to_the_server_wire_shape() -> None:
    payload = _manifest().to_dict()

    assert payload["artifactKind"] == TOOLBOX_TRANSLATION_MANIFEST_KIND
    assert payload["artifactVersion"] == "1.0"
    assert list(payload)[:2] == ["artifactKind", "artifactVersion"]
    assert payload["toolboxName"] == "VectorAnalysisToolbox"
    assert payload["sourceFormat"] == "pyt"
    assert payload["sourceLabel"] == "vector_analysis.pyt"
    assert payload["tools"][0]["parameterMappings"] == [
        {"sourceName": "in_geometry", "targetParameter": "wkb", "sourceDataType": "GPGeometry"},
        {"sourceName": "buffer_distance", "targetParameter": "distance"},
    ]
    # An untranslatable tool carries no target rather than a stub target.
    assert "targetProcessId" not in payload["tools"][1]
    assert payload["tools"][1]["unsupportedConstructs"] == ["custom Python execution body"]


def test_validate_toolbox_translation_posts_the_manifest_and_parses_the_report() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_REPORT)

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        report = client.validate_toolbox_translation(_manifest())

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/admin/import/toolbox/translation/validate"
    assert seen["body"]["artifactKind"] == TOOLBOX_TRANSLATION_MANIFEST_KIND

    assert report.artifact_kind == TOOLBOX_TRANSLATION_REPORT_KIND
    assert report.toolbox_name == "VectorAnalysisToolbox"
    assert report.summary.tool_count == 2
    assert report.summary.translated_count == 1
    assert report.summary.unsupported_count == 1
    assert [tool.classification for tool in report.tools] == ["translated", "unsupported"]
    assert report.tools[0].process_id == "geometry.buffer"
    assert report.tools[0].parameter_bindings[0].value_type == "Wkb"
    assert report.tools[0].parameter_bindings[0].required is True
    assert report.tools[1].issues[0].code == "no-native-executor"


def test_validate_toolbox_translation_sends_the_admin_api_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        return httpx.Response(200, json=_REPORT)

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient("http://test.honua.io", api_key="admin-secret", transport=transport) as client:
        client.validate_toolbox_translation(_manifest())

    # The endpoint is in the admin import group, so it rides the existing admin
    # credential path rather than a new auth mechanism.
    assert seen["headers"]["x-api-key"] == "admin-secret"


def test_validate_toolbox_translation_accepts_per_call_options() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["timeout"] = request.extensions.get("timeout", {})
        return httpx.Response(200, json=_REPORT)

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        client.validate_toolbox_translation(
            _manifest(),
            timeout=2.5,
            extra_headers={"X-Trace-Id": "trace-9"},
            idempotency_key="toolbox-key",
        )

    assert seen["headers"]["x-trace-id"] == "trace-9"
    assert seen["headers"]["idempotency-key"] == "toolbox-key"
    assert seen["timeout"]["connect"] == 2.5


def test_validate_toolbox_translation_raises_on_a_rejected_manifest() -> None:
    from honua_sdk.errors import HonuaHttpError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "sourceFormat must be one of: pyt, tbx, atbx."})

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient("http://test.honua.io", transport=transport) as client, pytest.raises(HonuaHttpError):
        client.validate_toolbox_translation(
            ToolboxTranslationManifest(toolbox_name="T", source_format="docx", tools=[])
        )


def test_report_from_dict_tolerates_a_sparse_payload() -> None:
    from honua_admin import ToolboxTranslationReport

    report = ToolboxTranslationReport.from_dict({"toolboxName": "T", "sourceFormat": "pyt"})

    assert report.summary.tool_count == 0
    assert report.tools == []
    assert report.artifact_kind == TOOLBOX_TRANSLATION_REPORT_KIND
    assert report.to_dict()["artifactKind"] == TOOLBOX_TRANSLATION_REPORT_KIND


@pytest.mark.anyio
async def test_async_validate_toolbox_translation() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_REPORT)

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaAdminClient("http://test.honua.io", transport=transport) as client:
        report = await client.validate_toolbox_translation(_manifest())

    assert seen["path"] == "/api/v1/admin/import/toolbox/translation/validate"
    assert seen["body"]["tools"][0]["toolName"] == "BufferGeometry"
    assert report.summary.translated_count == 1
