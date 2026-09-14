"""Response-value emitter for eval scripts.

The golden harness verifies two independent things:

* The **request** honua_gp projects onto the server (process id + typed
  inputs). That fingerprint is captured from the audit JSONL stream and is
  deterministic across the stub transport and a live server, so it is diffed
  in both modes (see ``run_eval.py``).
* The **response** honua_gp parses back from the server. The stub transport
  only returns a canned ``href``, so a response value diff is meaningful
  *only* against a live, seeded honua-server. Scripts that read a computed
  result (buffered geometry, a row count, cursor rows) call
  :func:`emit_response` here to record what ``honua_gp`` actually parsed;
  ``run_eval.py`` diffs that sidecar against the golden ``response`` block
  when running in live mode.

The emitter is a no-op unless ``HONUA_GP_EVAL_RESULT_DIR`` is set (the harness
sets it), so the scripts stay runnable by hand and in stub CI without writing
stray files.

This is NOT an ArcGIS Pro parity check: the response fingerprint is pinned to
the honua-server client-compat seed, not to a licensed arcpy baseline. It
verifies that ``honua_gp`` round-trips correctly against the real Honua
server; arcpy-level output parity remains license-gated and out of scope here.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping


_RESULT_DIR_ENV = "HONUA_GP_EVAL_RESULT_DIR"


def _result_dir() -> Path | None:
    raw = os.environ.get(_RESULT_DIR_ENV)
    if not raw:
        return None
    return Path(raw)


def emit_response(name: str, response: Mapping[str, Any]) -> None:
    """Write ``{HONUA_GP_EVAL_RESULT_DIR}/{name}.json`` when capture is enabled.

    ``response`` is a normalized, seed-stable fingerprint (geometry type,
    feature/row counts, output keys) -- never the raw floating-point geometry,
    which would be brittle across server versions.
    """

    target_dir = _result_dir()
    if target_dir is None:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{name}.json").write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _decode_feature_layer_href(href: str) -> Mapping[str, Any] | None:
    """Decode a ``data:application/geo+json;base64,...`` FeatureLayer href."""

    marker = "base64,"
    if not isinstance(href, str) or marker not in href:
        return None
    payload = href.split(marker, 1)[1]
    try:
        decoded = base64.b64decode(payload)
        parsed = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def feature_layer_fingerprint(result: Any) -> dict[str, Any]:
    """Normalize a process ``Result`` into a seed-stable response fingerprint.

    Extracts the sorted output keys, and -- when the primary output is a
    GeoJSON FeatureLayer -- the geometry type and feature count that the
    server actually computed and ``honua_gp`` parsed back. Absent / unreadable
    geometry degrades gracefully to ``None`` so the harness still diffs the
    structural keys.
    """

    outputs = getattr(result, "outputs", None)
    if not isinstance(outputs, Mapping):
        return {"output_keys": [], "geometry_type": None, "feature_count": None}

    fingerprint: dict[str, Any] = {
        "output_keys": sorted(str(key) for key in outputs),
        "geometry_type": None,
        "feature_count": None,
    }

    # The layer-aware analysis/management processes return a single
    # ``outputFeatureLayer`` (or similarly named) FeatureLayer artifact, either
    # as a ``href`` data URI (by-reference transmission) or an inline ``value``
    # GeoJSON document (OGC API Processes "value" transmission mode -- what
    # honua-server's layer-aware executors actually return).
    for value in outputs.values():
        if not isinstance(value, Mapping):
            continue
        href = value.get("href")
        geojson = _decode_feature_layer_href(href) if isinstance(href, str) else None
        if geojson is None:
            inline = value.get("value")
            if isinstance(inline, Mapping):
                geojson = inline
        if geojson is None:
            continue
        features = geojson.get("features")
        if isinstance(features, list):
            fingerprint["feature_count"] = len(features)
            if features and isinstance(features[0], Mapping):
                geometry = features[0].get("geometry")
                if isinstance(geometry, Mapping):
                    fingerprint["geometry_type"] = geometry.get("type")
        break

    return fingerprint


def schema_fingerprint(fields: Any, *, shape_type: Any = None, oid_field: Any = None, srid: Any = None) -> dict[str, Any]:
    """Normalize a Describe/ListFields result into a seed-stable fingerprint.

    ``fields`` is a sequence of ``FieldDescribe`` (or anything exposing
    ``.name`` / ``.type``). The seeded ``segments`` / ``roads`` schemas are
    fixed by ``tests/seed/client-compat-v1.sql`` and do not change between
    live runs, so field names + types are a stable oracle -- unlike geometry
    coordinates or generated object ids.
    """

    return {
        "field_count": len(fields),
        "field_names": [str(getattr(f, "name", "")) for f in fields],
        "field_types": {str(getattr(f, "name", "")): getattr(f, "type", None) for f in fields},
        "shape_type": shape_type,
        "oid_field": oid_field,
        "srid": srid,
    }


def apply_edits_fingerprint(result: Any) -> dict[str, Any]:
    """Normalize an ``InsertCursor``/``UpdateCursor`` ``flush()`` return value.

    ``flush()`` returns different shapes depending on transport: the stub's
    ``_StubApplyEditsResult.to_dict()`` (a plain dict with ``adds`` /
    ``updates`` / ``deletes`` lists) versus the live SDK's
    ``honua_sdk.models.ApplyEditsResult`` dataclass (``add_results`` /
    ``update_results`` / ``delete_results`` sequences of typed
    ``EditOperationResult``, each carrying a server-assigned ``object_id``).
    Only success *counts* are captured, never object ids -- those are not
    stable oracles across repeated seed runs. ``result`` is ``None`` when
    ``flush()`` had nothing buffered (e.g. an UpdateCursor predicate matched
    zero rows against the current seed state) -- that is itself a valid,
    deterministic oracle (all counts zero, vacuously succeeded), not an
    absence of one.
    """

    if result is None:
        return {"add_count": 0, "update_count": 0, "delete_count": 0, "all_succeeded": True}
    if isinstance(result, Mapping):
        adds, updates, deletes = result.get("adds", []), result.get("updates", []), result.get("deletes", [])
        return {
            "add_count": len(adds),
            "update_count": len(updates),
            "delete_count": len(deletes),
            "all_succeeded": True,
        }
    add_results = getattr(result, "add_results", ())
    update_results = getattr(result, "update_results", ())
    delete_results = getattr(result, "delete_results", ())
    all_succeeded = getattr(result, "all_succeeded", None)
    if all_succeeded is None:
        combined = [*add_results, *update_results, *delete_results]
        all_succeeded = bool(combined) and all(getattr(r, "success", False) for r in combined)
    return {
        "add_count": len(add_results),
        "update_count": len(update_results),
        "delete_count": len(delete_results),
        "all_succeeded": bool(all_succeeded),
    }


def edited_object_ids(result: Any, operation: str) -> set[str]:
    """Return the server-assigned object ids of the successful ``operation`` edits.

    ``operation`` is ``"add"``, ``"update"`` or ``"delete"``. The ids are
    never frozen into a golden (they differ across seeds); scripts use them
    to read back exactly the rows their own edit touched, so the response
    oracle records what the dataset holds afterwards rather than what the
    script submitted. Ids are compared as strings because
    ``QueryFeature.id`` may be a ``str`` or an ``int``. The stub's plain-dict
    result carries no server ids, so it yields an empty set.
    """

    if result is None or isinstance(result, Mapping):
        return set()
    results = getattr(result, f"{operation}_results", ())
    return {
        str(entry.object_id)
        for entry in results
        if getattr(entry, "success", False) and getattr(entry, "object_id", None) is not None
    }


__all__ = [
    "apply_edits_fingerprint",
    "edited_object_ids",
    "emit_response",
    "feature_layer_fingerprint",
    "schema_fingerprint",
]
