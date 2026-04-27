from __future__ import annotations

from datetime import date
import json

from scripts import backlog_review


def test_render_backlog_review_flags_triage_ready_blocked_and_stale_items() -> None:
    issues = [
        backlog_review.BacklogIssue.from_json(
            {
                "number": 1,
                "title": "Ready MVP task",
                "url": "https://github.com/honua-io/honua-sdk-python/issues/1",
                "labels": [
                    {"name": "area/sdk"},
                    {"name": "priority/P1"},
                    {"name": "effort/S"},
                    {"name": "phase/MVP"},
                    {"name": "status/ready-to-start"},
                ],
                "assignees": [{"login": "owner"}],
                "milestone": {"title": "apr-2026"},
                "updatedAt": "2026-04-26T12:00:00Z",
                "body": "Ready to start.",
            }
        ),
        backlog_review.BacklogIssue.from_json(
            {
                "number": 2,
                "title": "Blocked without dependency note",
                "url": "https://github.com/honua-io/honua-sdk-python/issues/2",
                "labels": [
                    {"name": "area/sdk"},
                    {"name": "priority/P1"},
                    {"name": "effort/XL"},
                    {"name": "phase/Beta"},
                    {"name": "status/blocked"},
                ],
                "assignees": [{"login": "owner"}],
                "milestone": {"title": "apr-2026"},
                "updatedAt": "2026-03-01T00:00:00Z",
                "body": "Blocked.",
            }
        ),
        backlog_review.BacklogIssue.from_json(
            {
                "number": 3,
                "title": "Needs triage",
                "url": "https://github.com/honua-io/honua-sdk-python/issues/3",
                "labels": [{"name": "documentation"}],
                "assignees": [],
                "milestone": None,
                "updatedAt": "2026-04-26T12:00:00Z",
                "body": "",
            }
        ),
    ]

    rendered = backlog_review.render_backlog_review(
        issues,
        repo="honua-io/honua-sdk-python",
        review_date=date(2026, 4, 27),
        owner="@owner",
        stale_days=30,
    )

    assert "## Weekly Backlog Review - 2026-04-27" in rendered
    assert "Owner: @owner" in rendered
    assert "#3 missing area/*, priority/*, effort/*, phase/*, assignee, milestone" in rendered
    assert "Next 2 weeks have enough `ready-to-start` work: #1 Ready MVP task" in rendered
    assert "Blocked issues have explicit dependency notes: #2 Blocked without dependency note" in rendered
    assert "Oversized tickets are split or explicitly accepted: #2 Blocked without dependency note" in rendered
    assert "Stale items rephased or closed: #2 Blocked without dependency note" in rendered
    assert "phase/Beta `1`, phase/MVP `1`, unphased `1`" in rendered


def test_load_issues_accepts_saved_gh_issue_list_payload(tmp_path) -> None:
    payload = [
        {
            "number": 6,
            "title": "Operating cadence",
            "url": "https://github.com/honua-io/honua-sdk-python/issues/6",
            "labels": [{"name": "area/sdk"}, {"name": "priority/P1"}],
            "assignees": [{"login": "owner"}],
            "milestone": {"title": "apr-2026"},
            "updatedAt": "2026-04-27T00:00:00Z",
            "body": "Depends on honua-server#813.",
        }
    ]
    path = tmp_path / "issues.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    issues = backlog_review.load_issues(path)

    assert len(issues) == 1
    assert issues[0].number == 6
    assert issues[0].labels == ("area/sdk", "priority/P1")
    assert backlog_review.has_dependency_note(issues[0]) is True
