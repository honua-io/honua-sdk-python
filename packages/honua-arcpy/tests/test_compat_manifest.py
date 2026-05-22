"""Compatibility manifest invariants."""

from __future__ import annotations

import honua_arcpy
from honua_arcpy._compat import COMPAT


def test_manifest_covers_45_functions_across_three_families() -> None:
    families = {"analysis": 0, "management": 0, "da": 0}
    for name in COMPAT:
        family = name.split(".", 1)[0]
        assert family in families, f"Unexpected family {family!r}"
        families[family] += 1
    assert families == {"analysis": 15, "management": 20, "da": 10}
    assert len(COMPAT) == 45


def test_every_manifest_entry_has_backend_and_status() -> None:
    valid_backends = {"process", "source", "admin", "session", "not_implemented"}
    valid_statuses = {"supported", "partial", "stub"}
    for name, entry in COMPAT.items():
        assert entry.backend in valid_backends, f"{name}: bad backend {entry.backend!r}"
        assert entry.status in valid_statuses, f"{name}: bad status {entry.status!r}"


def test_process_entries_carry_process_id() -> None:
    for name, entry in COMPAT.items():
        if entry.backend == "process":
            assert entry.process_id, f"{name}: process backend missing process_id"


def test_stub_entries_carry_replacement_hint_and_tracking() -> None:
    for name, entry in COMPAT.items():
        if entry.status == "stub":
            assert entry.replacement_hint, f"{name}: stub missing replacement_hint"
            assert entry.tracking, f"{name}: stub missing tracking"


def test_public_top_level_reexports_exist() -> None:
    expected = {
        "configure",
        "configure_from_env",
        "analysis",
        "management",
        "da",
        "env",
        "ExecuteError",
        "HonuaArcpyUnsupportedError",
        "HonuaArcpyConfigurationError",
        "Describe",
        "DescribeResult",
        "FieldDescribe",
        "Selection",
        "GetCount",
        "COMPAT",
    }
    missing = expected - set(dir(honua_arcpy))
    assert not missing, f"Missing top-level exports: {sorted(missing)}"


def test_legacy_suffix_aliases_are_exported() -> None:
    # Real arcpy exposes both ``arcpy.analysis.Buffer`` and
    # ``arcpy.Buffer_analysis``. The shim mirrors the suffix form for the
    # top-of-corpus entries so unmodified scripts keep importing -- the
    # underlying shim may currently raise ``HonuaArcpyUnsupportedError``
    # for process-backed entries until the projection adapter lands, but
    # the suffix-aliased reference must still resolve to the same callable.
    assert honua_arcpy.Buffer_analysis is honua_arcpy.analysis.Buffer
    assert honua_arcpy.Clip_analysis is honua_arcpy.analysis.Clip
    assert honua_arcpy.CalculateField_management is honua_arcpy.management.CalculateField
    assert honua_arcpy.MakeFeatureLayer_management is honua_arcpy.management.MakeFeatureLayer
    assert honua_arcpy.GetCount_management is honua_arcpy.management.GetCount


def test_process_backed_entries_match_honua_server_catalog() -> None:
    """Contract guard: every ``backend="process"`` entry's ``param_map``
    values must form a subset of the inputs the corresponding honua-server
    process accepts. The reference is a hand-maintained snapshot of
    ``Honua.Server.Features.Geoprocessing.BuiltInProcessCatalog`` (see
    ``packages/honua-arcpy/tests/test_compat_manifest.py::_SERVER_INPUTS``).

    This test was added after audit pass 8 caught the original shim emitting
    arcpy-style ``input_features`` / ``result`` payloads against the
    server's ``wkb`` / ``srid`` / ``layerId`` contract. Today every
    process-backed entry is a stub, so the test currently asserts the
    invariant against an empty set; the moment a future change re-promotes
    one of these entries to ``backend="process"``, this test enforces the
    contract.
    """

    # Snapshot of honua-server's BuiltInProcessCatalog inputs (process_id
    # -> accepted input names). Keep this in sync when honua-server adds /
    # renames process inputs. The list intentionally omits raster / surface
    # / generalization processes the arcpy shim does not target.
    server_inputs: dict[str, set[str]] = {
        "geometry.buffer": {"wkb", "srid", "distance", "geodesic"},
        "geometry.clip": {"targetWkb", "clipEnvelopeWkb", "srid"},
        "geometry.intersect": {"targetWkb", "intersectorWkb", "srid"},
        "geometry.union": {"wkbs", "srid"},
        "geometry.difference": {"targetWkb", "eraserWkb", "srid"},
        "geometry.dissolve": {"wkbs", "srid", "groupKeys"},
        "analytics.spatial-join": {
            "layerId", "joinLayerId", "predicate", "distance",
            "carryFields", "outStatistics",
            # Shared analytics filter parameters:
            "where", "objectIds", "geometry", "geometryType", "inSR",
            "spatialRel", "time", "timeRelation",
        },
        "data-management.copy-features": {
            "sourceLayerId", "targetLayerName", "where", "objectIds",
        },
        "data-management.delete-features": {"layerId", "where", "objectIds"},
        "data-management.calculate-field": {
            "layerId", "fieldName", "expression", "where", "objectIds",
        },
        "conversion.feature-project": {"layerId", "targetSrid"},
    }

    process_entries = [
        (name, entry) for name, entry in COMPAT.items()
        if entry.backend == "process"
    ]
    for name, entry in process_entries:
        assert entry.process_id in server_inputs, (
            f"{name}: process_id {entry.process_id!r} is not in the "
            "honua-server BuiltInProcessCatalog snapshot. Either extend "
            "the snapshot or drop the entry."
        )
        accepted = server_inputs[entry.process_id]
        emitted = set(entry.param_map.values())
        extras = emitted - accepted
        assert not extras, (
            f"{name}: param_map emits keys {sorted(extras)!r} that the "
            f"server's {entry.process_id} process does not accept. "
            "Either rename the param_map values to match the server "
            "contract or downgrade the entry to a stub until a projection "
            "adapter lands."
        )


def test_stub_hints_do_not_recommend_stubbed_sibling_shims() -> None:
    """A stub's ``replacement_hint`` must not tell the customer to call
    another ``honua_arcpy.<family>.<func>`` that is itself a stub.

    Audit pass 8 downgraded 11 process-backed entries to stubs at once.
    Several other stubs' replacement hints (``analysis.MultipleRingBuffer``
    pointed at ``honua_arcpy.analysis.Buffer``;
    ``analysis.SymmetricalDifference`` told callers to "Compose Union minus
    Intersect; both processes are supported"; ``analysis.Identity``
    referenced ``Intersect``; ``management.SelectLayerByLocation``
    referenced ``analysis.Buffer + analysis.Intersect``) silently shipped a
    workaround that immediately raises ``HonuaArcpyUnsupportedError``
    against the stubbed sibling. This invariant prevents that regression:
    a stub may describe the relationship to another stubbed shim, but it
    cannot recommend calling it.
    """

    stub_names = {name for name, entry in COMPAT.items() if entry.status == "stub"}
    for name, entry in COMPAT.items():
        if entry.status != "stub" or not entry.replacement_hint:
            continue
        hint = entry.replacement_hint
        for sibling in stub_names:
            # Only flag the fully-qualified ``honua_arcpy.<family>.<func>``
            # invocation form in the replacement_hint. Bare references like
            # "analysis.Buffer" or appearances in the ``notes`` field are
            # allowed because they may describe the relationship ("blocked
            # on the same adapter as analysis.Buffer") rather than
            # recommend a call.
            invocation = f"honua_arcpy.{sibling}"
            assert invocation not in hint, (
                f"{name}: replacement_hint recommends calling {invocation}, "
                "which is itself a stub. Point at the underlying honua_sdk / "
                "honua_admin call (or the OGC Processes client) instead, or "
                "acknowledge the shared blocker without inviting another "
                "HonuaArcpyUnsupportedError."
            )
