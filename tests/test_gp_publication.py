from __future__ import annotations


import pytest

from scripts.resolve_publish_targets import plan_publish
from tests.test_resolve_publish_targets import SHA, OTHER_SHA, VERSIONS, SDK_TAG, ADMIN_TAG


GP_TAG = "python-gp-v0.1.0"


def test_gp_release_selects_only_the_exact_tagged_commit() -> None:
    plan = plan_publish(
        event_name="workflow_run", release_sha=SHA, versions=VERSIONS,
        tag_commits={SDK_TAG: OTHER_SHA, ADMIN_TAG: OTHER_SHA, GP_TAG: SHA},
        release_is_trunk_ancestor=True,
    )
    assert plan.selected == ("gp",)
    assert plan.publish is True


@pytest.mark.parametrize("tag_commit", [None, OTHER_SHA])
def test_manual_gp_publication_rejects_missing_or_moved_tag(tag_commit: str | None) -> None:
    with pytest.raises(ValueError, match="python-gp-v"):
        plan_publish(
            event_name="workflow_dispatch", release_sha=SHA, versions=VERSIONS,
            tag_commits={GP_TAG: tag_commit}, release_is_trunk_ancestor=True,
            requested_package="honua-gp", dry_run=False, release_tag=GP_TAG,
            workflow_ref="refs/heads/trunk",
        )


def test_manual_gp_publication_accepts_its_exact_release() -> None:
    plan = plan_publish(
        event_name="workflow_dispatch", release_sha=SHA, versions=VERSIONS,
        tag_commits={GP_TAG: SHA}, release_is_trunk_ancestor=True,
        requested_package="honua-gp", dry_run=False, release_tag=GP_TAG,
        workflow_ref="refs/heads/trunk",
    )
    assert plan.selected == ("gp",)
    assert plan.publish is True
