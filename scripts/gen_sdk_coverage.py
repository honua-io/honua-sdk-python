"""Generator + CI gate for ``compatibility/sdk-coverage.v1.json``.

Publishes this SDK's per-capability coverage snapshot against the canonical
capability key vocabulary owned by honua-io/honua-server (see
honua-server#2893 / #2892 and honua-sdk-python#182). Consumers of the
snapshot (honua-evidence's aggregate run, the capability matrix) join on
``key``.

Design, mirroring ``scripts/compatibility_gate.py``:

- ``collect_snapshot()`` is a pure function of :data:`COVERAGE` (the hand-
  curated key -> status/entrypoints/note mapping below) plus live
  introspection of the installed ``honua_sdk`` / ``honua_admin`` packages.
  It does **not** depend on which key-list source was used, so the
  committed snapshot is identical whether generated against the pinned
  fixture or the live upstream URL.
- Every entrypoint in :data:`COVERAGE` is resolved via ``importlib`` +
  ``getattr`` against the *installed* packages. If a referenced class,
  function, or method is renamed or removed, generation fails -- this is
  the real drift signal: an SDK change that invalidates a coverage claim
  fails CI until a human updates :data:`COVERAGE` in the same PR.
- The canonical key list is *consumed, never copied*: every key in
  :data:`COVERAGE` is validated against it (unknown key -> fail). Key-list
  resolution order (mirrors honua-samples' ``validate-manifests.mjs``
  ``KEY_LIST_URL`` pattern):

  1. ``HONUA_CAPABILITY_KEY_LIST_URL`` env var, if set -- fetched live.
     CI sets this to honua-server's published raw URL on every run, so
     PRs validate against current upstream truth (satisfies "unknown keys
     fail" from #182).
  2. ``compatibility/capability-keys.fixture.json`` -- a pinned,
     point-in-time offline copy, used for local/offline dev so this
     script never *requires* network access to run.

Rules from #182, enforced below:

- ``partial`` requires a non-empty ``note`` saying where coverage stops.
- Capabilities the SDK does not touch are omitted entirely -- never
  padded with a ``none`` entry.
- ``sinceVersion`` is an honest, non-invented marker: this SDK is a
  source preview with no published PyPI release, so every entry uses the
  literal :data:`SINCE_VERSION` string rather than a package version
  number nobody can actually install.

Usage::

    python scripts/gen_sdk_coverage.py                     # run the gate
    python scripts/gen_sdk_coverage.py --update-snapshot    # rewrite the snapshot
    python scripts/gen_sdk_coverage.py --refresh-key-list-fixture  # re-pin the fixture
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "compatibility" / "sdk-coverage.v1.json"
KEY_LIST_FIXTURE_PATH = ROOT / "compatibility" / "capability-keys.fixture.json"
DEFAULT_KEY_LIST_URL = (
    "https://raw.githubusercontent.com/honua-io/honua-server/trunk/docs/gis/data/capability-keys.v1.json"
)
KEY_LIST_URL_ENV_VAR = "HONUA_CAPABILITY_KEY_LIST_URL"

SCHEMA_VERSION = "sdk-coverage.v1"

# This SDK is a source preview: neither honua-sdk nor honua-admin has ever
# been published to PyPI (see AGENTS.md / README "Status: alpha"). Never
# invent a released version number here -- this literal string is the
# honest answer for every entry until a real release ships.
SINCE_VERSION = "unreleased (source preview; not yet published to PyPI)"

KEY_LIST_POLICY = (
    "Canonical capability key vocabulary is owned and published by "
    "honua-io/honua-server (docs/gis/data/capability-keys.v1.json, "
    "honua-server#2893). This SDK consumes it for validation only -- keys "
    "are never redefined or copied here beyond the entries this SDK "
    "actually implements. See scripts/gen_sdk_coverage.py for the "
    "HONUA_CAPABILITY_KEY_LIST_URL / pinned-fixture resolution order."
)


def _add_source_paths() -> None:
    for path in (ROOT / "packages" / "honua-admin", ROOT / "packages" / "honua-sdk"):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


_add_source_paths()


@dataclasses.dataclass(frozen=True)
class CoverageEntry:
    key: str
    status: str  # "covered" | "partial"
    entrypoints: tuple[str, ...]
    note: str | None = None


# ---------------------------------------------------------------------------
# Hand-curated coverage inventory.
#
# Each entry maps a canonical honua-server capability key to what this
# repository's *client* source actually implements. This is a client SDK,
# so "covered" means "the SDK has a surface that talks to that server
# capability", not that the capability is implemented server-side.
#
# Every capability NOT listed here is intentionally omitted (status "none",
# never padded) -- e.g. every ``identity.*``, ``alerts.*``, ``channels.*``,
# ``dr.*``, ``analytics.*``, ``fieldops.*``, ``printing.*``, ``staticmap.*``,
# ``ai.*``, ``routing.*``, ``caching.*``, and ``import.*`` key, because this
# SDK has no client surface for any of them (verified by source grep during
# #182 triage -- those are either server-admin-only config surfaces this
# SDK's control-plane client doesn't expose, or protocols this SDK's data
# plane never implemented).
# ---------------------------------------------------------------------------
COVERAGE: tuple[CoverageEntry, ...] = (
    CoverageEntry(
        key="serve.geoservices-root",
        status="covered",
        entrypoints=(
            "honua_sdk.AsyncHonuaClient.list_services",
            "honua_sdk.AsyncHonuaClient.list_service_summaries",
        ),
    ),
    CoverageEntry(
        key="serve.geoservices-featureserver",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.GeoServicesFeatureServerClient",
            "honua_sdk.protocols.AsyncGeoServicesFeatureServerClient",
            "honua_sdk.AsyncHonuaClient.feature_server",
        ),
    ),
    CoverageEntry(
        key="editing.featureserver-edits",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.GeoServicesFeatureServerClient.apply_edits",
            "honua_sdk.AsyncHonuaClient.apply_edits",
            "honua_sdk.AsyncHonuaClient.apply_edits_result",
        ),
    ),
    CoverageEntry(
        key="serve.geoservices-mapserver",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.GeoServicesMapServerClient",
            "honua_sdk.protocols.AsyncGeoServicesMapServerClient",
            "honua_sdk.AsyncHonuaClient.map_server",
            "honua_sdk.AsyncHonuaClient.export_map",
        ),
    ),
    CoverageEntry(
        key="serve.geoservices-imageserver",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.GeoServicesImageServerClient",
            "honua_sdk.protocols.AsyncGeoServicesImageServerClient",
            "honua_sdk.AsyncHonuaClient.image_server",
        ),
    ),
    CoverageEntry(
        key="serve.geoservices-geometry-service",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.GeoServicesGeometryServerClient",
            "honua_sdk.protocols.AsyncGeoServicesGeometryServerClient",
            "honua_sdk.AsyncHonuaClient.geometry_server",
        ),
    ),
    CoverageEntry(
        key="raster.temporal-mosaic",
        status="partial",
        entrypoints=(
            "honua_sdk.protocols.GeoServicesImageServerClient.compute_histograms",
            "honua_sdk.protocols.GeoServicesImageServerClient.compute_statistics_histograms",
            "honua_sdk.protocols.GeoServicesImageServerClient.get_samples",
        ),
        note=(
            "mosaic_rule + a single ISO-8601 time instant select a raster "
            "temporal mosaic on the ImageServer histogram/statistics/sample "
            "analysis operations only. export_image, tile, identify, and "
            "query do not accept a typed time/mosaic_rule parameter (only "
            "generic extra_params passthrough), so temporal mosaic selection "
            "does not extend to raster rendering/export."
        ),
    ),
    CoverageEntry(
        key="raster.multidim-coverage",
        status="partial",
        entrypoints=("honua_sdk.protocols.GeoServicesImageServerClient.multidimensional_info",),
        note=(
            "Read-only: the client can query dimension/variable metadata "
            "for an already-registered multidimensional ImageServer via "
            "multidimensionalInfo. There is no client surface to register "
            "or configure a NetCDF4/HDF5/Zarr multidimensional coverage -- "
            "that is server-admin configuration this SDK's control-plane "
            "client does not expose."
        ),
    ),
    CoverageEntry(
        key="serve.ogc-api-features",
        status="covered",
        entrypoints=(
            "honua_sdk.ogc.HonuaOgcFeatures",
            "honua_sdk.ogc.HonuaOgcFeatureCollection",
            "honua_sdk.ogc.AsyncHonuaOgcFeatures",
            "honua_sdk.ogc.AsyncHonuaOgcFeatureCollection",
        ),
    ),
    CoverageEntry(
        key="serve.ogc-api-maps",
        status="covered",
        entrypoints=("honua_sdk.protocols.OgcMapsClient", "honua_sdk.protocols.AsyncOgcMapsClient"),
    ),
    CoverageEntry(
        key="serve.ogc-api-tiles",
        status="covered",
        entrypoints=("honua_sdk.protocols.OgcTilesClient", "honua_sdk.protocols.AsyncOgcTilesClient"),
    ),
    CoverageEntry(
        key="serve.ogc-api-coverages",
        status="covered",
        entrypoints=("honua_sdk.protocols.OgcCoveragesClient", "honua_sdk.protocols.AsyncOgcCoveragesClient"),
    ),
    CoverageEntry(
        key="serve.ogc-api-records",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.OgcRecordsClient",
            "honua_sdk.protocols.OgcRecordsCollectionClient",
            "honua_sdk.protocols.AsyncOgcRecordsClient",
            "honua_sdk.protocols.AsyncOgcRecordsCollectionClient",
        ),
    ),
    CoverageEntry(
        key="process.ogc-api-processes",
        status="covered",
        entrypoints=("honua_sdk.geoprocessing.HonuaGeoprocessing", "honua_sdk.geoprocessing.AsyncHonuaGeoprocessing"),
    ),
    CoverageEntry(
        key="serve.stac",
        status="covered",
        entrypoints=("honua_sdk.protocols.StacClient", "honua_sdk.protocols.AsyncStacClient"),
    ),
    CoverageEntry(
        key="serve.wfs",
        status="covered",
        entrypoints=("honua_sdk.protocols.WfsClient", "honua_sdk.protocols.AsyncWfsClient"),
    ),
    CoverageEntry(
        key="serve.wms",
        status="covered",
        entrypoints=("honua_sdk.protocols.WmsClient", "honua_sdk.protocols.AsyncWmsClient"),
    ),
    CoverageEntry(
        key="serve.wmts",
        status="covered",
        entrypoints=("honua_sdk.protocols.WmtsClient", "honua_sdk.protocols.AsyncWmtsClient"),
    ),
    CoverageEntry(
        key="serve.odata",
        status="partial",
        entrypoints=("honua_sdk.protocols.ODataClient", "honua_sdk.protocols.AsyncODataClient"),
        note=(
            "Read/query only (service_document, metadata, layers, features, "
            "and pagination helpers). No create/update/delete entity-set "
            "operations are implemented, so the write half of 'query and "
            "edit features through OData v4' is not covered."
        ),
    ),
    CoverageEntry(
        key="serve.3d-tiles-scene",
        status="covered",
        entrypoints=(
            "honua_sdk.protocols.SceneClient",
            "honua_sdk.protocols.AsyncSceneClient",
            "honua_sdk.protocols.enumerate_tileset_contents",
            "honua_sdk.protocols.parse_scene_package_manifest",
        ),
    ),
    CoverageEntry(
        key="serve.i3s-scene",
        status="partial",
        entrypoints=("honua_sdk.protocols.SceneClient.resolve_scene", "honua_sdk.protocols.SceneClient.fetch_tile"),
        note=(
            "I3S-tagged scene endpoints resolve and fetch as opaque bytes "
            "through the same generic scene-endpoint resolution used for 3D "
            "Tiles, but there is no I3S-specific scene-layer-package (.slpk) "
            "node/resource-tree parsing -- only the 3D Tiles tileset.json "
            "walker (enumerate_tileset_contents) is implemented."
        ),
    ),
    CoverageEntry(
        key="scene.catalog",
        status="covered",
        entrypoints=("honua_sdk.protocols.SceneClient.list_scenes", "honua_sdk.protocols.SceneClient.get_scene"),
    ),
    CoverageEntry(
        key="serve.elevation",
        status="covered",
        entrypoints=("honua_sdk.protocols.ElevationClient", "honua_sdk.protocols.AsyncElevationClient"),
    ),
    CoverageEntry(
        key="geocoding.forward",
        status="covered",
        entrypoints=(
            "honua_sdk.geocoding.HonuaGeocodingClient.forward_geocode",
            "honua_sdk.async_geocoding.AsyncHonuaGeocodingClient.forward_geocode",
        ),
    ),
    CoverageEntry(
        key="geocoding.reverse",
        status="covered",
        entrypoints=(
            "honua_sdk.geocoding.HonuaGeocodingClient.reverse_geocode",
            "honua_sdk.async_geocoding.AsyncHonuaGeocodingClient.reverse_geocode",
        ),
    ),
    CoverageEntry(
        key="discovery.capability-manifest",
        status="covered",
        entrypoints=(
            "honua_sdk.AsyncHonuaClient.capabilities",
            "honua_admin.AsyncHonuaAdminClient.get_capabilities",
            "honua_admin.AsyncHonuaAdminClient.get_capability_flags",
            "honua_admin.AsyncHonuaAdminClient.check_compatibility",
        ),
    ),
    CoverageEntry(
        key="admin.control-plane",
        status="covered",
        entrypoints=("honua_admin.AsyncHonuaAdminClient", "honua_admin.HonuaAdminClient"),
    ),
    CoverageEntry(
        key="styling.ogc-api-styles",
        status="covered",
        entrypoints=(
            "honua_admin.AsyncHonuaAdminClient.list_styles",
            "honua_admin.AsyncHonuaAdminClient.get_stylesheet",
            "honua_admin.AsyncHonuaAdminClient.get_style_metadata",
            "honua_admin.AsyncHonuaAdminClient.update_style",
        ),
    ),
    CoverageEntry(
        key="ops.health",
        status="covered",
        entrypoints=("honua_sdk.AsyncHonuaClient.readiness",),
    ),
)


def _resolve_entrypoint(dotted_path: str) -> tuple[bool, str | None]:
    """Resolve ``dotted_path`` against the installed packages.

    Tries the longest importable module prefix, then walks any remaining
    dotted attributes (class -> method) with ``getattr``. Returns
    ``(True, None)`` on success or ``(False, error_message)`` on failure --
    the real drift check: a renamed/removed symbol fails this.
    """
    import importlib

    parts = dotted_path.split(".")
    module = None
    split_index = 0
    for index in range(len(parts), 0, -1):
        candidate = ".".join(parts[:index])
        try:
            module = importlib.import_module(candidate)
        except ImportError:
            continue
        split_index = index
        break
    if module is None:
        return False, f"no importable module prefix for {dotted_path!r}"

    obj: Any = module
    for attr in parts[split_index:]:
        try:
            obj = getattr(obj, attr)
        except AttributeError:
            return False, f"{dotted_path!r}: no attribute {attr!r} on {obj!r}"
    return True, None


def check_entrypoints_resolve(entries: Sequence[CoverageEntry] = COVERAGE) -> list[str]:
    failures = []
    for entry in entries:
        if not entry.entrypoints:
            failures.append(f"{entry.key}: must list at least one entrypoint.")
            continue
        for dotted_path in entry.entrypoints:
            ok, error = _resolve_entrypoint(dotted_path)
            if not ok:
                failures.append(f"{entry.key}: entrypoint drift -- {error}.")
    return failures


def check_partial_notes(entries: Sequence[CoverageEntry] = COVERAGE) -> list[str]:
    failures = []
    for entry in entries:
        if entry.status not in {"covered", "partial"}:
            failures.append(f"{entry.key}: status must be 'covered' or 'partial', got {entry.status!r}.")
        if entry.status == "partial" and not (entry.note and entry.note.strip()):
            failures.append(f"{entry.key}: status 'partial' requires a non-empty note saying where coverage stops.")
        if entry.status == "covered" and entry.note:
            failures.append(f"{entry.key}: status 'covered' should not carry a partial-style note ({entry.note!r}).")
    return failures


def check_keys_are_unique(entries: Sequence[CoverageEntry] = COVERAGE) -> list[str]:
    seen: dict[str, int] = {}
    failures = []
    for entry in entries:
        seen[entry.key] = seen.get(entry.key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            failures.append(f"{key}: listed {count} times in COVERAGE; each capability key must appear once.")
    return failures


def _extract_canonical_keys(payload: Any, *, source: str) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("capabilities"), list):
        raise ValueError(f"{source}: expected an object with a 'capabilities' array.")
    keys = set()
    for item in payload["capabilities"]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"]:
            raise ValueError(f"{source}: every capabilities[] entry must be an object with a non-empty 'key'.")
        keys.add(item["key"])
    if not keys:
        raise ValueError(f"{source}: capabilities[] must not be empty.")
    return keys


def load_key_list_fixture(path: Path = KEY_LIST_FIXTURE_PATH) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _extract_canonical_keys(payload, source=str(path))


def fetch_key_list(url: str, *, timeout: float = 15.0) -> set[str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 -- fixed https URL, not user input
        payload = json.loads(response.read().decode("utf-8"))
    return _extract_canonical_keys(payload, source=url)


def resolve_canonical_keys(url_override: str | None = None) -> tuple[set[str], str]:
    """Resolve the canonical key set, returning ``(keys, source_label)``.

    Resolution order: an explicit ``url_override`` argument, then the
    ``HONUA_CAPABILITY_KEY_LIST_URL`` env var, then the pinned offline
    fixture. Network is only ever touched when a URL is explicitly
    requested, so this script (and its tests) run offline by default.
    """
    import os

    url = url_override or os.environ.get(KEY_LIST_URL_ENV_VAR)
    if url:
        return fetch_key_list(url), url
    return load_key_list_fixture(), f"{KEY_LIST_FIXTURE_PATH.relative_to(ROOT)} (pinned fixture)"


def check_keys_are_canonical(canonical_keys: set[str], entries: Sequence[CoverageEntry] = COVERAGE) -> list[str]:
    failures = []
    for entry in entries:
        if entry.key not in canonical_keys:
            failures.append(
                f"{entry.key}: not present in the canonical capability key list "
                "-- fix the key, or this capability was renamed/removed upstream."
            )
    return failures


def collect_snapshot() -> dict[str, Any]:
    """Build the sdk-coverage.v1.json document.

    Deliberately independent of which key-list source was used to validate
    :data:`COVERAGE`, so the committed snapshot is identical whether
    generated against the pinned fixture or the live upstream URL.
    """
    capabilities = [
        {
            "key": entry.key,
            "status": entry.status,
            "sinceVersion": SINCE_VERSION,
            "entrypoints": list(entry.entrypoints),
            **({"note": entry.note} if entry.note else {}),
        }
        for entry in sorted(COVERAGE, key=lambda entry: entry.key)
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "package": "honua-sdk-python (packages/honua-sdk + packages/honua-admin)",
        "generator": "scripts/gen_sdk_coverage.py",
        "keyListPolicy": KEY_LIST_POLICY,
        "capabilities": capabilities,
    }


def _json_dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=False) + "\n"


def update_snapshot(path: Path = SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(collect_snapshot()), encoding="utf-8")


def check_snapshot_current(path: Path = SNAPSHOT_PATH) -> list[str]:
    actual = collect_snapshot()
    try:
        expected = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"SDK coverage snapshot is missing: {path}"]

    if actual == expected:
        return []

    expected_text = _json_dumps(expected).splitlines()
    actual_text = _json_dumps(actual).splitlines()
    diff = "\n".join(
        difflib.unified_diff(expected_text, actual_text, fromfile=str(path), tofile="current coverage", lineterm="")
    )
    return [
        "SDK coverage snapshot drift detected. Run "
        "`python scripts/gen_sdk_coverage.py --update-snapshot` after "
        "reviewing any intentional coverage change.\n"
        f"{diff}"
    ]


def run_gate(url_override: str | None = None) -> list[str]:
    failures = []
    failures.extend(check_keys_are_unique())
    failures.extend(check_partial_notes())
    failures.extend(check_entrypoints_resolve())
    canonical_keys, source_label = resolve_canonical_keys(url_override)
    failures.extend(check_keys_are_canonical(canonical_keys))
    failures.extend(check_snapshot_current())
    if not failures:
        print(f"Validated {len(COVERAGE)} capability keys against {source_label} ({len(canonical_keys)} known keys).")
    return failures


def refresh_key_list_fixture(url: str = DEFAULT_KEY_LIST_URL, path: Path = KEY_LIST_FIXTURE_PATH) -> None:
    with urllib.request.urlopen(url, timeout=15.0) as response:  # noqa: S310 -- fixed https URL, not user input
        payload = json.loads(response.read().decode("utf-8"))
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        raise ValueError(f"{url}: expected an object with a 'capabilities' array.")

    fixture = {
        "_comment": (
            "PINNED, POINT-IN-TIME FIXTURE. This is the offline fallback key "
            "list used when HONUA_CAPABILITY_KEY_LIST_URL is unset (local "
            "dev / no network). It is a trimmed copy "
            "(key/category/edition/displayName only -- descriptions "
            "dropped) of honua-io/honua-server's published "
            "capability-keys.v1.json. honua-sdk-python does not own this "
            "vocabulary -- consume, never redefine it. CI always validates "
            "against the live URL (see .github/workflows/ci.yml); this "
            "fixture only backstops local/offline runs of "
            "scripts/gen_sdk_coverage.py. Refresh with "
            "`python scripts/gen_sdk_coverage.py --refresh-key-list-fixture` "
            "whenever honua-server's vocabulary changes."
        ),
        "source": url,
        "schemaVersion": payload.get("schemaVersion"),
        "capabilities": [
            {
                "key": item.get("key"),
                "category": item.get("category"),
                "edition": item.get("edition"),
                "displayName": item.get("displayName"),
            }
            for item in capabilities
            if isinstance(item, dict)
        ],
    }
    path.write_text(json.dumps(fixture, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-snapshot",
        action="store_true",
        help="Rewrite compatibility/sdk-coverage.v1.json from the current COVERAGE inventory.",
    )
    parser.add_argument(
        "--refresh-key-list-fixture",
        action="store_true",
        help="Re-fetch the live key list and rewrite the pinned offline fixture.",
    )
    parser.add_argument(
        "--key-list-url",
        default=None,
        help=f"Override the canonical key list URL for this run (defaults to ${KEY_LIST_URL_ENV_VAR} or the fixture).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.refresh_key_list_fixture:
        refresh_key_list_fixture()
        print(f"Refreshed {KEY_LIST_FIXTURE_PATH.relative_to(ROOT)}")
        return 0
    if args.update_snapshot:
        update_snapshot()
        print(f"Updated {SNAPSHOT_PATH.relative_to(ROOT)}")
        return 0

    failures = run_gate(args.key_list_url)
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("SDK coverage gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
