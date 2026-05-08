"""Tests for admin migration toolkit endpoints and artifact contracts."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_admin import (
    AsyncHonuaAdminClient,
    HonuaAdminClient,
    MigrationInventoryScanRequest,
    MigrationManifestArtifact,
    MigrationParityEvidenceArtifact,
    MigrationReadinessAttestation,
    MigrationSourceInventoryArtifact,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


_COMPATIBLE = {
    "level": "compatible",
    "code": "COMPATIBLE",
    "reason": "Supported as-is.",
    "warnings": [],
    "manualSteps": [],
}

_PARTIAL = {
    "level": "partial",
    "code": "ARCGIS_ATTACHMENTS",
    "reason": "Attachments need a separate plan.",
    "warnings": ["attachments-present"],
    "manualSteps": ["Plan attachment migration."],
}

_SOURCE = {
    "displayName": "County Parcels",
    "baseUrl": "https://example.com/arcgis/rest/services/Parcels/FeatureServer",
    "product": "ArcGIS Server",
    "version": "11.2",
    "build": "12345",
    "serviceType": "FeatureServer",
}

_INVENTORY_ARTIFACT = {
    "artifactKind": "honua.migration.source-inventory",
    "artifactVersion": "1.0",
    "sourceKind": "arcgis-geoservices-rest",
    "source": _SOURCE,
    "authPosture": {
        "mode": "anonymous",
        "credentialsSupplied": False,
        "accessConfirmed": True,
        "notes": ["public service"],
    },
    "scanCompleteness": {
        "status": "failed",
        "warnings": ["Layer metadata was unavailable."],
        "missingArtifacts": ["fields"],
    },
    "summary": {
        "containerCount": 1,
        "resourceCount": 1,
        "styleCount": 1,
        "externalDependencyCount": 1,
        "compatibleCount": 0,
        "partiallyCompatibleCount": 1,
        "incompatibleCount": 0,
    },
    "overallCompatibility": _PARTIAL,
    "containers": [
        {
            "id": "service:parcels",
            "kind": "service",
            "name": "Parcels",
            "title": "County Parcels",
            "description": "Parcel service",
            "isDefault": True,
            "compatibility": _COMPATIBLE,
        }
    ],
    "resources": [
        {
            "id": "resource:parcels:0",
            "containerId": "service:parcels",
            "kind": "feature-layer",
            "name": "Parcels",
            "title": "Parcels",
            "description": "Parcel layer",
            "geometryType": "esriGeometryPolygon",
            "featureCount": 42,
            "hasAttachments": True,
            "capabilities": ["Query"],
            "spatialReferences": [
                {
                    "role": "service",
                    "sourceValue": "EPSG:4326",
                    "srid": 4326,
                    "crsUri": "http://www.opengis.net/def/crs/EPSG/0/4326",
                    "datum": "WGS 84",
                    "unit": "degree",
                    "axisOrder": "lon-lat",
                    "isGeographic": True,
                }
            ],
            "fields": [
                {
                    "name": "ZONING",
                    "alias": "Zoning",
                    "fieldType": "esriFieldTypeString",
                    "nullable": True,
                    "domainType": "codedValue",
                    "domainName": "ZoningCode",
                    "domainValues": [{"code": "R1", "name": "Residential 1"}],
                }
            ],
            "styleIds": ["renderer:parcels:0"],
            "externalDependencyIds": ["dependency:attachments:parcels:0"],
            "compatibility": _PARTIAL,
        }
    ],
    "styles": [
        {
            "id": "renderer:parcels:0",
            "containerId": "service:parcels",
            "kind": "renderer",
            "name": "default",
            "format": "esri-json",
            "resourceIds": ["resource:parcels:0"],
            "externalDependencyIds": [],
            "metadata": {"rendererType": "simple"},
            "compatibility": _COMPATIBLE,
        }
    ],
    "externalDependencies": [
        {
            "id": "dependency:attachments:parcels:0",
            "containerId": "service:parcels",
            "resourceId": "resource:parcels:0",
            "kind": "attachments",
            "name": "Parcels attachments",
            "dependencyType": "arcgis-attachments",
            "address": "https://example.com/arcgis/rest/services/Parcels/FeatureServer/0",
            "metadata": {"relationship": "attachments"},
            "spatialReferences": [],
            "compatibility": _PARTIAL,
        }
    ],
}


def test_scan_migration_source_sends_body_and_parses_raw_artifact() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_INVENTORY_ARTIFACT)

    transport = httpx.MockTransport(handler)
    request = MigrationInventoryScanRequest(
        source_kind="geoserver",
        source_url="https://example.com/geoserver/rest",
        username="operator",
        password="secret",
        timeout_seconds=45,
        include_style_content=True,
    )

    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        result = client.scan_migration_source(request)

    assert seen["method"] == "POST"
    assert seen["path"] == "/api/v1/admin/import/scan"
    assert seen["params"] == {}
    assert seen["body"] == {
        "sourceKind": "geoserver",
        "sourceUrl": "https://example.com/geoserver/rest",
        "username": "operator",
        "password": "secret",
        "timeoutSeconds": 45,
        "includeStyleContent": True,
    }
    assert isinstance(result, MigrationSourceInventoryArtifact)
    assert result.artifact_kind == "honua.migration.source-inventory"
    assert result.source.display_name == "County Parcels"
    assert result.scan_completeness.status == "failed"
    assert result.resources[0].fields[0].domain_values is not None
    assert result.resources[0].fields[0].domain_values[0].code == "R1"


def test_scan_migration_source_export_json_sets_query() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        return httpx.Response(
            200,
            json=_INVENTORY_ARTIFACT,
            headers={"Content-Disposition": 'attachment; filename="parcels-inventory.json"'},
        )

    transport = httpx.MockTransport(handler)
    request = MigrationInventoryScanRequest(
        source_kind="arcgis-geoservices-rest",
        source_url="https://example.com/arcgis/rest/services/Parcels/FeatureServer",
    )

    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        result = client.scan_migration_source(request, export_json=True)

    assert seen["export"] == "json"
    assert result.artifact_version == "1.0"


@pytest.mark.anyio
async def test_async_scan_migration_source() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_INVENTORY_ARTIFACT)

    transport = httpx.MockTransport(handler)
    request = MigrationInventoryScanRequest(
        source_kind="geoservices",
        source_url="https://example.com/arcgis/rest/services/Parcels/FeatureServer",
    )

    async with AsyncHonuaAdminClient("http://test.honua.io", transport=transport) as client:
        result = await client.scan_migration_source(request)

    assert seen["path"] == "/api/v1/admin/import/scan"
    assert seen["body"] == {
        "sourceKind": "geoservices",
        "sourceUrl": "https://example.com/arcgis/rest/services/Parcels/FeatureServer",
    }
    assert result.source_kind == "arcgis-geoservices-rest"


def test_migration_inventory_scan_request_repr_redacts_password() -> None:
    request = MigrationInventoryScanRequest(
        source_kind="geoserver",
        source_url="https://example.com/geoserver/rest",
        password="super-secret",
    )

    repr_text = repr(request)

    assert "password" not in repr_text
    assert "super-secret" not in repr_text


def test_source_inventory_artifact_round_trips_contract_fields() -> None:
    artifact = MigrationSourceInventoryArtifact.from_dict(_INVENTORY_ARTIFACT)
    payload = artifact.to_dict()

    assert payload["artifactKind"] == "honua.migration.source-inventory"
    assert payload["artifactVersion"] == "1.0"
    assert payload["scanCompleteness"]["status"] == "failed"
    assert payload["resources"][0]["hasAttachments"] is True
    assert payload["resources"][0]["fields"][0]["domainValues"][0] == {
        "code": "R1",
        "name": "Residential 1",
    }
    assert payload["externalDependencies"][0]["metadata"] == {"relationship": "attachments"}


def test_migration_manifest_artifact_models_preserve_nested_fields() -> None:
    manifest = MigrationManifestArtifact.from_dict(
        {
            "artifactKind": "honua.migration.manifest",
            "artifactVersion": "1.0",
            "sourceArtifactKind": "honua.migration.source-inventory",
            "sourceArtifactVersion": "1.0",
            "sourceKind": "arcgis-geoservices-rest",
            "source": _SOURCE,
            "summary": {
                "sourceResourceCount": 1,
                "targetResourceCount": 1,
                "styleActionCount": 1,
                "manualReviewCount": 1,
                "unsupportedCount": 0,
            },
            "targetResources": [
                {
                    "sourceResourceId": "resource:parcels:0",
                    "sourceKind": "feature-layer",
                    "action": "manual-review",
                    "targetServiceName": "county-parcels",
                    "targetResourceName": "parcels",
                    "geometryType": "esriGeometryPolygon",
                    "fields": [
                        {
                            "name": "OBJECTID",
                            "fieldType": "esriFieldTypeOID",
                        }
                    ],
                    "capabilities": ["Query"],
                    "spatialReferences": [{"role": "service", "srid": 4326}],
                    "styleIds": ["renderer:parcels:0"],
                    "externalDependencyIds": [],
                    "compatibility": _PARTIAL,
                }
            ],
            "styleActions": [
                {
                    "sourceStyleId": "renderer:parcels:0",
                    "action": "manual-review",
                    "format": "esri-json",
                    "resourceIds": ["resource:parcels:0"],
                    "externalDependencyIds": [],
                    "compatibility": _PARTIAL,
                }
            ],
            "manualReviewItems": [
                {
                    "sourceId": "resource:parcels:0",
                    "kind": "feature-layer",
                    "code": "ARCGIS_ATTACHMENTS",
                    "severity": "manual-review",
                    "reason": "Attachments require review.",
                    "manualSteps": ["Plan attachment migration."],
                    "warnings": ["attachments-present"],
                }
            ],
            "unsupportedItems": [],
        }
    )

    payload = manifest.to_dict()

    assert payload["artifactKind"] == "honua.migration.manifest"
    assert payload["sourceArtifactKind"] == "honua.migration.source-inventory"
    assert payload["summary"]["manualReviewCount"] == 1
    assert payload["targetResources"][0]["compatibility"]["code"] == "ARCGIS_ATTACHMENTS"
    assert payload["manualReviewItems"][0]["manualSteps"] == ["Plan attachment migration."]


def test_parity_evidence_and_readiness_models_preserve_state_values() -> None:
    evidence = MigrationParityEvidenceArtifact.from_dict(
        {
            "artifactKind": "honua.migration.parity-evidence-pack",
            "artifactVersion": "1.0",
            "sourceKind": "arcgis-geoservices-rest",
            "source": _SOURCE,
            "overallState": "unknown",
            "summary": "Readiness evidence is incomplete.",
            "manifestAvailable": True,
            "sections": [
                {
                    "id": "capability",
                    "title": "Capability",
                    "state": "pass",
                    "items": [
                        {
                            "id": "query",
                            "state": "pass",
                            "summary": "Query capability verified.",
                            "evidence": ["Fixture baseline passed."],
                            "remediation": [],
                            "relatedIds": ["resource:parcels:0"],
                        },
                        {
                            "id": "attachments",
                            "state": "not-applicable",
                            "summary": "No attachments in pilot.",
                        },
                    ],
                }
            ],
            "cutoverReadiness": {
                "state": "unknown",
                "items": [
                    {
                        "id": "rollback-plan-documented",
                        "title": "Rollback plan documented",
                        "state": "fail",
                        "evidence": ["Missing runbook link."],
                        "remediation": ["Add rollback runbook."],
                        "owner": "ops",
                    },
                    {
                        "id": "traffic-switch-planned",
                        "title": "Traffic switch planned",
                        "state": "unknown",
                    },
                ],
            },
        }
    )
    attestation = MigrationReadinessAttestation.from_dict(
        {
            "items": [
                {
                    "id": "known-gaps-accepted",
                    "state": "not-applicable",
                    "evidence": ["No known gaps for this slice."],
                    "owner": "release",
                }
            ]
        }
    )

    payload = evidence.to_dict()

    assert payload["overallState"] == "unknown"
    assert payload["sections"][0]["items"][0]["state"] == "pass"
    assert payload["sections"][0]["items"][1]["state"] == "not-applicable"
    assert payload["cutoverReadiness"]["items"][0]["state"] == "fail"
    assert payload["cutoverReadiness"]["items"][1]["state"] == "unknown"
    assert attestation.to_dict()["items"][0]["state"] == "not-applicable"
