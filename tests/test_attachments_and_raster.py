"""Tests for the FeatureServer attachments surface and windowed raster reads.

Covers the GeoServices attachment request construction (query/list/add/update/
delete/download) against a faked transport, plus the OGC Coverages windowed
read and the ImageServer windowed export. The raster-write stance is asserted
in ``test_raster_write_documented_stance``.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.protocols import (
    AddAttachmentResult,
    AttachmentContent,
    AttachmentInfo,
    AttachmentQueryResult,
    DeleteAttachmentResult,
    UpdateAttachmentResult,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _record_handler(seen: list[dict[str, Any]]):
    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        body = request.content
        entry: dict[str, Any] = {
            "method": request.method,
            "raw_path": raw_path,
            "query": dict(request.url.params.multi_items()),
            "content_type": request.headers.get("content-type"),
            "body": body,
        }
        seen.append(entry)
        if raw_path.endswith("/queryAttachments"):
            return httpx.Response(
                200,
                json={
                    "attachmentGroups": [
                        {
                            "parentObjectId": 7,
                            "attachmentInfos": [
                                {
                                    "id": 11,
                                    "name": "photo.jpg",
                                    "contentType": "image/jpeg",
                                    "size": 2048,
                                    "keywords": "site",
                                    "url": "https://x/att/11",
                                }
                            ],
                        }
                    ]
                },
            )
        if raw_path.endswith("/attachments") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "attachmentInfos": [
                        {"id": 11, "name": "photo.jpg", "contentType": "image/jpeg", "size": 2048}
                    ]
                },
            )
        if raw_path.endswith("/addAttachment"):
            return httpx.Response(200, json={"addAttachmentResult": {"objectId": 11, "success": True}})
        if raw_path.endswith("/updateAttachment"):
            return httpx.Response(200, json={"updateAttachmentResult": {"objectId": 11, "success": True}})
        if raw_path.endswith("/deleteAttachments"):
            return httpx.Response(200, json={"deleteAttachmentResults": [{"objectId": 11, "success": True}]})
        if "/attachments/" in raw_path:
            return httpx.Response(200, content=b"\xff\xd8\xff-jpeg", headers={"content-type": "image/jpeg"})
        return httpx.Response(200, content=b"raster-bytes")

    return handler


# --------------------------------------------------------------------------
# Attachments — sync
# --------------------------------------------------------------------------


def test_query_attachments_builds_request_and_parses_groups() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.feature_server("parcels").query_attachments(2, 7, return_url=True)

    assert isinstance(result, AttachmentQueryResult)
    assert seen[0]["method"] == "GET"
    assert seen[0]["raw_path"] == "/rest/services/parcels/FeatureServer/2/queryAttachments"
    assert seen[0]["query"] == {"f": "json", "objectIds": "7", "returnUrl": "true"}
    assert result.groups[7][0].object_id == 11
    info = result.infos[0]
    assert isinstance(info, AttachmentInfo)
    assert info.name == "photo.jpg"
    assert info.content_type == "image/jpeg"
    assert info.size == 2048
    assert info.url == "https://x/att/11"
    assert info.parent_object_id == 7


def test_query_attachments_accepts_multiple_object_ids() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.feature_server("parcels").query_attachments(2, object_ids=[7, 8, 9])
    assert seen[0]["query"]["objectIds"] == "7,8,9"


def test_query_attachments_requires_object_id() -> None:
    transport = httpx.MockTransport(_record_handler([]))
    with HonuaClient("http://example.test", transport=transport) as client:
        with pytest.raises(ValueError, match="object_id"):
            client.feature_server("parcels").query_attachments(2)


def test_list_attachments_uses_canonical_infos_resource() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        infos = client.feature_server("parcels").list_attachments(2, 7)
    assert seen[0]["raw_path"] == "/rest/services/parcels/FeatureServer/2/7/attachments"
    assert infos[0].object_id == 11
    assert infos[0].parent_object_id == 7


def test_add_attachment_posts_multipart(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    file_path = tmp_path / "photo.jpg"
    file_path.write_bytes(b"\xff\xd8\xff-jpeg")
    with HonuaClient("http://example.test", transport=transport) as client:
        result = client.feature_server("parcels").add_attachment(2, 7, file_path, keywords="site")

    assert isinstance(result, AddAttachmentResult)
    assert result.object_id == 11
    assert result.success is True
    entry = seen[0]
    assert entry["method"] == "POST"
    assert entry["raw_path"] == "/rest/services/parcels/FeatureServer/2/7/addAttachment"
    assert entry["content_type"].startswith("multipart/form-data")
    assert b"photo.jpg" in entry["body"]
    assert b"\xff\xd8\xff-jpeg" in entry["body"]
    assert b'name="f"' in entry["body"]
    assert b"site" in entry["body"]


def test_add_attachment_accepts_bytes_and_file_object() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        fs = client.feature_server("parcels")
        fs.add_attachment(2, 7, b"raw-bytes", content_type="application/octet-stream")
        fs.add_attachment(2, 7, io.BytesIO(b"streamed"))
    assert b"raw-bytes" in seen[0]["body"]
    assert b"streamed" in seen[1]["body"]


def test_update_attachment_sends_attachment_id_and_optional_file() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        fs = client.feature_server("parcels")
        result = fs.update_attachment(2, 7, 11, keywords="updated")
        fs.update_attachment(2, 7, 11, file=b"new-bytes")

    assert isinstance(result, UpdateAttachmentResult)
    assert result.object_id == 11
    assert seen[0]["raw_path"] == "/rest/services/parcels/FeatureServer/2/7/updateAttachment"
    # keywords-only update still carries attachmentId in the multipart body
    assert b"attachmentId" in seen[0]["body"]
    assert b"updated" in seen[0]["body"]
    assert b"new-bytes" in seen[1]["body"]


def test_delete_attachment_posts_attachment_ids() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        results = client.feature_server("parcels").delete_attachment(2, 7, [11, 12])
    assert all(isinstance(r, DeleteAttachmentResult) for r in results)
    assert results[0].object_id == 11
    assert results[0].success is True
    assert seen[0]["method"] == "POST"
    assert seen[0]["raw_path"] == "/rest/services/parcels/FeatureServer/2/7/deleteAttachments"
    assert seen[0]["content_type"] == "application/x-www-form-urlencoded"
    assert dict(parse_qsl(seen[0]["body"].decode("ascii"))) == {"f": "json", "attachmentIds": "11,12"}


def test_download_attachment_returns_content_and_type() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        content = client.feature_server("parcels").download_attachment(2, 7, 11)
    assert isinstance(content, AttachmentContent)
    assert content.content == b"\xff\xd8\xff-jpeg"
    assert content.content_type == "image/jpeg"
    assert seen[0]["raw_path"] == "/rest/services/parcels/FeatureServer/2/7/attachments/11"


# --------------------------------------------------------------------------
# Attachments — async parity
# --------------------------------------------------------------------------


@pytest.mark.anyio
async def test_async_attachments_roundtrip() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        fs = client.feature_server("parcels")
        query = await fs.query_attachments(2, 7)
        added = await fs.add_attachment(2, 7, b"bytes")
        content = await fs.download_attachment(2, 7, 11)
        deleted = await fs.delete_attachment(2, 7, 11)

    assert query.infos[0].object_id == 11
    assert added.object_id == 11
    assert content.content_type == "image/jpeg"
    assert deleted[0].success is True
    assert [e["raw_path"] for e in seen] == [
        "/rest/services/parcels/FeatureServer/2/queryAttachments",
        "/rest/services/parcels/FeatureServer/2/7/addAttachment",
        "/rest/services/parcels/FeatureServer/2/7/attachments/11",
        "/rest/services/parcels/FeatureServer/2/7/deleteAttachments",
    ]


# --------------------------------------------------------------------------
# Windowed raster reads
# --------------------------------------------------------------------------


def test_coverage_windowed_read_builds_subset_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        data = client.ogc_coverages().coverage(
            "elevation",
            bbox=[-158, 21, -157, 22],
            bbox_crs="EPSG:4326",
            scale_size="x(512),y(512)",
            properties=["dem"],
            crs="EPSG:3857",
            response_format="tiff",
        )
    assert data == b"raster-bytes"
    assert seen[0]["raw_path"] == "/ogc/coverages/collections/elevation/coverage"
    assert seen[0]["query"] == {
        "f": "tiff",
        "bbox": "-158,21,-157,22",
        "bbox-crs": "EPSG:4326",
        "crs": "EPSG:3857",
        "scale-size": "x(512),y(512)",
        "properties": "dem",
    }


def test_coverage_whole_blob_read_unchanged() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.ogc_coverages().coverage("elevation", response_format="tiff")
    assert seen[0]["query"] == {"f": "tiff"}


def test_coverage_scale_factor_and_resolution() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.ogc_coverages().coverage("elevation", scale_factor=0.5, resolution="30,30", datetime="2024-01-01")
    assert seen[0]["query"]["scale-factor"] == "0.5"
    assert seen[0]["query"]["resolution"] == "30,30"
    assert seen[0]["query"]["datetime"] == "2024-01-01"


def test_image_server_windowed_export_builds_params() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    with HonuaClient("http://example.test", transport=transport) as client:
        client.image_server("imagery").export_image(
            [-158, 21, -157, 22],
            size=(256, 256),
            bbox_sr=4326,
            image_sr=3857,
            band_ids=[0, 1, 2],
            interpolation="RSP_BilinearInterpolation",
            image_format="tiff",
        )
    query = seen[0]["query"]
    assert seen[0]["raw_path"] == "/rest/services/imagery/ImageServer/exportImage"
    assert query["bbox"] == "-158,21,-157,22"
    assert query["size"] == "256,256"
    assert query["bboxSR"] == "4326"
    assert query["imageSR"] == "3857"
    assert query["bandIds"] == "0,1,2"
    assert query["interpolation"] == "RSP_BilinearInterpolation"
    assert query["format"] == "tiff"


@pytest.mark.anyio
async def test_async_coverage_windowed_read() -> None:
    seen: list[dict[str, Any]] = []
    transport = httpx.MockTransport(_record_handler(seen))
    async with AsyncHonuaClient("http://example.test", transport=transport) as client:
        await client.ogc_coverages().coverage("elevation", bbox=[0, 0, 1, 1], scale_size="x(64),y(64)")
    assert seen[0]["query"]["bbox"] == "0,0,1,1"
    assert seen[0]["query"]["scale-size"] == "x(64),y(64)"


# --------------------------------------------------------------------------
# Raster write stance
# --------------------------------------------------------------------------


def test_raster_write_documented_stance() -> None:
    """The SDK intentionally exposes no public raster/coverage WRITE method.

    honua-server has no public GeoServices/OGC raster-write endpoint (raster
    ingest is admin-only versioned import). The SDK therefore does not
    fabricate a ``put_coverage``/``write`` method on the read clients; this
    test pins that stance so a future write surface is a deliberate, reviewed
    addition tied to a real server endpoint. See docs/raster.md.
    """
    from honua_sdk.protocols import GeoServicesImageServerClient, OgcCoveragesClient

    for cls in (OgcCoveragesClient, GeoServicesImageServerClient):
        method_names = {name for name in dir(cls) if not name.startswith("_")}
        assert not (method_names & {"write", "put_coverage", "upload", "put", "write_coverage"})
