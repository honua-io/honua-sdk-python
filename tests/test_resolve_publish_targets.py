from __future__ import annotations

import pytest

from scripts.resolve_publish_targets import plan_publish


SHA = "f7930b6e9c3ce47ade148bba3d4510eeffd2ccc4"
OTHER_SHA = "953f2b3ba2cbb2d947b13c8ac5848cebe1860a76"
VERSIONS = {"sdk": "0.1.11", "admin": "0.1.8"}
SDK_TAG = "python-sdk-v0.1.11"
ADMIN_TAG = "python-admin-v0.1.8"


def test_release_please_completion_selects_only_tags_on_its_exact_commit() -> None:
    plan = plan_publish(
        event_name="workflow_run",
        release_sha=SHA,
        versions=VERSIONS,
        tag_commits={SDK_TAG: SHA, ADMIN_TAG: OTHER_SHA},
        release_is_trunk_ancestor=True,
    )

    assert plan.selected == ("sdk",)
    assert plan.publish is True
    assert plan.tags == {"sdk": SDK_TAG, "admin": ADMIN_TAG}


def test_release_please_completion_without_new_tags_is_a_clean_no_op() -> None:
    plan = plan_publish(
        event_name="workflow_run",
        release_sha=OTHER_SHA,
        versions=VERSIONS,
        tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
        release_is_trunk_ancestor=True,
    )

    assert plan.selected == ()
    assert plan.should_build is False
    assert plan.publish is False


def test_release_please_commit_must_be_on_trunk() -> None:
    with pytest.raises(ValueError, match="not an ancestor of origin/trunk"):
        plan_publish(
            event_name="workflow_run",
            release_sha=SHA,
            versions=VERSIONS,
            tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
            release_is_trunk_ancestor=False,
        )


def test_direct_tag_push_is_not_a_supported_publication_event() -> None:
    with pytest.raises(ValueError, match="Unsupported publication event"):
        plan_publish(
            event_name="push",
            release_sha=SHA,
            versions=VERSIONS,
            tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
            release_is_trunk_ancestor=True,
        )


def test_dry_manual_build_does_not_require_a_tag() -> None:
    plan = plan_publish(
        event_name="workflow_dispatch",
        release_sha=OTHER_SHA,
        versions=VERSIONS,
        tag_commits={SDK_TAG: None, ADMIN_TAG: None},
        release_is_trunk_ancestor=False,
        requested_package="both",
        dry_run=True,
        workflow_ref="refs/heads/feature",
    )

    assert plan.selected == ("sdk", "admin")
    assert plan.publish is False


def test_non_dry_manual_publication_must_run_repaired_workflow_from_trunk() -> None:
    with pytest.raises(ValueError, match="dispatch the workflow from trunk"):
        plan_publish(
            event_name="workflow_dispatch",
            release_sha=SHA,
            versions=VERSIONS,
            tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
            release_is_trunk_ancestor=True,
            requested_package="both",
            dry_run=False,
            release_tag=SDK_TAG,
            workflow_ref="refs/heads/feature",
        )


def test_non_dry_manual_single_package_requires_its_exact_tag() -> None:
    with pytest.raises(ValueError, match="does not match the selection"):
        plan_publish(
            event_name="workflow_dispatch",
            release_sha=SHA,
            versions=VERSIONS,
            tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
            release_is_trunk_ancestor=True,
            requested_package="honua-admin",
            dry_run=False,
            release_tag=SDK_TAG,
            workflow_ref="refs/heads/trunk",
        )


def test_non_dry_manual_both_requires_both_tags_on_one_release_commit() -> None:
    with pytest.raises(ValueError, match=ADMIN_TAG):
        plan_publish(
            event_name="workflow_dispatch",
            release_sha=SHA,
            versions=VERSIONS,
            tag_commits={SDK_TAG: SHA, ADMIN_TAG: OTHER_SHA},
            release_is_trunk_ancestor=True,
            requested_package="both",
            dry_run=False,
            release_tag=SDK_TAG,
            workflow_ref="refs/heads/trunk",
        )


def test_non_dry_manual_both_accepts_either_tag_when_both_map_to_release() -> None:
    plan = plan_publish(
        event_name="workflow_dispatch",
        release_sha=SHA,
        versions=VERSIONS,
        tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
        release_is_trunk_ancestor=True,
        requested_package="both",
        dry_run=False,
        release_tag=ADMIN_TAG,
        workflow_ref="refs/heads/trunk",
    )

    assert plan.selected == ("sdk", "admin")
    assert plan.publish is True
    assert plan.release_sha == SHA


def test_non_dry_manual_release_commit_must_be_on_trunk() -> None:
    with pytest.raises(ValueError, match="not an ancestor of origin/trunk"):
        plan_publish(
            event_name="workflow_dispatch",
            release_sha=SHA,
            versions=VERSIONS,
            tag_commits={SDK_TAG: SHA, ADMIN_TAG: SHA},
            release_is_trunk_ancestor=False,
            requested_package="both",
            dry_run=False,
            release_tag=SDK_TAG,
            workflow_ref="refs/heads/trunk",
        )
