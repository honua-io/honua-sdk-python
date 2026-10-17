"""Actual installed-SDK operations missing from the original REST certification slice.

The shared park edit fixture is mapped onto the maintained client-compat layer's
name/ratio fields. Only newly allocated, marker-bound scratch features are edited.
gRPC reads use that seed's authored alpha/beta points, through the public factory.
"""
from __future__ import annotations

from collections.abc import Mapping
import math
from typing import TYPE_CHECKING, Any
import uuid

from honua_sdk import HonuaClient

if TYPE_CHECKING:
    from scripts._conformance import ConformanceTarget, FixtureBundle


def _require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _attributes(feature: Mapping[str, Any]) -> dict[str, Any]:
    attrs = feature.get("attributes")
    _require(isinstance(attrs, Mapping), "feature is missing attributes")
    return {str(key).lower(): value for key, value in attrs.items()}


def _grpc_query(client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle, *, stream: bool) -> dict[str, Any]:
    import grpc
    from honua_sdk import HonuaGrpcError
    from honua_sdk.grpc import QueryFeaturesRequest, SpatialReference

    _require(target.grpc_target, "HONUA_GRPC_TARGET must identify the pinned candidate's gRPC listener")
    target.grpc_base_url()
    fixture = "feature_query_stream" if stream else "feature_query"
    invalid = bundle.request(f"{fixture}_invalid")
    invalid_status = bundle._load(bundle.fixtures_dir / f"{fixture}_invalid_status.json")
    _require(invalid_status.get("name") == "NOT_FOUND" and invalid_status.get("code") == 5,
             "shared negative query fixture must require NOT_FOUND")
    _require(invalid.get("serviceId") == "no-such-service", "unexpected shared missing-service fixture")
    # The client-compat seed is selected from the same full source SHA as the running image.
    # These are authored fixture values, independent of a second protocol agreeing with gRPC.
    expected = {"alpha": (1, -122.49, 37.71), "beta": (2, -122.475, 37.72)}
    request = QueryFeaturesRequest(
        service_id=target.service_id, layer_id=target.layer_id,
        where="name IN ('alpha','beta')", out_fields=["name", "count"],
        return_geometry=True, out_sr=SpatialReference(wkid=4326),
        result_record_count=2, order_by="name ASC",
    )
    with client.grpc(target=target.grpc_target) as connection:
        if stream:
            pages = []
            for page in connection.query_features_stream(request):
                _require(len(pages) < 3, "candidate gRPC stream exceeded its bounded fixture")
                pages.append(page)
            _require(pages and pages[-1].is_last_page, "stream is empty or has no terminal page")
            _require(not any(page.is_last_page for page in pages[:-1]), "stream continued after its terminal page")
            features = [feature for page in pages for feature in page.features]
            envelopes = pages
        else:
            response = connection.query_features(request)
            features = response.features
            envelopes = [response]
            _require(not response.exceeded_transfer_limit, "bounded unary query was truncated")
        _require(len(features) == 2, "gRPC did not return the two authored fixture points")
        _require(all(envelope.object_id_field_name for envelope in envelopes), "gRPC object-id metadata missing")
        _require(all(envelope.spatial_reference and envelope.spatial_reference.wkid == 4326 for envelope in envelopes),
                 "gRPC spatial reference does not match the authored fixture")
        names = []
        for feature in features:
            attrs = {str(key).lower(): value for key, value in feature.attributes.items()}
            name = attrs.get("name")
            _require(name in expected, "gRPC returned an unrelated feature")
            count, x, y = expected[name]
            _require(isinstance(attrs.get("count"), int) and not isinstance(attrs["count"], bool)
                     and attrs["count"] == count, "gRPC attribute type/value differs from the seed")
            _require(isinstance(feature.id, int) and feature.id > 0, "gRPC feature id missing")
            _point(feature.geometry, x, y)
            names.append(name)
        _require(len({feature.id for feature in features}) == 2, "gRPC returned duplicate feature ids")
        _require(names == ["alpha", "beta"], "gRPC order, uniqueness or fixture coverage differs")

        missing = QueryFeaturesRequest(service_id=invalid["serviceId"], layer_id=target.layer_id)
        try:
            if stream:
                for _ in connection.query_features_stream(missing):
                    raise AssertionError("missing-service stream yielded a page")
            else:
                connection.query_features(missing)
        except HonuaGrpcError as error:
            _require(error.code == grpc.StatusCode.NOT_FOUND and bool(error.message),
                     "missing-service query did not preserve typed NOT_FOUND")
        else:
            raise AssertionError("missing-service query unexpectedly succeeded")
    return {"grpc_target": target.grpc_target, "observed_names": names, "negative_status": "NOT_FOUND",
            "page_count": len(envelopes), "terminal_page": True if stream else None}


def grpc_query(client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle) -> dict[str, Any]:
    return _grpc_query(client, target, bundle, stream=False)


def grpc_stream(client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle) -> dict[str, Any]:
    return _grpc_query(client, target, bundle, stream=True)


def _point(geometry: object, x: float, y: float) -> None:
    _require(isinstance(geometry, Mapping), "fixture point geometry missing")
    _require(all(isinstance(geometry.get(axis), (int, float)) and not isinstance(geometry[axis], bool)
                 and math.isclose(geometry[axis], expected, rel_tol=0, abs_tol=1e-8)
                 for axis, expected in (("x", x), ("y", y))), "point differs from authored fixture")


def _fixture_attributes(feature: Mapping[str, Any]) -> dict[str, Any]:
    attrs = feature["attributes"]
    # Explicit field mapping: the seeded layer has name/ratio, while the shared park fixture has NAME/AREA.
    result = {}
    for source, destination, kind in (("NAME", "name", "stringValue"), ("AREA", "ratio", "doubleValue")):
        if source in attrs:
            _require(set(attrs[source]) == {kind}, "shared edit fixture attribute has an unexpected type")
            result[destination] = attrs[source][kind]
    _require(result and len(result) == len(attrs), "shared edit fixture has unmapped attributes")
    return result


def apply_edits(client: HonuaClient, target: ConformanceTarget, bundle: FixtureBundle) -> dict[str, Any]:
    """Shared all-or-nothing missing-target case, then the real add/update/delete batch and readback."""
    baseline = bundle.response("feature_apply_edits_missing_target_verify")["features"]
    negative = bundle.request("feature_apply_edits_missing_target")
    positive = bundle.request("feature_apply_edits")
    negative_status = bundle._load(bundle.fixtures_dir / "feature_apply_edits_missing_target_status.json")
    _require(negative_status.get("name") == "NOT_FOUND" and negative_status.get("code") == 5,
             "shared missing-target fixture must require NOT_FOUND")
    _require(len(baseline) == 2 and {feature["id"] for feature in baseline} == {"7", "42"},
             "unexpected shared edit baseline")
    _require(negative.get("rollbackOnFailure") is True and positive.get("rollbackOnFailure") is True,
             "shared edit fixtures must require rollbackOnFailure")
    _require(negative.get("deletes") == ["7", "8"] and len(negative["updates"]) == 1,
             "shared missing-target fixture shape changed")
    _require(positive.get("deletes") == ["7"] and len(positive["updates"]) == 1 and len(positive["adds"]) == 1,
             "shared positive edit fixture shape changed")
    marker = "sdk-certification-" + uuid.uuid4().hex
    ids: dict[str, int] = {}

    def query(where: str) -> list[dict[str, Any]]:
        response = client.query_features(target.service_id, target.layer_id, where=where, out_fields=["*"],
                                         return_geometry=True, extra_params={"resultRecordCount": 10})
        _require(isinstance(response, Mapping) and isinstance(response.get("features"), list), "readback missing features")
        _require(response.get("exceededTransferLimit") is False, "scratch readback was truncated")
        return response["features"]

    def ours() -> dict[int, dict[str, Any]]:
        features = query(f"description = '{marker}'")
        _require(len(features) <= 4, "scratch readback is unbounded")
        rows = {}
        for feature in features:
            attrs = _attributes(feature)
            _require(attrs.get("description") == marker, "scratch readback returned another writer's feature")
            identifier = attrs.get("objectid")
            _require(isinstance(identifier, int) and not isinstance(identifier, bool) and identifier > 0,
                     "scratch readback has no valid object id")
            _require(identifier not in rows, "duplicate scratch object id")
            rows[identifier] = feature
        return rows

    def checked(result: Any, counts: tuple[int, int, int]) -> None:
        groups = (result.add_results, result.update_results, result.delete_results)
        _require(tuple(map(len, groups)) == counts and result.all_succeeded, "applyEdits response is partial or failed")
        _require(all(row.success and row.error is None for group in groups for row in group),
                 "successful applyEdits carries contradictory failures")

    def check_rows(expected: dict[str, Mapping[str, Any]]) -> None:
        actual = ours()
        _require(set(actual) == {ids[key] for key in expected}, "edit readback differs from expected feature ids")
        for key, feature in expected.items():
            row = actual[ids[key]]
            attrs = _attributes(row)
            _require(all(attrs.get(name) == value for name, value in _fixture_attributes(feature).items()),
                     "edit attributes differ from the authored fixture")
            point = feature["geometry"]["point"]
            _point(row.get("geometry"), point["x"], point["y"])

    def translated_add(feature: Mapping[str, Any]) -> dict[str, Any]:
        return {"attributes": {**_fixture_attributes(feature), "description": marker},
                "geometry": {**feature["geometry"]["point"], "spatialReference": {"wkid": 4326}}}

    try:
        seeded = client.apply_edits_result(target.service_id, target.layer_id,
                                           adds=[translated_add(feature) for feature in baseline], rollback_on_failure=True)
        checked(seeded, (2, 0, 0))
        for feature, result in zip(baseline, seeded.add_results, strict=True):
            _require(isinstance(result.object_id, int) and not isinstance(result.object_id, bool) and result.object_id > 0,
                     "add receipt omitted its allocated object id")
            ids[feature["id"]] = result.object_id
        _require(len(set(ids.values())) == 2, "baseline add returned duplicate ids")
        check_rows({feature["id"]: feature for feature in baseline})
        missing_id = 2147483647
        _require(not query(f"objectid = {missing_id}"), "negative fixture's mapped missing target already exists")
        ids["8"] = missing_id
        update = negative["updates"][0]
        failed = client.apply_edits_result(
            target.service_id, target.layer_id,
            updates=[{"attributes": {"objectid": ids[update["id"]], **_fixture_attributes(update)}}],
            deletes=[ids[key] for key in negative["deletes"]], rollback_on_failure=True,
        )
        _require(not failed.add_results and len(failed.update_results) == 1 and len(failed.delete_results) == 2,
                 "negative applyEdits response omitted operations")
        _require(not failed.all_succeeded and all(not row.success for row in (*failed.update_results, *failed.delete_results)),
                 "failed atomic batch reports a committed edit")
        missing = failed.delete_results[-1]
        _require(missing.object_id == missing_id and isinstance(missing.error, Mapping) and missing.error.get("code") == 1003,
                 "missing-target delete did not preserve GeoServices DeleteNotFound (1003)")
        check_rows({feature["id"]: feature for feature in baseline})

        update = positive["updates"][0]
        result = client.apply_edits_result(
            target.service_id, target.layer_id, adds=[translated_add(positive["adds"][0])],
            updates=[{"attributes": {"objectid": ids[update["id"]], **_fixture_attributes(update)}}],
            deletes=[ids[key] for key in positive["deletes"]], rollback_on_failure=True,
        )
        checked(result, (1, 1, 1))
        _require(result.update_results[0].object_id == ids["42"] and result.delete_results[0].object_id == ids["7"],
                 "positive update/delete receipts name different targets")
        added_id = result.add_results[0].object_id
        _require(isinstance(added_id, int) and not isinstance(added_id, bool) and added_id > 0 and added_id not in ids.values(),
                 "positive add did not allocate a distinct id")
        ids["added"] = added_id
        updated = next(feature for feature in baseline if feature["id"] == "42")
        updated = {**updated, "attributes": {**updated["attributes"], **update["attributes"]}}
        check_rows({"42": updated, "added": positive["adds"][0]})
        details = {"positive_operations": ["add", "update", "delete"], "negative_code": 1003,
                   "rollback_readback": True, "positive_readback": True, "allocated_ids": [value for key, value in ids.items() if key != "8"], "missing_target_id": missing_id}
    finally:
        remaining = ours()
        if remaining:
            cleaned = client.apply_edits_result(target.service_id, target.layer_id, deletes=list(remaining), rollback_on_failure=True)
            checked(cleaned, (0, 0, len(remaining)))
            _require(not ours(), "SDK scratch cleanup left features behind")
    return {**details, "cleanup_readback": True}
