"""Shared spatial-analysis helpers for the GeoPandas walkthrough.

This module is the canonical implementation so the notebook
(``examples/notebooks/spatial_analysis_walkthrough.ipynb``) and its paired
script mirror reuse the same logic instead of carrying duplicate code.

The helpers split into two groups:

* **Pure-Python helpers** (no network): build a small demo Esri JSON response,
  convert it to a GeoDataFrame through the SDK, and run the spatial operations
  (buffer, spatial join, dissolve, summarise). These are import- and
  test-friendly and never require a live Honua server.
* **Live helper** (:func:`query_sensor_features`): issues a real
  ``query_features`` call against a Honua deployment using the shared
  ``HONUA_*`` environment-variable contract documented in
  ``examples/README.md``. Only the notebook's clearly-marked "live" cell calls
  this.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Protocol

try:
    import geopandas as gpd
except ImportError as exc:  # pragma: no cover - import guard for local usage
    raise ImportError(
        "The spatial-analysis example requires geopandas and shapely. "
        'Install them with: pip install -e "packages/honua-sdk[geopandas]"'
    ) from exc

from honua_sdk.geopandas import features_to_geodataframe

# ---------------------------------------------------------------------------
# Cloud environment contract (mirrors examples/README.md)
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0

# Working CRS for the buffer step. Esri "Web Mercator" (metres) keeps buffer
# distances intuitive; results are reprojected to WGS84 for display/summary.
WORKING_CRS = "EPSG:3857"
DISPLAY_CRS = "EPSG:4326"
# Buffer radius in the working (Web Mercator) projection. SF sits near 37.8N,
# where Web Mercator inflates distances ~1.27x, so this is roughly a 2.4 km
# ground radius -- large enough that adjacent waterfront sensors share buffers.
DEFAULT_BUFFER_METERS = 3000.0


class HonuaClientProtocol(Protocol):
    """Minimal protocol for the live-query helper's client dependency."""

    def query_features(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | list[str] = "*",
        return_geometry: bool = True,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EnvContract:
    """Resolved ``HONUA_*`` environment configuration for a live run."""

    base_url: str
    service_id: str
    layer_id: int
    api_key: str | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "EnvContract":
        source = os.environ if env is None else env
        return cls(
            base_url=source.get("HONUA_BASE_URL", DEFAULT_BASE_URL),
            service_id=source.get("HONUA_SERVICE_ID", DEFAULT_SERVICE_ID),
            layer_id=int(source.get("HONUA_LAYER_ID", str(DEFAULT_LAYER_ID))),
            api_key=source.get("HONUA_API_KEY") or None,
        )


# ---------------------------------------------------------------------------
# Demo fixture: an Esri JSON response shaped like HonuaClient.query_features
# ---------------------------------------------------------------------------
# Six air-quality sensors around San Francisco, in Web Mercator (EPSG:3857),
# matching the shape ``features_to_geodataframe`` consumes. Using a fixture
# keeps the pure-Python path runnable with no live server.
DEMO_SENSOR_RESPONSE: dict[str, Any] = {
    "spatialReference": {"wkid": 102100, "latestWkid": 3857},
    "features": [
        {
            "attributes": {"objectid": 1, "name": "Pier 39", "district": "north", "pm25": 11.4},
            "geometry": {"x": -13626596.60, "y": 4552436.67},
        },
        {
            "attributes": {"objectid": 2, "name": "Ferry Building", "district": "north", "pm25": 9.1},
            "geometry": {"x": -13624804.36, "y": 4550576.96},
        },
        {
            "attributes": {"objectid": 3, "name": "Mission Creek", "district": "south", "pm25": 18.7},
            "geometry": {"x": -13624058.52, "y": 4547069.78},
        },
        {
            "attributes": {"objectid": 4, "name": "Alamo Square", "district": "central", "pm25": 14.2},
            "geometry": {"x": -13629357.33, "y": 4547886.61},
        },
        {
            "attributes": {"objectid": 5, "name": "Golden Gate Park", "district": "west", "pm25": 6.8},
            "geometry": {"x": -13635101.41, "y": 4546900.79},
        },
        {
            "attributes": {"objectid": 6, "name": "Presidio Gate", "district": "west", "pm25": 7.5},
            "geometry": {"x": -13632875.02, "y": 4551055.95},
        },
    ],
}


def query_sensor_features(
    client: HonuaClientProtocol,
    *,
    service_id: str,
    layer_id: int,
    where: str = "1=1",
) -> dict[str, Any]:
    """Query a live Honua layer and return the raw Esri JSON response.

    This is the only helper that touches the network. The notebook's "live"
    cell calls it; tests and the pure-Python path use :data:`DEMO_SENSOR_RESPONSE`
    instead. The returned dict has the same shape as the demo fixture, so the
    downstream helpers below work identically either way.
    """
    return client.query_features(
        service_id=service_id,
        layer_id=layer_id,
        where=where,
        out_fields=["*"],
        return_geometry=True,
    )


def response_to_geodataframe(
    response: dict[str, Any],
    *,
    working_crs: str = WORKING_CRS,
) -> "gpd.GeoDataFrame":
    """Convert a query response to a GeoDataFrame projected to ``working_crs``.

    Falls back to ``working_crs`` when the response carries no spatial
    reference so buffer distances remain in metres.
    """
    gdf = features_to_geodataframe(response)
    if gdf.crs is None:
        gdf = gdf.set_crs(working_crs)
    elif gdf.crs.to_string() != working_crs:
        gdf = gdf.to_crs(working_crs)
    return gdf


def buffer_sensors(
    sensors_gdf: "gpd.GeoDataFrame",
    *,
    distance_meters: float = DEFAULT_BUFFER_METERS,
) -> "gpd.GeoDataFrame":
    """Return a copy with point geometries replaced by metre-based buffers.

    Requires a projected (metric) CRS; reproject with
    :func:`response_to_geodataframe` first.
    """
    if sensors_gdf.crs is None:
        raise ValueError("buffer_sensors requires a projected CRS (metres); CRS is unset.")

    buffered = sensors_gdf.copy()
    buffered["geometry"] = buffered.geometry.buffer(distance_meters)
    return buffered


def join_points_to_buffers(
    sensors_gdf: "gpd.GeoDataFrame",
    buffers_gdf: "gpd.GeoDataFrame",
) -> "gpd.GeoDataFrame":
    """Spatial-join sensor points to the buffers that contain them.

    Counts how many sensors fall inside each sensor's buffer (i.e. neighbour
    density). Returns the points frame with an added ``neighbors_in_buffer``
    column (a self-count of 1 means an isolated sensor).
    """
    points = sensors_gdf[["objectid", "name", "geometry"]].copy()
    buffers = buffers_gdf[["objectid", "geometry"]].rename(
        columns={"objectid": "buffer_objectid"}
    )

    joined = gpd.sjoin(points, buffers, how="inner", predicate="within")
    counts = (
        joined.groupby("objectid").size().rename("neighbors_in_buffer").reset_index()
    )

    result = sensors_gdf.merge(counts, on="objectid", how="left")
    result["neighbors_in_buffer"] = (
        result["neighbors_in_buffer"].fillna(1).astype("int64")
    )
    return gpd.GeoDataFrame(result, geometry="geometry", crs=sensors_gdf.crs)


def dissolve_by_district(
    sensors_gdf: "gpd.GeoDataFrame",
) -> "gpd.GeoDataFrame":
    """Dissolve sensor points into one multi-point geometry per district.

    Aggregates the mean ``pm25`` per district alongside the dissolved geometry,
    giving a compact per-district view.
    """
    dissolved = sensors_gdf.dissolve(by="district", aggfunc={"pm25": "mean"})
    return dissolved.reset_index()


def summarize_by_district(
    sensors_gdf: "gpd.GeoDataFrame",
) -> "gpd.GeoDataFrame":
    """Return a per-district summary table (no geometry).

    Columns: ``district``, ``sensor_count``, ``mean_pm25``, ``max_pm25``.
    Sorted by ``mean_pm25`` descending so the dirtiest districts surface first.
    """
    grouped = sensors_gdf.groupby("district")
    summary = grouped.agg(
        sensor_count=("objectid", "size"),
        mean_pm25=("pm25", "mean"),
        max_pm25=("pm25", "max"),
    ).reset_index()
    summary["mean_pm25"] = summary["mean_pm25"].round(2)
    return summary.sort_values("mean_pm25", ascending=False).reset_index(drop=True)


def run_demo_analysis(
    *,
    buffer_meters: float = DEFAULT_BUFFER_METERS,
) -> dict[str, Any]:
    """Run the full pure-Python walkthrough against the demo fixture.

    Returns a dict of intermediate artifacts so both the notebook and the test
    can assert on the same results without a live server.
    """
    sensors = response_to_geodataframe(DEMO_SENSOR_RESPONSE)
    buffers = buffer_sensors(sensors, distance_meters=buffer_meters)
    joined = join_points_to_buffers(sensors, buffers)
    dissolved = dissolve_by_district(sensors)
    summary = summarize_by_district(sensors)
    return {
        "sensors": sensors,
        "buffers": buffers,
        "joined": joined,
        "dissolved": dissolved,
        "summary": summary,
    }
