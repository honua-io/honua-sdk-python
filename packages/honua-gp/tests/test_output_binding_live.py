"""Live-server proof for honua-sdk-python#226: GP outputs bind to real job results.

Skipped unless ``HONUA_GP_LIVE_BASE_URL`` points at a seeded client-compat
honua-server (see ``test_describe_list_fields_live.py`` for the docker recipe).
``HONUA_GP_LIVE_API_KEY`` is sent when set; ``HONUA_GP_LIVE_SERVICE_ID``
defaults to ``test_service``.

The oracles do not come from honua_gp. The input points are read straight from
the FeatureServer query endpoint with httpx, and the expected outputs are
computed here from those points:

* Buffer 25 m, dissolve ALL: one feature whose ``COUNT`` is the input count,
  that contains every input point, and whose vertices all lie 25 m (ground
  distance) from the nearest input point.
* Project to EPSG:3857: one point per input point at the spherical-Mercator
  coordinates computed from its longitude/latitude.
* Dissolve: one MultiPoint whose coordinates are the input points.
* Buffer 25 m per point, then Dissolve of that output: one polygon per located
  point, then one feature whose part count is the number of groups of points
  under 50 m apart, covering every point with vertices 25 m from the nearest.

Results that are gone after a job succeeds: honua-server keeps a terminal job
record in its Redis job store for a fixed 7 days, and ``/jobs/{id}/results``
rebuilds an expired result package from that record, so a test cannot wait
for real expiry. Set ``HONUA_GP_LIVE_REDIS`` to the ``host:port`` of the
server's Redis to delete a successful job's record before its results are
read, which is the state expiry or store loss leaves behind.
"""

from __future__ import annotations

import json
import math
import os
import socket
from typing import Any

import httpx
import pytest
from honua_sdk.errors import HonuaHttpError

import honua_gp

_BASE_URL = os.environ.get("HONUA_GP_LIVE_BASE_URL")
_API_KEY = os.environ.get("HONUA_GP_LIVE_API_KEY")
_REDIS = os.environ.get("HONUA_GP_LIVE_REDIS")
_SERVICE = os.environ.get("HONUA_GP_LIVE_SERVICE_ID", "test_service")
INPUT = f"honua://services/{_SERVICE}/0"
UNREACHABLE = f"honua://services/{_SERVICE}/99"
_WGS84_RADIUS_M = 6378137.0
_UNKNOWN_JOB_ID = "gp-00000000000000000000000000000000"

pytestmark = pytest.mark.skipif(
    not _BASE_URL,
    reason="set HONUA_GP_LIVE_BASE_URL to run the #226 output-binding proof against a seeded honua-server.",
)


@pytest.fixture(autouse=True)
def _live_session():
    honua_gp.reset()
    honua_gp.configure(base_url=_BASE_URL, api_key=_API_KEY)
    # Workspace layer 0 is the input, so a layer-0 fallback reads the input points.
    honua_gp.env.workspace = f"honua://services/{_SERVICE}"
    honua_gp.env.overwriteOutput = True
    yield
    honua_gp.reset()


def _query(where: str) -> list[dict[str, Any]]:
    headers = {"X-API-Key": _API_KEY} if _API_KEY else {}
    response = httpx.get(
        f"{str(_BASE_URL).rstrip('/')}/rest/services/{_SERVICE}/FeatureServer/0/query",
        params={"where": where, "outFields": "objectid", "returnGeometry": "true", "outSR": "4326", "f": "json"},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["features"]


@pytest.fixture(scope="module")
def input_features() -> list[dict[str, Any]]:
    return _query("1=1")


@pytest.fixture(scope="module")
def input_points(input_features: list[dict[str, Any]]) -> list[tuple[float, float]]:
    # The client-compat seed includes rows without geometry; they have no location to buffer or project.
    points = [
        (feature["geometry"]["x"], feature["geometry"]["y"]) for feature in input_features if feature.get("geometry")
    ]
    assert len(points) >= 2
    return points


def _rows(name: str, fields: list[str]) -> list[tuple[Any, ...]]:
    with honua_gp.da.SearchCursor(name, fields) as cursor:
        return list(cursor)


def _ground_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    mean_latitude = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(mean_latitude) * _WGS84_RADIUS_M
    dy = math.radians(b[1] - a[1]) * _WGS84_RADIUS_M
    return math.hypot(dx, dy)


def _polygons(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    assert geometry["type"] == "MultiPolygon"
    return geometry["coordinates"]


def _ring_contains(ring: list[list[float]], point: tuple[float, float]) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _covers(geometry: dict[str, Any], point: tuple[float, float]) -> bool:
    return any(
        _ring_contains(polygon[0], point) and not any(_ring_contains(hole, point) for hole in polygon[1:])
        for polygon in _polygons(geometry)
    )


def _mercator(point: tuple[float, float]) -> tuple[float, float]:
    lon, lat = point
    return (
        _WGS84_RADIUS_M * math.radians(lon),
        _WGS84_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


class _Delegate:
    def __init__(self, real: Any) -> None:
        self._real = real

    def execute(self, process_id: str, payload: dict[str, Any]) -> Any:
        return self._real.execute(process_id, payload)

    def job(self, job_id: str) -> Any:
        return self._real.job(job_id)

    def job_results(self, job_id: str) -> Any:
        return self._real.job_results(job_id)

    def dismiss_job(self, job_id: str) -> Any:
        return self._real.dismiss_job(job_id)


class _DismissOnSubmit(_Delegate):
    """Cancels each job through the server's DELETE /jobs/{id} right after submission."""

    def execute(self, process_id: str, payload: dict[str, Any]) -> Any:
        response = self._real.execute(process_id, payload)
        self._real.dismiss_job(response["jobID"])
        return response


class _ResultsGone(_Delegate):
    """Fetches results the server no longer has.

    honua-server refuses to dismiss a terminal job (HTTP 409); asking for the
    results of a job id the server does not know returns the not-found
    response an expired job gets. ``_JobRecordLost`` removes a real job's record.
    """

    def job_results(self, job_id: str) -> Any:
        return self._real.job_results(_UNKNOWN_JOB_ID)


def _redis_del(*keys: str) -> int:
    host, _, port = str(_REDIS).rpartition(":")
    command = [b"DEL", *(key.encode() for key in keys)]
    request = b"*%d\r\n" % len(command) + b"".join(b"$%d\r\n%s\r\n" % (len(part), part) for part in command)
    with socket.create_connection((host, int(port)), timeout=10) as connection:
        connection.sendall(request)
        reply = connection.recv(64)
    assert reply.startswith(b":"), reply
    return int(reply[1:].strip())


class _JobRecordLost(_Delegate):
    """Deletes a successful job's record from the server's job store, then reads its results."""

    def __init__(self, real: Any) -> None:
        super().__init__(real)
        self.statuses: list[str] = []

    def job_results(self, job_id: str) -> Any:
        self.statuses.append(self._real.job(job_id)["status"])
        assert _redis_del(f"controlplane:job:{job_id}", f"controlplane:job:gp-result:{job_id}") >= 1
        return self._real.job_results(job_id)


def test_buffer_output_is_the_job_result_then_dissolve(
    input_features: list[dict[str, Any]], input_points: list[tuple[float, float]]
) -> None:
    count = len(input_points)
    assert honua_gp.management.GetCount(INPUT) == len(input_features)

    result = honua_gp.analysis.Buffer(INPUT, "gp226_buffer", "25 Meters", dissolve_option="ALL")
    assert str(result) == result[0] == result.getOutput(0) == "gp226_buffer"
    assert honua_gp.management.GetCount(result[0]) == 1

    [(shape, buffered_count)] = _rows("gp226_buffer", ["SHAPE@JSON", "COUNT"])
    geometry = json.loads(shape)
    assert buffered_count == count
    assert all(_covers(geometry, point) for point in input_points)
    vertices = [
        (vertex[0], vertex[1]) for polygon in _polygons(geometry) for ring in polygon for vertex in ring
    ]
    distances = [min(_ground_distance_m(vertex, point) for point in input_points) for vertex in vertices]
    assert 24.5 <= min(distances)
    assert max(distances) <= 25.5

    with pytest.raises(honua_gp.ExecuteError) as where_info:
        _rows_filtered = honua_gp.da.SearchCursor("gp226_buffer", ["COUNT"], "COUNT > 1")
        with _rows_filtered as cursor:
            list(cursor)
    assert where_info.value.error_kind == "unsupported_output_operation"

    # The inline result is not a server layer: a layer-aware tool that only
    # reads layers refuses it, and the requested output stays unbound instead
    # of reading layer 0.
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.analysis.SpatialJoin("gp226_buffer", INPUT, "gp226_chained")
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount("gp226_chained")

    dissolved = honua_gp.management.Dissolve(INPUT, "gp226_dissolved")
    assert honua_gp.management.GetCount(dissolved[0]) == 1
    [(dissolved_shape,)] = _rows("gp226_dissolved", ["SHAPE@JSON"])
    dissolved_geometry = json.loads(dissolved_shape)
    assert dissolved_geometry["type"] == "MultiPoint"
    assert {(round(x, 9), round(y, 9)) for x, y in dissolved_geometry["coordinates"]} == {
        (round(x, 9), round(y, 9)) for x, y in input_points
    }


def _cluster_count(points: list[tuple[float, float]], threshold_m: float) -> int:
    """Connected groups of points closer than ``threshold_m`` (union-find)."""

    parent = list(range(len(points)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            if _ground_distance_m(points[i], points[j]) < threshold_m:
                parent[find(i)] = find(j)
    return len({find(index) for index in range(len(points))})


def _vertex_distances(geometry: dict[str, Any], points: list[tuple[float, float]]) -> list[float]:
    vertices = [(vertex[0], vertex[1]) for polygon in _polygons(geometry) for ring in polygon for vertex in ring]
    return [min(_ground_distance_m(vertex, point) for point in points) for vertex in vertices]


def test_buffer_output_chains_into_dissolve(
    input_features: list[dict[str, Any]], input_points: list[tuple[float, float]]
) -> None:
    buffered = honua_gp.analysis.Buffer(INPUT, "gp226_each", "25 Meters", dissolve_option="NONE")

    # One 25 m polygon per located input row (rows without geometry have nothing to buffer).
    assert honua_gp.management.GetCount(buffered[0]) == len(input_points)
    polygons = [json.loads(shape) for (shape,) in _rows("gp226_each", ["SHAPE@JSON"])]
    assert all(any(_covers(polygon, point) for polygon in polygons) for point in input_points)
    for polygon in polygons:
        distances = _vertex_distances(polygon, input_points)
        assert 24.5 <= min(distances)
        assert max(distances) <= 25.5

    dissolved = honua_gp.management.Dissolve(buffered[0], "gp226_each_dissolved")

    assert honua_gp.management.GetCount(dissolved[0]) == 1
    [(shape,)] = _rows("gp226_each_dissolved", ["SHAPE@JSON"])
    geometry = json.loads(shape)
    # Disks around points under 50 m apart merge; every other disk stays its own part.
    assert len(_polygons(geometry)) == _cluster_count(input_points, 50.0)
    assert all(_covers(geometry, point) for point in input_points)
    distances = _vertex_distances(geometry, input_points)
    assert 24.5 <= min(distances)
    assert max(distances) <= 25.5
    assert honua_gp.management.GetCount(INPUT) == len(input_features)


def test_project_output_matches_independent_mercator(
    input_features: list[dict[str, Any]], input_points: list[tuple[float, float]]
) -> None:
    result = honua_gp.management.Project(INPUT, "gp226_mercator", 3857)

    assert honua_gp.management.GetCount(result[0]) == len(input_features)
    projected = sorted(
        tuple(json.loads(shape)["coordinates"][:2]) for (shape,) in _rows("gp226_mercator", ["SHAPE@JSON"]) if shape
    )
    expected = sorted(_mercator(point) for point in input_points)
    assert len(projected) == len(expected)
    for (got_x, got_y), (want_x, want_y) in zip(projected, expected):
        assert got_x == pytest.approx(want_x, abs=0.01)
        assert got_y == pytest.approx(want_y, abs=0.01)


def test_empty_output_is_a_bound_zero_feature_result() -> None:
    where = "objectid > 1000000"
    assert _query(where) == []

    result = honua_gp.analysis.Buffer(INPUT, "gp226_empty", "25 Meters", where_clause=where)

    assert honua_gp.management.GetCount(result[0]) == 0
    assert _rows("gp226_empty", ["SHAPE@JSON"]) == []


def test_failed_and_cancelled_overwrites_keep_the_prior_output(input_features: list[dict[str, Any]]) -> None:
    honua_gp.management.Project(INPUT, "gp226_prior", 3857)
    prior = honua_gp.get_session().get_layer("gp226_prior")
    assert prior is not None

    with pytest.raises(honua_gp.ExecuteError):
        honua_gp.analysis.Buffer(UNREACHABLE, "gp226_prior", "25 Meters")
    assert honua_gp.get_session().get_layer("gp226_prior") is prior

    honua_gp.configure(processes_client=_DismissOnSubmit(honua_gp.get_session().processes_client()))
    with pytest.raises(honua_gp.ExecuteError) as info:
        honua_gp.analysis.Buffer(INPUT, "gp226_prior", "25 Meters")
    assert info.value.error_kind == "dismissed"

    assert honua_gp.get_session().get_layer("gp226_prior") is prior
    assert honua_gp.management.GetCount("gp226_prior") == len(input_features)


def test_unbound_outputs_never_fall_back_to_layer_zero(input_features: list[dict[str, Any]]) -> None:
    real = honua_gp.get_session().processes_client()

    with pytest.raises(honua_gp.ExecuteError):
        honua_gp.analysis.Buffer(UNREACHABLE, "gp226_failed", "25 Meters")

    honua_gp.configure(processes_client=_DismissOnSubmit(real))
    with pytest.raises(honua_gp.ExecuteError) as cancelled:
        honua_gp.analysis.Buffer(INPUT, "gp226_cancelled", "25 Meters")
    assert cancelled.value.error_kind == "dismissed"

    honua_gp.configure(processes_client=_ResultsGone(real))
    with pytest.raises(honua_gp.ExecuteError) as expired:
        honua_gp.analysis.Buffer(INPUT, "gp226_expired", "25 Meters")
    assert expired.value.error_kind == "missing_output"

    # Each name would count the workspace's layer 0 (the input) if it fell back.
    assert honua_gp.management.GetCount(INPUT) == len(input_features)
    for name in ("gp226_failed", "gp226_cancelled", "gp226_expired"):
        assert honua_gp.get_session().get_layer(name) is None
        with pytest.raises(honua_gp.HonuaGpResolveError):
            honua_gp.management.GetCount(name)


@pytest.mark.skipif(
    not _REDIS,
    reason="set HONUA_GP_LIVE_REDIS=<host:port> of the server's Redis to remove a successful job's record.",
)
def test_results_gone_after_success_are_a_typed_missing_output(
    input_features: list[dict[str, Any]], input_points: list[tuple[float, float]]
) -> None:
    real = honua_gp.get_session().processes_client()
    honua_gp.analysis.Buffer(INPUT, "gp226_lost", "25 Meters", dissolve_option="ALL")
    prior = honua_gp.get_session().get_layer("gp226_lost")
    assert prior is not None

    lost = _JobRecordLost(real)
    honua_gp.configure(processes_client=lost)
    for name in ("gp226_lost", "gp226_lost_new"):
        with pytest.raises(honua_gp.ExecuteError) as info:
            honua_gp.analysis.Buffer(INPUT, name, "25 Meters", dissolve_option="ALL")
        assert info.value.error_kind == "missing_output"
        assert isinstance(info.value.__cause__, HonuaHttpError)
        assert info.value.__cause__.status_code == 404
    # Both jobs really succeeded before their records were removed.
    assert lost.statuses == ["successful", "successful"]

    honua_gp.configure(processes_client=real)
    # The overwrite whose results were lost left the prior output bound to its own result.
    assert honua_gp.get_session().get_layer("gp226_lost") is prior
    [(shape, buffered_count)] = _rows("gp226_lost", ["SHAPE@JSON", "COUNT"])
    assert buffered_count == len(input_points)
    assert all(_covers(json.loads(shape), point) for point in input_points)
    # The new name is unbound rather than the workspace's layer 0.
    assert honua_gp.get_session().get_layer("gp226_lost_new") is None
    with pytest.raises(honua_gp.HonuaGpResolveError):
        honua_gp.management.GetCount("gp226_lost_new")
    assert honua_gp.management.GetCount(INPUT) == len(input_features)
