"""Typed layer schema models.

A GP tool authored against ``arcpy`` reaches for ``arcpy.Describe`` /
``arcpy.ListFields`` to discover a layer's fields, geometry type, spatial
reference, and extent before mapping outputs. The Honua SDK previously only
returned the raw ``FeatureServer`` ``layer_metadata`` JSON, forcing every tool
to hand-parse ``fields[]`` / ``geometryType`` / ``extent`` / ``spatialReference``.

:class:`LayerSchema` (built from that JSON via :meth:`LayerSchema.from_metadata`)
gives the same information as a typed model: typed :class:`Field` entries,
a normalized :attr:`LayerSchema.geometry_type`, a resolved :attr:`srid`, and a
typed :class:`Extent`. It parses the Esri FeatureServer/MapServer layer shape
and tolerates the OGC-style ``queryables``/``properties`` shape too.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._helpers import _optional_int, _optional_str

# Esri geometry-type token -> short, OGC-ish geometry name. Unknown tokens pass
# through unchanged so a caller always sees the server's value when we cannot
# normalize it.
_ESRI_GEOMETRY_TYPES: dict[str, str] = {
    "esriGeometryPoint": "Point",
    "esriGeometryMultipoint": "MultiPoint",
    "esriGeometryPolyline": "Polyline",
    "esriGeometryPolygon": "Polygon",
    "esriGeometryEnvelope": "Envelope",
}


def _normalize_geometry_type(value: Any) -> str | None:
    text = _optional_str(value)
    if text is None:
        return None
    return _ESRI_GEOMETRY_TYPES.get(text, text)


def _srid_from_spatial_reference(spatial_reference: Mapping[str, Any] | None) -> int | None:
    """Resolve an EPSG/WKID integer from an Esri ``spatialReference`` mapping."""
    if not spatial_reference:
        return None
    for key in ("latestWkid", "wkid"):
        wkid = spatial_reference.get(key)
        if isinstance(wkid, int):
            return wkid
        if isinstance(wkid, str) and wkid.isdigit():
            return int(wkid)
    return None


@dataclass(frozen=True)
class Field:
    """A single typed attribute field on a layer.

    Mirrors the fields surfaced by ``arcpy.ListFields`` / the ArcGIS-API layer
    ``fields`` property. ``type`` retains the server's native type token (the
    Esri ``esriFieldType*`` family or an OGC/JSON-schema type) verbatim.
    """

    name: str
    type: str
    alias: str | None = None
    length: int | None = None
    nullable: bool = True
    editable: bool = True
    default_value: Any = None
    domain: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Field":
        name = _optional_str(payload.get("name")) or ""
        type_token = _optional_str(payload.get("type")) or ""
        nullable = payload.get("nullable")
        editable = payload.get("editable")
        domain = payload.get("domain")
        return cls(
            name=name,
            type=type_token,
            alias=_optional_str(payload.get("alias")),
            length=_optional_int(payload.get("length")),
            nullable=bool(nullable) if nullable is not None else True,
            editable=bool(editable) if editable is not None else True,
            default_value=payload.get("defaultValue"),
            domain=dict(domain) if isinstance(domain, Mapping) else None,
        )


@dataclass(frozen=True)
class Extent:
    """Axis-aligned bounding box for a layer.

    Carries the four bounds plus the spatial reference WKID when the source
    advertised one, so a GP tool can build an output extent without re-parsing.
    """

    xmin: float
    ymin: float
    xmax: float
    ymax: float
    srid: int | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """``(minx, miny, maxx, maxy)`` tuple — the GeoJSON/Shapely bbox order."""
        return (self.xmin, self.ymin, self.xmax, self.ymax)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "Extent | None":
        if not payload:
            return None
        try:
            xmin = float(payload["xmin"])
            ymin = float(payload["ymin"])
            xmax = float(payload["xmax"])
            ymax = float(payload["ymax"])
        except (KeyError, TypeError, ValueError):
            return None
        srid = _srid_from_spatial_reference(
            payload.get("spatialReference") if isinstance(payload.get("spatialReference"), Mapping) else None
        )
        return cls(xmin=xmin, ymin=ymin, xmax=xmax, ymax=ymax, srid=srid)


@dataclass(frozen=True)
class LayerSchema:
    """Typed description of a single layer's fields, geometry, CRS, and extent.

    Built from a FeatureServer/MapServer ``layer_metadata`` JSON response (or
    the OGC-style ``properties``/``queryables`` shape) via
    :meth:`from_metadata`. The :class:`arcpy.Describe` analogue for Honua GP
    authoring: ``fields``, ``geometry_type``, ``srid``, and ``extent`` are all
    typed so a tool never hand-parses the raw JSON.

    Attributes:
        layer_id: Numeric layer id when the source exposes one.
        name: Layer display name.
        geometry_type: Normalized geometry type (e.g. ``"Polygon"``), or
            ``None`` for non-spatial tables.
        fields: Typed :class:`Field` entries in server order.
        srid: Resolved EPSG/WKID of the layer's spatial reference.
        extent: Typed :class:`Extent`, when advertised.
        object_id_field: Name of the OID field, when advertised.
        spatial_reference: Raw spatial-reference mapping, preserved verbatim.
        raw: The unparsed metadata mapping the schema was built from.
    """

    name: str
    layer_id: int | None = None
    geometry_type: str | None = None
    fields: tuple[Field, ...] = ()
    srid: int | None = None
    extent: Extent | None = None
    object_id_field: str | None = None
    spatial_reference: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def field_names(self) -> tuple[str, ...]:
        """Field names in server order (the ``arcpy.ListFields`` name list)."""
        return tuple(f.name for f in self.fields)

    def field(self, name: str) -> "Field | None":
        """Return the field whose name matches *name* case-insensitively."""
        lowered = name.lower()
        for entry in self.fields:
            if entry.name.lower() == lowered:
                return entry
        return None

    @classmethod
    def from_metadata(cls, payload: Mapping[str, Any]) -> "LayerSchema":
        """Parse a FeatureServer/MapServer (or OGC) layer-metadata mapping."""
        raw_fields = payload.get("fields")
        fields = _parse_fields(raw_fields)

        spatial_reference = payload.get("spatialReference")
        spatial_reference = dict(spatial_reference) if isinstance(spatial_reference, Mapping) else None

        extent = Extent.from_dict(payload.get("extent") if isinstance(payload.get("extent"), Mapping) else None)
        srid = _srid_from_spatial_reference(spatial_reference)
        if srid is None and extent is not None:
            srid = extent.srid

        return cls(
            name=_optional_str(payload.get("name")) or "",
            layer_id=_optional_int(payload.get("id")),
            geometry_type=_normalize_geometry_type(payload.get("geometryType")),
            fields=fields,
            srid=srid,
            extent=extent,
            object_id_field=_optional_str(payload.get("objectIdField")),
            spatial_reference=spatial_reference,
            raw=dict(payload),
        )


def _parse_fields(raw_fields: Any) -> tuple[Field, ...]:
    """Parse either an Esri ``fields`` list or an OGC ``properties`` mapping."""
    if isinstance(raw_fields, Sequence) and not isinstance(raw_fields, (str, bytes)):
        return tuple(Field.from_dict(entry) for entry in raw_fields if isinstance(entry, Mapping))
    if isinstance(raw_fields, Mapping):
        # OGC ``properties``/``queryables`` shape: ``{name: {type: ...}}``.
        parsed: list[Field] = []
        for name, spec in raw_fields.items():
            if isinstance(spec, Mapping):
                merged = {"name": name, **spec}
                parsed.append(Field.from_dict(merged))
            else:
                parsed.append(Field(name=str(name), type=str(spec)))
        return tuple(parsed)
    return ()
