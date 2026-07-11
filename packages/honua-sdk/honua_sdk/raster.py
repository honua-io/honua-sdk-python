"""Raster interop for converting server geoprocessing output to/from rasters.

Honua computes; your ecosystem consumes. This module is a *last-mile*
consumption layer: it turns the GeoTIFF a server-side OGC API Processes job
produces into the raster objects you already work with -- a :mod:`rasterio`
dataset, an :class:`xarray.DataArray` (via :mod:`rioxarray`) -- and back. It
contains **no** client-side raster analysis; the canonical engine is the
server.

The heavy geo stack is optional. Install it with::

    pip install honua-sdk[raster]

The output-selection helpers (:func:`find_raster_output`,
:func:`inline_raster_bytes`, :func:`raster_href`) are pure and dependency-free;
only the conversion helpers require ``rasterio``/``rioxarray``/``xarray`` and
raise a clear :class:`ImportError` when the extra is absent.

:func:`parse_multidimensional_info` (also pure and dependency-free) parses the
ImageServer ``multidimensionalInfo`` operation's response into typed
:class:`MultidimensionalVariable` / :class:`MultidimensionalDimension`
objects -- coverage *discovery* metadata only, not pixel data; see its
docstring.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import HonuaError

try:
    import rasterio
    import rioxarray
    import xarray

    _HAS_DEPS = True
except ImportError:
    _HAS_DEPS = False


def _ensure_deps() -> None:
    if not _HAS_DEPS:
        raise ImportError(
            "rasterio, rioxarray and xarray are required for raster interop. "
            "Install them with:  pip install honua-sdk[raster]"
        )


# ---------------------------------------------------------------------------
# Output selection (pure -- no optional deps required).
# ---------------------------------------------------------------------------
#: Substrings that mark a media/content type as a (Cloud-Optimized) GeoTIFF.
_RASTER_MEDIA_HINTS = ("tiff", "geotiff", "cog")
_RASTER_SUFFIXES = (".tif", ".tiff")


def _looks_raster_media(media: Any) -> bool:
    return isinstance(media, str) and any(hint in media.lower() for hint in _RASTER_MEDIA_HINTS)


def _looks_raster_href(href: Any) -> bool:
    if not isinstance(href, str):
        return False
    path = href.split("?", 1)[0].split("#", 1)[0]
    return path.lower().endswith(_RASTER_SUFFIXES)


def _is_raster_member(member: Any) -> bool:
    if not isinstance(member, Mapping):
        return False
    media = member.get("mediaType") or member.get("type")
    href = member.get("href")
    if isinstance(href, str) and (_looks_raster_media(media) or _looks_raster_href(href)):
        return True
    return isinstance(member.get("value"), str) and _looks_raster_media(media)


def find_raster_output(results: Mapping[str, Any]) -> dict[str, Any]:
    """Select the raster output member from an OGC Processes results document.

    The results document returned by ``GET /ogc/processes/jobs/{id}/results``
    is an outputs map keyed by output id. A raster member is identified by a
    GeoTIFF ``mediaType``/``type`` or a ``.tif``/``.tiff`` ``href``. The first
    match (the document itself, a top-level member, or a member nested under an
    OGC ``value`` wrapper) is returned.

    Raises :class:`~honua_sdk.errors.HonuaError` when no raster output is
    present so the failure is explicit rather than silent.
    """
    if _is_raster_member(results):
        return dict(results)

    for member in results.values():
        if _is_raster_member(member):
            return dict(member)
        if isinstance(member, Mapping) and _is_raster_member(member.get("value")):
            return dict(member["value"])

    raise HonuaError(
        "Geoprocessing results document does not contain a raster (GeoTIFF) output; "
        f"got output keys {sorted(results)!r}. "
        "Raster interop requires a raster-out process."
    )


def inline_raster_bytes(member: Mapping[str, Any]) -> bytes | None:
    """Decode an inline base64 raster ``value`` from an output member.

    Returns ``None`` when the member carries no inline ``value`` (for example a
    by-reference ``href`` output, which the caller fetches over HTTP instead).
    A ``data:`` URI prefix is tolerated. Raises
    :class:`~honua_sdk.errors.HonuaError` when a ``value`` is present but is not
    valid base64.
    """
    value = member.get("value")
    if not isinstance(value, str):
        return None
    payload = value.split(",", 1)[1] if value.startswith("data:") else value
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HonuaError(f"Raster output value is not valid base64: {exc}") from exc


def raster_href(member: Mapping[str, Any]) -> str | None:
    """Return the by-reference ``href`` of an output member, when present."""
    href = member.get("href")
    return href if isinstance(href, str) else None


# ---------------------------------------------------------------------------
# Conversions (require the ``raster`` extra).
# ---------------------------------------------------------------------------
def open_geotiff(data: bytes) -> rasterio.io.DatasetReader:
    """Open in-memory GeoTIFF ``data`` as a :mod:`rasterio` dataset.

    The returned dataset reads from an in-memory ``MemoryFile``; the backing
    file is kept alive for the dataset's lifetime, so close the dataset (or use
    it as a context manager) when done. Requires the ``raster`` extra.
    """
    _ensure_deps()
    memfile = rasterio.io.MemoryFile(data)
    dataset = memfile.open()
    # Pin the MemoryFile to the dataset so it is not garbage-collected (which
    # would drop the underlying VSIMEM file) before the caller is finished.
    dataset._honua_memfile = memfile
    return dataset


def geotiff_to_xarray(data: bytes) -> xarray.DataArray:
    """Convert in-memory GeoTIFF ``data`` to an :class:`xarray.DataArray`.

    The array (with CRS/affine transform attached by :mod:`rioxarray`) is read
    fully into memory and is self-contained -- no open file handle is retained.
    Requires the ``raster`` extra.
    """
    _ensure_deps()
    with rasterio.io.MemoryFile(data) as memfile, memfile.open() as dataset:
        array = rioxarray.open_rasterio(dataset)
        return array.load()


def xarray_to_geotiff(data_array: xarray.DataArray) -> bytes:
    """Serialize a (rioxarray-backed) :class:`xarray.DataArray` to GeoTIFF bytes.

    Useful for preparing a raster to send to the server. The array must carry
    rioxarray spatial metadata (CRS + transform), e.g. one produced by
    :func:`geotiff_to_xarray` or ``rioxarray.open_rasterio``. Requires the
    ``raster`` extra.
    """
    _ensure_deps()
    with rasterio.io.MemoryFile() as memfile:
        data_array.rio.to_raster(memfile.name, driver="GTiff")
        return bytes(memfile.read())


# ---------------------------------------------------------------------------
# Multidimensional coverage metadata (pure -- no optional deps required).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MultidimensionalDimension:
    """One dimensional axis (e.g. ``StdTime``, ``StdZ``) of a coverage variable.

    Mirrors a single entry of the Esri ``multidimensionalInfo`` dimension
    contract (``ImageServerMultidimensionalDimension`` in honua-server). This
    describes the *shape* of the axis only -- how many coordinates it has and,
    when enumerable, what they are -- not pixel data (see
    :func:`parse_multidimensional_info`).
    """

    name: str
    unit: str | None
    extent: tuple[float, float] | None
    values: tuple[float, ...] | None
    has_regular_intervals: bool
    dimension_size: int

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MultidimensionalDimension":
        """Parse one ``dimensions[]`` entry of a ``multidimensionalInfo`` variable."""
        extent_raw = payload.get("extent")
        extent: tuple[float, float] | None = None
        if isinstance(extent_raw, (list, tuple)):
            try:
                lo, hi = extent_raw
            except ValueError:
                pass
            else:
                extent = (float(lo), float(hi))

        values_raw = payload.get("values")
        values: tuple[float, ...] | None = (
            tuple(float(v) for v in values_raw) if isinstance(values_raw, (list, tuple)) else None
        )

        return cls(
            name=str(payload.get("name") or ""),
            unit=payload.get("unit"),
            extent=extent,
            values=values,
            has_regular_intervals=bool(payload.get("hasRegularIntervals", False)),
            dimension_size=int(payload.get("dimensionSize") or 0),
        )


@dataclass(frozen=True)
class MultidimensionalVariable:
    """One data variable (e.g. ``temperature``) of a multidimensional coverage.

    Mirrors a single entry of the Esri ``multidimensionalInfo`` ``variables``
    array (``ImageServerMultidimensionalVariable`` in honua-server), each
    carrying its own dimensional axes.
    """

    name: str
    description: str | None
    unit: str | None
    dimensions: tuple[MultidimensionalDimension, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MultidimensionalVariable":
        """Parse one ``variables[]`` entry of a ``multidimensionalInfo`` document."""
        dimensions_raw = payload.get("dimensions")
        dimensions = (
            tuple(
                MultidimensionalDimension.from_dict(dimension)
                for dimension in dimensions_raw
                if isinstance(dimension, Mapping)
            )
            if isinstance(dimensions_raw, (list, tuple))
            else ()
        )
        return cls(
            name=str(payload.get("name") or ""),
            description=payload.get("description"),
            unit=payload.get("unit"),
            dimensions=dimensions,
        )


def parse_multidimensional_info(payload: Mapping[str, Any]) -> tuple[MultidimensionalVariable, ...]:
    """Parse an ImageServer ``multidimensionalInfo`` response into typed variables.

    ``payload`` is the raw JSON response body of the GeoServices ImageServer
    ``multidimensionalInfo`` operation (or the inner ``multidimensionalInfo``
    document itself) -- accepted either as
    ``{"multidimensionalInfo": {"variables": [...]}}`` or as the unwrapped
    ``{"variables": [...]}`` document, so this composes with whichever client
    method eventually surfaces the raw wire call. Each variable's dimensions
    follow the Esri contract confirmed against honua-server's
    ``ImageServerMultidimensionalInfoBuilder``/``ImageServerModels.cs``:
    ``name``, optional ``description``/``unit``, and a ``dimensions`` array of
    ``{name, unit?, extent?: [min, max], values?: [...], hasRegularIntervals,
    dimensionSize}`` (``unit``, ``extent``, ``values``, and ``description`` are
    omitted from the wire payload -- not emitted as JSON ``null`` -- when
    unset, so they parse to Python ``None`` either way). ``values`` is only
    populated server-side for a regular axis whose ``dimensionSize`` is
    <= 10,000; larger or irregular axes carry ``extent`` only.

    This describes the coverage's **dimensions and variables** -- discovery /
    introspection metadata for driving a time slider or variable picker -- and
    nothing else. It is **not** a way to fetch actual pixel data for a
    specific time/depth slice: honua-server has no reader wired up that can
    resolve a parsed dimension constraint to pixels today (tracked as
    honua-server#1869 -- see ``ImageServerMultidimensionalDefinition.cs``,
    whose ``getSamples``/``slices`` paths return an honest 501 for any
    supplied ``multidimensionalDefinition`` rather than sampling from the
    wrong raster). This helper does not attempt that and never will until
    #1869 lands server-side.
    """
    document: Mapping[str, Any] = payload
    inner = payload.get("multidimensionalInfo")
    if isinstance(inner, Mapping):
        document = inner

    variables_raw = document.get("variables")
    if not isinstance(variables_raw, (list, tuple)):
        return ()
    return tuple(
        MultidimensionalVariable.from_dict(variable) for variable in variables_raw if isinstance(variable, Mapping)
    )
