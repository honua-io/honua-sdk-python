"""Tests for the typed :class:`LayerSchema` model.

Covers parsing a real FeatureServer ``layer_metadata`` JSON shape into typed
fields, normalized geometry type, resolved SRID, and a typed extent — the
``arcpy.Describe`` / ``ListFields`` analogue — plus the OGC ``properties`` shape
and the ``Source.schema`` / ``feature_server.schema`` facade methods.
"""

from __future__ import annotations

import httpx

from honua_sdk import Extent, Field, HonuaClient, LayerSchema
from honua_sdk.models import SourceDescriptor, SourceLocator

# A representative Esri FeatureServer layer-metadata response.
_LAYER_METADATA = {
    "id": 0,
    "name": "Parcels",
    "type": "Feature Layer",
    "geometryType": "esriGeometryPolygon",
    "objectIdField": "OBJECTID",
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "extent": {
        "xmin": -100.0,
        "ymin": 30.0,
        "xmax": -90.0,
        "ymax": 40.0,
        "spatialReference": {"wkid": 4326},
    },
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID", "alias": "OBJECTID", "nullable": False, "editable": False},
        {"name": "NAME", "type": "esriFieldTypeString", "alias": "Parcel Name", "length": 64, "nullable": True},
        {"name": "VALUE", "type": "esriFieldTypeDouble", "alias": "Assessed Value"},
    ],
}


def test_layer_schema_parses_fields() -> None:
    schema = LayerSchema.from_metadata(_LAYER_METADATA)
    assert schema.name == "Parcels"
    assert schema.layer_id == 0
    assert schema.object_id_field == "OBJECTID"
    assert schema.field_names == ("OBJECTID", "NAME", "VALUE")

    oid = schema.field("objectid")  # case-insensitive lookup
    assert isinstance(oid, Field)
    assert oid.type == "esriFieldTypeOID"
    assert oid.nullable is False
    assert oid.editable is False

    name = schema.field("NAME")
    assert name is not None
    assert name.alias == "Parcel Name"
    assert name.length == 64
    assert name.nullable is True

    value = schema.field("VALUE")
    assert value is not None
    assert value.nullable is True  # defaults to nullable when unspecified


def test_layer_schema_normalizes_geometry_type() -> None:
    schema = LayerSchema.from_metadata(_LAYER_METADATA)
    assert schema.geometry_type == "Polygon"


def test_layer_schema_resolves_srid_prefers_latest_wkid() -> None:
    schema = LayerSchema.from_metadata(_LAYER_METADATA)
    assert schema.srid == 3857  # latestWkid wins over wkid


def test_layer_schema_typed_extent() -> None:
    schema = LayerSchema.from_metadata(_LAYER_METADATA)
    assert isinstance(schema.extent, Extent)
    assert schema.extent.bbox == (-100.0, 30.0, -90.0, 40.0)
    assert schema.extent.srid == 4326


def test_layer_schema_non_spatial_table() -> None:
    schema = LayerSchema.from_metadata({"id": 1, "name": "Inspections", "geometryType": None, "fields": []})
    assert schema.geometry_type is None
    assert schema.fields == ()
    assert schema.extent is None
    assert schema.srid is None


def test_layer_schema_unknown_geometry_type_passes_through() -> None:
    schema = LayerSchema.from_metadata({"name": "X", "geometryType": "esriGeometryWeird"})
    assert schema.geometry_type == "esriGeometryWeird"


def test_layer_schema_ogc_properties_shape() -> None:
    """OGC-style ``properties`` mapping (``{name: {type: ...}}``) is parsed too."""
    schema = LayerSchema.from_metadata(
        {
            "name": "lakes",
            "fields": {
                "name": {"type": "string"},
                "area": {"type": "number", "nullable": False},
            },
        }
    )
    assert set(schema.field_names) == {"name", "area"}
    area = schema.field("area")
    assert area is not None
    assert area.type == "number"
    assert area.nullable is False


def test_layer_schema_ogc_scalar_field_spec() -> None:
    """A scalar field spec (``{name: "string"}``) is parsed as a typed field."""
    schema = LayerSchema.from_metadata({"name": "x", "fields": {"label": "string"}})
    label = schema.field("label")
    assert label is not None
    assert label.type == "string"


def test_layer_schema_ignores_malformed_extent() -> None:
    schema = LayerSchema.from_metadata({"name": "x", "extent": {"xmin": "bad"}})
    assert schema.extent is None


def test_layer_schema_srid_falls_back_to_extent() -> None:
    schema = LayerSchema.from_metadata(
        {
            "name": "x",
            "extent": {"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1, "spatialReference": {"wkid": 4326}},
        }
    )
    assert schema.srid == 4326


# ---------------------------------------------------------------------------
# Facade integration: feature_server.schema / Source.schema
# ---------------------------------------------------------------------------


def _schema_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services/parcels/FeatureServer/0"
        return httpx.Response(200, json=_LAYER_METADATA)

    return httpx.MockTransport(handler)


def test_feature_server_schema_returns_typed_layer_schema() -> None:
    with HonuaClient("http://example.test", transport=_schema_transport()) as client:
        schema = client.feature_server("parcels").schema(0)
    assert isinstance(schema, LayerSchema)
    assert schema.geometry_type == "Polygon"
    assert schema.srid == 3857


def test_source_schema_uses_descriptor_layer() -> None:
    descriptor = SourceDescriptor(
        id="parcels",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="parcels", layer_id=0),
    )
    with HonuaClient("http://example.test", transport=_schema_transport()) as client:
        schema = client.source(descriptor).schema()
    assert isinstance(schema, LayerSchema)
    assert schema.field_names == ("OBJECTID", "NAME", "VALUE")
