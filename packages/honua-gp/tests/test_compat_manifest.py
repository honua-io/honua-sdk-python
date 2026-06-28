"""Compatibility manifest invariants."""

from __future__ import annotations

from pathlib import Path

import honua_gp
from honua_gp._compat import COMPAT

_README_PATH = Path(honua_gp.__file__).resolve().parent.parent / "README.md"


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
        "HonuaGpUnsupportedError",
        "HonuaGpConfigurationError",
        "Describe",
        "DescribeResult",
        "FieldDescribe",
        "Selection",
        "GetCount",
        "COMPAT",
    }
    missing = expected - set(dir(honua_gp))
    assert not missing, f"Missing top-level exports: {sorted(missing)}"


def test_legacy_suffix_aliases_are_exported() -> None:
    # Real arcpy exposes both ``arcpy.analysis.Buffer`` and
    # ``arcpy.Buffer_analysis``. The shim mirrors the suffix form for the
    # top-of-corpus entries so unmodified scripts keep importing -- the
    # underlying shim may currently raise ``HonuaGpUnsupportedError``
    # for process-backed entries until the projection adapter lands, but
    # the suffix-aliased reference must still resolve to the same callable.
    assert honua_gp.Buffer_analysis is honua_gp.analysis.Buffer
    assert honua_gp.Clip_analysis is honua_gp.analysis.Clip
    assert honua_gp.CalculateField_management is honua_gp.management.CalculateField
    assert honua_gp.MakeFeatureLayer_management is honua_gp.management.MakeFeatureLayer
    assert honua_gp.GetCount_management is honua_gp.management.GetCount


def test_process_backed_entries_match_honua_server_catalog() -> None:
    """Contract guard: every ``backend="process"`` entry's ``param_map``
    values must form a subset of the inputs the corresponding honua-server
    process accepts. The reference is a hand-maintained snapshot of
    ``Honua.Server.Features.Geoprocessing.BuiltInProcessCatalog`` (see
    ``packages/honua-gp/tests/test_compat_manifest.py::_SERVER_INPUTS``).

    This test was added after audit pass 8 caught the original shim emitting
    arcpy-style ``input_features`` / ``result`` payloads against the
    server's ``wkb`` / ``srid`` / ``layerId`` contract. The layer-aware
    projection adapter re-promoted Buffer / SpatialJoin / Dissolve /
    CalculateField / Copy / Project to ``backend="process"``; this test now
    enforces that each one's ``param_map`` values stay a subset of the
    matching honua-server process inputs.
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
        "analytics.buffer-aggregate": {
            "layerId", "distance", "unit", "dissolve", "groupByFields",
            "outStatistics",
            # Shared analytics filter parameters:
            "where", "objectIds", "geometry", "geometryType", "inSR",
            "spatialRel", "time", "timeRelation",
        },
        "generalization.dissolve": {
            "layerId", "groupByFields", "dissolve", "outStatistics",
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


def test_compat_repo_doc_points_at_a_committed_matrix_copy() -> None:
    """``HonuaGpUnsupportedError.compat_anchor`` embeds
    ``COMPAT_REPO_DOC`` so users can paste the anchor into the repo browser.

    Before the fix, ``COMPAT_REPO_DOC`` was ``docs/compatibility-matrix.md``
    -- a path that does not exist in this repo. The committed matrix copies
    are ``docs/honua-gp/compatibility-matrix.md`` and
    ``packages/honua-gp/docs/compatibility-matrix.md``. This test pins
    the constant to a path that actually resolves so the user-facing error
    URL is not a 404.
    """

    from pathlib import Path

    from honua_gp._compat import COMPAT_REPO_DOC, anchor_for

    # The constant is repo-relative; resolve it against the workspace root
    # (three parents up from this test file: tests/ -> honua-gp/ ->
    # packages/ -> workspace).
    workspace_root = Path(__file__).resolve().parents[3]
    matrix_path = workspace_root / COMPAT_REPO_DOC
    assert matrix_path.is_file(), (
        f"COMPAT_REPO_DOC {COMPAT_REPO_DOC!r} must point at a committed "
        f"matrix file. Resolved to {matrix_path} which does not exist."
    )

    # And the anchor builder must produce URLs that start from the same path.
    anchor = anchor_for("analysis.Buffer")
    assert anchor.startswith(COMPAT_REPO_DOC + "#"), (
        f"anchor_for(...) returned {anchor!r}; expected the URL to start "
        f"with {COMPAT_REPO_DOC!r}."
    )


def test_stub_hints_do_not_recommend_stubbed_sibling_shims() -> None:
    """A stub's ``replacement_hint`` must not tell the customer to call
    another ``honua_gp.<family>.<func>`` that is itself a stub.

    Audit pass 8 downgraded 11 process-backed entries to stubs at once.
    Several other stubs' replacement hints (``analysis.MultipleRingBuffer``
    pointed at ``honua_gp.analysis.Buffer``;
    ``analysis.SymmetricalDifference`` told callers to "Compose Union minus
    Intersect; both processes are supported"; ``analysis.Identity``
    referenced ``Intersect``; ``management.SelectLayerByLocation``
    referenced ``analysis.Buffer + analysis.Intersect``) silently shipped a
    workaround that immediately raises ``HonuaGpUnsupportedError``
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
            # Only flag the fully-qualified ``honua_gp.<family>.<func>``
            # invocation form in the replacement_hint. Bare references like
            # "analysis.Buffer" or appearances in the ``notes`` field are
            # allowed because they may describe the relationship ("blocked
            # on the same adapter as analysis.Buffer") rather than
            # recommend a call.
            invocation = f"honua_gp.{sibling}"
            assert invocation not in hint, (
                f"{name}: replacement_hint recommends calling {invocation}, "
                "which is itself a stub. Point at the underlying honua_sdk / "
                "honua_admin call (or the OGC Processes client) instead, or "
                "acknowledge the shared blocker without inviting another "
                "HonuaGpUnsupportedError."
            )


def test_readme_coverage_counts_match_manifest() -> None:
    """The README Status section quotes supported/partial/stub counts. Pin them
    to the COMPAT manifest so the doc cannot drift back to a stale (and badly
    understated) claim the way audit pass 8 left it."""
    supported = sum(1 for e in COMPAT.values() if e.status == "supported")
    partial = sum(1 for e in COMPAT.values() if e.status == "partial")
    stubs = sum(1 for e in COMPAT.values() if e.status == "stub")
    supported_or_partial = supported + partial

    readme = _README_PATH.read_text(encoding="utf-8")
    assert f"{supported} supported entries and {partial} partial entries" in readme, (
        "README Status coverage line is stale; regenerate from the COMPAT manifest "
        f"({supported} supported, {partial} partial, {stubs} stubs)."
    )
    assert f"({supported_or_partial} supported/partial) + {stubs} stubs" in readme


def test_readme_only_lists_true_stubs_as_raising() -> None:
    """The README must not claim a working tool raises HonuaGpUnsupportedError.
    Every process op named as still raising must actually be a stub, and the
    re-promoted tools must NOT be named in that raising list."""
    readme = _README_PATH.read_text(encoding="utf-8")
    promoted = [
        "analysis.Buffer",
        "analysis.SpatialJoin",
        "management.CalculateField",
        "management.Dissolve",
        "management.Copy",
        "management.Project",
    ]
    for name in promoted:
        assert COMPAT[name].is_supported, f"{name} should be supported/partial in COMPAT"
        # A re-promoted tool's bare function name must not be presented in the
        # README's "still raise HonuaGpUnsupportedError" sentence.
        func = name.split(".", 1)[1]
        assert f"``{func}`` / ``Clip``" not in readme, (
            f"README still lists {name} among the ops that raise"
        )
    # The raising list in the Quickstart enumerates the genuine process stubs.
    raising_stubs = (
        "analysis.Clip",
        "analysis.Intersect",
        "analysis.Union",
        "analysis.Erase",
        "management.Delete",
    )
    for name in raising_stubs:
        assert COMPAT[name].status == "stub", f"{name} should be a stub in COMPAT"
