"""Tests for the SDK capability coverage snapshot gate (honua-sdk-python#182)."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "scripts" / "gen_sdk_coverage.py"
SPEC = importlib.util.spec_from_file_location("gen_sdk_coverage", GATE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
gen_sdk_coverage = importlib.util.module_from_spec(SPEC)
# Register in sys.modules before exec: gen_sdk_coverage.py defines a frozen
# dataclass, and dataclasses' type-resolution machinery looks the defining
# module up via sys.modules[cls.__module__] -- without this it raises
# AttributeError on a None module during class creation.
sys.modules[SPEC.name] = gen_sdk_coverage
SPEC.loader.exec_module(gen_sdk_coverage)


def test_snapshot_is_current() -> None:
    assert gen_sdk_coverage.check_snapshot_current(gen_sdk_coverage.SNAPSHOT_PATH) == []


def test_snapshot_detects_drift(tmp_path: Path) -> None:
    snapshot = gen_sdk_coverage.collect_snapshot()
    snapshot["capabilities"].pop()

    snapshot_path = tmp_path / "sdk-coverage.v1.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    failures = gen_sdk_coverage.check_snapshot_current(snapshot_path)

    assert any("SDK coverage snapshot drift detected" in failure for failure in failures)


def test_snapshot_missing_file_reports_failure(tmp_path: Path) -> None:
    missing_path = tmp_path / "does-not-exist.json"

    failures = gen_sdk_coverage.check_snapshot_current(missing_path)

    assert any("is missing" in failure for failure in failures)


def test_entrypoints_all_resolve() -> None:
    assert gen_sdk_coverage.check_entrypoints_resolve() == []


def test_entrypoints_resolve_detects_renamed_class() -> None:
    entries = (
        dataclasses.replace(
            gen_sdk_coverage.COVERAGE[0],
            entrypoints=("honua_sdk.protocols.ThisClassDoesNotExist",),
        ),
    )

    failures = gen_sdk_coverage.check_entrypoints_resolve(entries)

    assert any("entrypoint drift" in failure for failure in failures)
    assert any("ThisClassDoesNotExist" in failure for failure in failures)


def test_entrypoints_resolve_detects_renamed_method() -> None:
    entries = (
        dataclasses.replace(
            gen_sdk_coverage.COVERAGE[0],
            entrypoints=("honua_sdk.AsyncHonuaClient.this_method_does_not_exist",),
        ),
    )

    failures = gen_sdk_coverage.check_entrypoints_resolve(entries)

    assert any("entrypoint drift" in failure for failure in failures)


def test_entry_requires_at_least_one_entrypoint() -> None:
    entries = (dataclasses.replace(gen_sdk_coverage.COVERAGE[0], entrypoints=()),)

    failures = gen_sdk_coverage.check_entrypoints_resolve(entries)

    assert any("must list at least one entrypoint" in failure for failure in failures)


def test_partial_status_requires_a_note() -> None:
    entries = (dataclasses.replace(gen_sdk_coverage.COVERAGE[0], status="partial", note=None),)

    failures = gen_sdk_coverage.check_partial_notes(entries)

    assert any("requires a non-empty note" in failure for failure in failures)


def test_partial_status_rejects_blank_note() -> None:
    entries = (dataclasses.replace(gen_sdk_coverage.COVERAGE[0], status="partial", note="   "),)

    failures = gen_sdk_coverage.check_partial_notes(entries)

    assert any("requires a non-empty note" in failure for failure in failures)


def test_covered_status_rejects_a_partial_style_note() -> None:
    entries = (dataclasses.replace(gen_sdk_coverage.COVERAGE[0], status="covered", note="stops here"),)

    failures = gen_sdk_coverage.check_partial_notes(entries)

    assert any("should not carry a partial-style note" in failure for failure in failures)


def test_unknown_status_is_rejected() -> None:
    entries = (dataclasses.replace(gen_sdk_coverage.COVERAGE[0], status="none"),)

    failures = gen_sdk_coverage.check_partial_notes(entries)

    assert any("status must be 'covered' or 'partial'" in failure for failure in failures)


def test_all_committed_entries_pass_the_note_rule() -> None:
    assert gen_sdk_coverage.check_partial_notes() == []


def test_duplicate_keys_are_rejected() -> None:
    entries = (*gen_sdk_coverage.COVERAGE, gen_sdk_coverage.COVERAGE[0])

    failures = gen_sdk_coverage.check_keys_are_unique(entries)

    assert any("listed 2 times" in failure for failure in failures)


def test_committed_keys_are_unique() -> None:
    assert gen_sdk_coverage.check_keys_are_unique() == []


def test_key_list_fixture_loads_and_covers_every_committed_key() -> None:
    canonical_keys = gen_sdk_coverage.load_key_list_fixture()

    assert len(canonical_keys) > 0
    assert gen_sdk_coverage.check_keys_are_canonical(canonical_keys) == []


def test_unknown_key_is_rejected_against_the_fixture() -> None:
    canonical_keys = gen_sdk_coverage.load_key_list_fixture()
    entries = (dataclasses.replace(gen_sdk_coverage.COVERAGE[0], key="not.a-real-key"),)

    failures = gen_sdk_coverage.check_keys_are_canonical(canonical_keys, entries)

    assert any("not present in the canonical capability key list" in failure for failure in failures)


def test_resolve_canonical_keys_defaults_to_the_pinned_fixture(monkeypatch) -> None:
    monkeypatch.delenv(gen_sdk_coverage.KEY_LIST_URL_ENV_VAR, raising=False)

    keys, source_label = gen_sdk_coverage.resolve_canonical_keys()

    assert "pinned fixture" in source_label
    assert keys == gen_sdk_coverage.load_key_list_fixture()


def test_resolve_canonical_keys_prefers_explicit_url_override(monkeypatch) -> None:
    monkeypatch.setenv(gen_sdk_coverage.KEY_LIST_URL_ENV_VAR, "https://example.invalid/should-not-be-used.json")
    calls = []

    def fake_fetch(url: str, *, timeout: float = 15.0):
        calls.append(url)
        return {"fake.key"}

    monkeypatch.setattr(gen_sdk_coverage, "fetch_key_list", fake_fetch)

    keys, source_label = gen_sdk_coverage.resolve_canonical_keys("https://example.invalid/override.json")

    assert calls == ["https://example.invalid/override.json"]
    assert source_label == "https://example.invalid/override.json"
    assert keys == {"fake.key"}


def test_resolve_canonical_keys_uses_env_var_when_no_override(monkeypatch) -> None:
    monkeypatch.setenv(gen_sdk_coverage.KEY_LIST_URL_ENV_VAR, "https://example.invalid/from-env.json")
    calls = []

    def fake_fetch(url: str, *, timeout: float = 15.0):
        calls.append(url)
        return {"fake.key"}

    monkeypatch.setattr(gen_sdk_coverage, "fetch_key_list", fake_fetch)

    _keys, source_label = gen_sdk_coverage.resolve_canonical_keys()

    assert calls == ["https://example.invalid/from-env.json"]
    assert source_label == "https://example.invalid/from-env.json"


def test_extract_canonical_keys_rejects_malformed_payload() -> None:
    try:
        gen_sdk_coverage._extract_canonical_keys({"nope": []}, source="test")
    except ValueError as error:
        assert "capabilities" in str(error)
    else:
        raise AssertionError("expected ValueError for a payload without 'capabilities'")


def test_extract_canonical_keys_rejects_empty_capabilities() -> None:
    try:
        gen_sdk_coverage._extract_canonical_keys({"capabilities": []}, source="test")
    except ValueError as error:
        assert "must not be empty" in str(error)
    else:
        raise AssertionError("expected ValueError for empty capabilities[]")


def test_run_gate_passes_offline(monkeypatch) -> None:
    monkeypatch.delenv(gen_sdk_coverage.KEY_LIST_URL_ENV_VAR, raising=False)

    assert gen_sdk_coverage.run_gate() == []


def test_collect_snapshot_is_independent_of_key_list_source() -> None:
    # The generated document must not embed which key-list source validated
    # it (fixture vs. live URL), so the committed snapshot is identical
    # regardless of resolve_canonical_keys()'s resolution path. Confirm the
    # keys used in this test process (via check_keys_are_canonical) never
    # feed into collect_snapshot()'s output.
    before = gen_sdk_coverage.collect_snapshot()
    gen_sdk_coverage.resolve_canonical_keys()  # exercises the fixture path
    after = gen_sdk_coverage.collect_snapshot()

    assert before == after
    assert "keyListUrl" not in before
    assert "keyListSource" not in before


def test_snapshot_omits_untouched_capabilities() -> None:
    snapshot = gen_sdk_coverage.collect_snapshot()
    keys = {entry["key"] for entry in snapshot["capabilities"]}

    # Never-padded per #182: capabilities this SDK does not touch must not
    # appear at all, e.g. identity/alerts/channels/dr/ai/routing/caching
    # protocols this client has no surface for.
    for untouched_prefix in ("identity.", "alerts.", "channels.", "dr.", "ai.", "routing.", "caching.", "fieldops."):
        assert not any(key.startswith(untouched_prefix) for key in keys), untouched_prefix


def test_snapshot_every_entry_has_the_honest_since_version() -> None:
    snapshot = gen_sdk_coverage.collect_snapshot()

    for entry in snapshot["capabilities"]:
        assert entry["sinceVersion"] == gen_sdk_coverage.SINCE_VERSION
        assert "published to PyPI" in entry["sinceVersion"] or "unreleased" in entry["sinceVersion"]
