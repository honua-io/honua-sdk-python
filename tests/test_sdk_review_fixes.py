"""Regression tests for honua-sdk URL safety, 3D geometry conversion, and pagination."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk._http import _to_transport_error
from honua_sdk._query import _bbox_values, feature_server_extra_params, query_feature_from_feature_server
from honua_sdk.auth import BearerToken
from honua_sdk.models import FeatureQuery, FeatureSet
from honua_sdk.models._geometry import geometry_to_geo_interface, geometry_to_shapely
from honua_sdk.protocols.scenes import _resolve_tileset_relative_path, _scene_asset_path


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# 1. Path Traversal in scenes.py


@pytest.mark.parametrize(
    ("base_path", "uri"),
    [
        ("tileset.json", "../secret.json"),
        ("sub/tileset.json", "../../secret.json"),
        ("tileset.json", ".."),
        ("tileset.json", "%2e%2e/secret.json"),
        ("sub/tileset.json", "a/../../../escape.b3dm"),
    ],
)
def test_resolve_tileset_relative_path_rejects_root_escape(base_path: str, uri: str) -> None:
    with pytest.raises(ValueError, match="outside|invalid|empty"):
        _resolve_tileset_relative_path(base_path, uri)


def test_resolve_tileset_relative_path_allows_in_root_normalization() -> None:
    assert _resolve_tileset_relative_path("sub/tileset.json", "../tiles/0.b3dm") == "tiles/0.b3dm"
    assert _resolve_tileset_relative_path("sub/tileset.json", "./2.b3dm?v=1") == "sub/2.b3dm?v=1"


@pytest.mark.parametrize(
    "asset_path",
    [
        "../other-scene/tileset.json",
        "tiles/../../secret.b3dm",
        "%2e%2e/secret.b3dm",
        "..",
        "https://evil.example/tiles/0.b3dm",
        "tiles\\..\\..\\secret.b3dm",
    ],
)
def test_scene_asset_path_rejects_traversal(asset_path: str) -> None:
    with pytest.raises(ValueError):
        _scene_asset_path("downtown", asset_path)


def test_scene_asset_path_allows_normalized_in_root_path() -> None:
    assert _scene_asset_path("downtown", "sub/../tiles/0.b3dm?v=2") == "/scenes/downtown/tiles/0.b3dm?v=2"


# 2. gRPC host binding & plaintext transport security


def test_grpc_rejects_cross_host_target_when_credentials_attached() -> None:
    pytest.importorskip("grpc")
    with HonuaClient("http://localhost:8080", api_key="secret-key") as client:
        with pytest.raises(ValueError, match="does not match configured client host"):
            client.grpc(target="remote.example.test:50051")


def test_grpc_rejects_plaintext_non_loopback_with_credentials_without_opt_in() -> None:
    pytest.importorskip("grpc")
    with HonuaClient("https://api.example.test", api_key="secret-key") as client:
        with pytest.raises(ValueError, match="allow_insecure_http=True"):
            client.grpc(insecure=True)


def test_grpc_checks_every_address_of_a_multi_address_target() -> None:
    pytest.importorskip("grpc")
    with HonuaClient("https://10.0.0.1", api_key="secret-key") as client:
        with pytest.raises(ValueError, match="does not match configured client host"):
            client.grpc(target="ipv4:10.0.0.1:443,203.0.113.5:443")
    with HonuaClient("http://127.0.0.1:8080", api_key="secret-key") as local_client:
        with pytest.raises(ValueError, match="does not match configured client host"):
            local_client.grpc(insecure=True, target="ipv4:127.0.0.1:50051,203.0.113.5:50051")


def test_grpc_allows_same_host_different_port_with_tls_and_loopback_plaintext() -> None:
    pytest.importorskip("grpc")
    with HonuaClient("https://api.example.test", api_key="secret-key") as client:
        grpc_client = client.grpc(target="api.example.test:50051")
        grpc_client.close()

    with HonuaClient("http://localhost:8080", api_key="secret-key") as local_client:
        local_grpc = local_client.grpc(target="localhost:50051")
        local_grpc.close()


def test_grpc_allows_anonymous_cross_host_and_plaintext() -> None:
    pytest.importorskip("grpc")
    with HonuaClient("https://api.example.test") as client:
        grpc_client = client.grpc(target="other.example.test:50051", insecure=True)
        grpc_client.close()


@pytest.mark.anyio
async def test_async_grpc_enforces_host_binding_and_transport_security() -> None:
    pytest.importorskip("grpc")
    async with AsyncHonuaClient("https://api.example.test", api_key="secret-key") as client:
        with pytest.raises(ValueError, match="does not match configured client host"):
            client.grpc(target="other.example.test:50051")
        with pytest.raises(ValueError, match="allow_insecure_http=True"):
            client.grpc(insecure=True)


# 3. Secret redaction in BearerToken and _to_transport_error


def test_bearer_token_repr_omits_access_token() -> None:
    token = BearerToken(access_token="eyJhbGciOiJSUzI1NiJ9.super-secret")
    assert "super-secret" not in repr(token)
    assert token.access_token == "eyJhbGciOiJSUzI1NiJ9.super-secret"


def test_to_transport_error_sanitizes_sensitive_query_params() -> None:
    url = "https://example.test/rest/services/roads/FeatureServer/0/query?f=json&token=tok123&api_key=key456&access_token=acc789"
    request = httpx.Request("GET", url)
    err = httpx.ConnectError(f"failed connecting to {url}", request=request)
    mapped = _to_transport_error(err)

    assert "tok123" not in str(mapped)
    assert "key456" not in str(mapped)
    assert "acc789" not in str(mapped)
    assert mapped.url is not None  # type: ignore[attr-defined]
    assert "tok123" not in mapped.url  # type: ignore[attr-defined]
    assert "key456" not in mapped.url  # type: ignore[attr-defined]
    assert "acc789" not in mapped.url  # type: ignore[attr-defined]
    assert "f=json" in mapped.url  # type: ignore[attr-defined]
    assert "token=[REDACTED]" in mapped.url  # type: ignore[attr-defined]


# 4. 3D Z/M geometry handling & 6-element BBox


def test_geopandas_esri_to_shapely_preserves_3d_slices_4d_and_drops_m_only() -> None:
    pytest.importorskip("geopandas")
    pytest.importorskip("shapely")
    from honua_sdk.geopandas import _geoservices_geometry_to_shapely, features_to_geodataframe

    pt_3d = _geoservices_geometry_to_shapely({"x": 1.0, "y": 2.0, "z": 3.5})
    assert pt_3d.has_z
    assert (pt_3d.x, pt_3d.y, pt_3d.z) == (1.0, 2.0, 3.5)

    line_4d = _geoservices_geometry_to_shapely(
        {"hasZ": True, "hasM": True, "paths": [[[0.0, 0.0, 10.0, 100.0], [1.0, 1.0, 20.0, 200.0]]]}
    )
    assert line_4d.has_z
    assert list(line_4d.coords) == [(0.0, 0.0, 10.0), (1.0, 1.0, 20.0)]

    mp_4d = _geoservices_geometry_to_shapely(
        {"hasZ": True, "hasM": True, "points": [[1.0, 2.0, 3.0, 99.0], [4.0, 5.0, 6.0, 88.0]]}
    )
    assert mp_4d.has_z
    assert [tuple(p.coords[0]) for p in mp_4d.geoms] == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]

    poly_4d = _geoservices_geometry_to_shapely(
        {
            "hasZ": True,
            "hasM": True,
            "rings": [[[0, 0, 5, 1], [0, 10, 5, 2], [10, 10, 5, 3], [10, 0, 5, 4], [0, 0, 5, 1]]],
        }
    )
    assert poly_4d.has_z
    assert poly_4d.exterior.coords[0] == (0.0, 0.0, 5.0)

    # M-only (hasM=True, hasZ=False) must slice to 2D so M is not treated as Z.
    gdf_m_only = features_to_geodataframe(
        {
            "hasM": True,
            "hasZ": False,
            "spatialReference": {"wkid": 4326},
            "features": [
                {
                    "attributes": {"id": 1},
                    "geometry": {"paths": [[[0.0, 0.0, 500.0], [1.0, 1.0, 600.0]]]},
                }
            ],
        }
    )
    geom_m_only = gdf_m_only.geometry.iloc[0]
    assert not geom_m_only.has_z
    assert list(geom_m_only.coords) == [(0.0, 0.0), (1.0, 1.0)]


def test_geopandas_shapely_to_esri_preserves_z_and_sets_has_z() -> None:
    pytest.importorskip("geopandas")
    from shapely.geometry import LineString, MultiPoint, Point, Polygon

    from honua_sdk.geopandas import _shapely_to_geoservices_geometry

    pt = _shapely_to_geoservices_geometry(Point(1.0, 2.0, 3.0))
    assert pt == {"x": 1.0, "y": 2.0, "z": 3.0, "hasZ": True}

    mp = _shapely_to_geoservices_geometry(MultiPoint([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]))
    assert mp is not None
    assert mp["hasZ"] is True
    assert mp["points"] == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]

    line = _shapely_to_geoservices_geometry(LineString([(0.0, 0.0, 1.0), (1.0, 1.0, 2.0)]))
    assert line is not None
    assert line["hasZ"] is True
    assert line["paths"] == [[[0.0, 0.0, 1.0], [1.0, 1.0, 2.0]]]

    poly = _shapely_to_geoservices_geometry(
        Polygon([(0, 0, 5), (10, 0, 5), (10, 10, 5), (0, 10, 5), (0, 0, 5)])
    )
    assert poly is not None
    assert poly["hasZ"] is True
    assert len(poly["rings"][0][0]) == 3
    assert poly["rings"][0][0][2] == 5.0

    # 2D geometries should not advertise hasZ.
    pt_2d = _shapely_to_geoservices_geometry(Point(1.0, 2.0))
    assert pt_2d == {"x": 1.0, "y": 2.0}


def test_feature_set_propagates_root_has_z_and_has_m_to_geometry_bridge() -> None:
    pytest.importorskip("shapely")
    feature_set_z = FeatureSet.from_dict(
        {
            "hasZ": True,
            "features": [
                {
                    "attributes": {"objectid": 1},
                    "geometry": {"paths": [[[0.0, 0.0, 12.0], [1.0, 1.0, 15.0]]]},
                }
            ],
        }
    )
    feat = feature_set_z.features[0]
    assert feat.__geo_interface__ == {
        "type": "LineString",
        "coordinates": [[0.0, 0.0, 12.0], [1.0, 1.0, 15.0]],
    }
    shape = feat.to_shapely()
    assert shape is not None and shape.has_z

    qf = query_feature_from_feature_server(feat, source="roads", protocol="geoservices-feature-service")
    qf_shape = qf.to_shapely()
    assert qf_shape is not None and qf_shape.has_z

    # Direct helper with default_has_m=True and default_has_z=False drops M.
    m_only = geometry_to_geo_interface(
        {"paths": [[[0.0, 0.0, 99.0], [1.0, 1.0, 100.0]]]},
        default_has_z=False,
        default_has_m=True,
    )
    assert m_only == {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 1.0]]}
    assert geometry_to_shapely({"paths": [[[0.0, 0.0, 99.0], [1.0, 1.0, 100.0]]]}, default_has_m=True) is not None


def test_six_element_3d_bbox_accepted() -> None:
    assert _bbox_values((-158.0, 21.0, -10.0, -157.0, 22.0, 500.0)) == (
        -158.0,
        21.0,
        -10.0,
        -157.0,
        22.0,
        500.0,
    )
    assert _bbox_values("-158,21,-10,-157,22,500") == (-158.0, 21.0, -10.0, -157.0, 22.0, 500.0)

    params = feature_server_extra_params(
        FeatureQuery(source="roads", bbox=(-158.0, 21.0, -10.0, -157.0, 22.0, 500.0))
    )
    envelope = json.loads(params["geometry"])
    assert envelope["xmin"] == -158.0
    assert envelope["zmin"] == -10.0
    assert envelope["zmax"] == 500.0

    with pytest.raises(ValueError, match="4 values.*6 values"):
        _bbox_values((0, 0, 10))
    with pytest.raises(ValueError, match="4 values.*6 values"):
        _bbox_values((0, 0, 0, 10, 10))


# 5. OGC pagination last-page loop prevention


def test_ogc_iter_items_stops_on_exact_page_size_when_links_present_without_next() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert calls <= 2, "infinite pagination loop detected"
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}, {"id": 2}],
                "links": [{"rel": "self", "href": str(request.url)}],
            },
        )

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        items = list(client.ogc_features().collection("parcels").iter_items(page_size=2, max_pages=None))

    assert [i["id"] for i in items] == [1, 2]
    assert calls == 1


def test_ogc_iter_items_stops_when_number_matched_reached_without_links() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert calls <= 2
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "numberMatched": 2,
                "features": [{"id": 1}, {"id": 2}],
            },
        )

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        items = list(client.ogc_features().collection("parcels").iter_items(page_size=2, max_pages=None))

    assert [i["id"] for i in items] == [1, 2]
    assert calls == 1


def test_ogc_iter_items_offset_pages_while_number_matched_exceeds_fetched_despite_self_link() -> None:
    offsets: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = request.url.params.get("offset")
        offsets.append(offset)
        assert len(offsets) <= 3, "pagination did not stop at numberMatched"
        start = int(offset or 0)
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "numberMatched": 4,
                "features": [{"id": start + 1}, {"id": start + 2}],
                "links": [{"rel": "self", "href": str(request.url)}],
            },
        )

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        items = list(client.ogc_features().collection("parcels").iter_items(page_size=2, max_pages=None))

    assert [i["id"] for i in items] == [1, 2, 3, 4]
    assert len(offsets) == 2


@pytest.mark.anyio
async def test_async_ogc_iter_items_stops_on_exact_page_size_without_next_link() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert calls <= 2, "infinite async pagination loop detected"
        return httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [{"id": 1}, {"id": 2}],
                "links": [{"rel": "self", "href": str(request.url)}],
            },
        )

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        items = [
            item
            async for item in client.ogc_features().collection("parcels").iter_items(page_size=2, max_pages=None)
        ]

    assert [i["id"] for i in items] == [1, 2]
    assert calls == 1


# 6. Geoprocessing sub-path prefix & output CRS


def test_geoprocessing_href_does_not_double_prefix_subpath() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, content=b"geotiff-bytes")

    with HonuaClient("https://example.test/honua/", transport=httpx.MockTransport(handler)) as client:
        gp = client.geoprocessing()
        data_abs = gp.result_raster_bytes(
            {"out": {"kind": "Raster", "href": "https://example.test/honua/ogc/processes/jobs/j1/out.tif"}}
        )
        data_rel = gp.result_raster_bytes(
            {"out": {"kind": "Raster", "href": "/honua/ogc/processes/jobs/j1/out2.tif"}}
        )

    assert data_abs == b"geotiff-bytes"
    assert data_rel == b"geotiff-bytes"
    assert seen_paths == [
        "/honua/ogc/processes/jobs/j1/out.tif",
        "/honua/ogc/processes/jobs/j1/out2.tif",
    ]


def test_execute_dataframe_respects_payload_and_parameter_crs() -> None:
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    src = gpd.GeoDataFrame({"name": ["a"]}, geometry=[Point(-157.8583, 21.3069)], crs="EPSG:4326").to_crs("EPSG:3857")
    fc_with_crs = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:26904"}},
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [618000.0, 2356000.0]}, "properties": {"name": "a"}}
        ],
    }
    fc_plain = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-157.8583, 21.3069]}, "properties": {"name": "a"}}
        ],
    }

    def _make_handler(payload: dict[str, Any]) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(201, json={"jobID": "j1", "status": "accepted"})
            if request.url.path.endswith("/jobs/j1"):
                return httpx.Response(200, json={"jobID": "j1", "status": "successful"})
            return httpx.Response(200, json={"outputFeatureLayer": payload})

        return httpx.MockTransport(handler)

    # A payload-declared CRS (26904) is read as such, then reprojected back to source_crs (3857).
    with HonuaClient("http://example.test", transport=_make_handler(fc_with_crs)) as client:
        out_payload_crs = client.geoprocessing().execute_dataframe("geometry.buffer", src, poll_interval=0.0)
    assert out_payload_crs.crs is not None
    assert out_payload_crs.crs.to_epsg() == 3857
    expected = gpd.GeoSeries([Point(618000.0, 2356000.0)], crs="EPSG:26904").to_crs("EPSG:3857")
    assert out_payload_crs.geometry.iloc[0].distance(expected.iloc[0]) < 1e-3

    # Reprojection parameter targetSrid prevents overwriting back to source_crs (3857).
    with HonuaClient("http://example.test", transport=_make_handler(fc_plain)) as client:
        out_reprojected = client.geoprocessing().execute_dataframe(
            "conversion.feature-project", src, parameters={"targetSrid": 4326}, poll_interval=0.0
        )
    assert out_reprojected.crs is not None
    assert out_reprojected.crs.to_epsg() == 4326
