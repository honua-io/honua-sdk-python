"""Render the weekly backlog review comment for this repository."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

TRIAGE_LABEL_PREFIXES = ("area/", "priority/", "effort/", "phase/")
READY_LABELS = frozenset({"ready-to-start", "status/ready-to-start"})
BLOCKED_LABELS = frozenset({"blocked", "status/blocked"})
DEPENDENCY_NOTE_MARKERS = (
    "blocked by",
    "depends on",
    "dependency",
    "honua-server#",
    "honua-devops#",
)


@dataclass(frozen=True)
class BacklogIssue:
    number: int
    title: str
    url: str
    labels: tuple[str, ...]
    assignees: tuple[str, ...]
    milestone: str | None
    updated_at: datetime | None
    body: str

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "BacklogIssue":
        return cls(
            number=int(payload["number"]),
            title=str(payload["title"]),
            url=str(payload.get("url") or ""),
            labels=tuple(_label_names(payload.get("labels"))),
            assignees=tuple(_assignee_logins(payload.get("assignees"))),
            milestone=_milestone_title(payload.get("milestone")),
            updated_at=_parse_datetime(payload.get("updatedAt")),
            body=str(payload.get("body") or ""),
        )


def render_backlog_review(
    issues: Sequence[BacklogIssue],
    *,
    repo: str,
    review_date: date,
    owner: str | None = None,
    stale_days: int = 30,
) -> str:
    triage_gaps = [(issue, missing_triage_fields(issue)) for issue in issues]
    triage_gaps = [(issue, gaps) for issue, gaps in triage_gaps if gaps]
    ready_issues = [issue for issue in issues if is_ready_to_start(issue)]
    blocked_without_notes = [
        issue for issue in issues if is_blocked(issue) and not has_dependency_note(issue)
    ]
    oversized_issues = [issue for issue in issues if issue_has_label(issue, "effort/XL")]
    stale_cutoff = datetime.combine(review_date, datetime.min.time(), tzinfo=timezone.utc) - timedelta(
        days=stale_days
    )
    stale_issues = [issue for issue in issues if issue.updated_at is not None and issue.updated_at < stale_cutoff]

    priority_counts = label_counts_by_prefix(issues, "priority/")
    effort_counts = label_counts_by_prefix(issues, "effort/")
    phase_counts = label_counts_by_prefix(issues, "phase/")
    unphased_count = sum(1 for issue in issues if label_with_prefix(issue, "phase/") is None)

    owner_line = f"Owner: {owner}" if owner else "Owner: TBD"
    lines = [
        f"## Weekly Backlog Review - {review_date.isoformat()}",
        "",
        owner_line,
        f"Repository: `{repo}`",
        f"Open issues reviewed: `{len(issues)}`",
        "",
        "### Backlog Review",
        f"- [ ] New issues triaged: {triage_gap_summary(triage_gaps)}",
        f"- [ ] Next 2 weeks have enough `ready-to-start` work: {issue_list_summary(ready_issues)}",
        f"- [ ] Blocked issues have explicit dependency notes: {issue_list_summary(blocked_without_notes)}",
        "",
        "### Scope Gate",
        "- [ ] New scope has an explicit tradeoff: add decision notes below when scope changes.",
        f"- [ ] MVP/Beta/GA mix is intentional: {phase_mix_summary(phase_counts, unphased_count)}",
        f"- [ ] Oversized tickets are split or explicitly accepted: {issue_list_summary(oversized_issues)}",
        "",
        "### Done/Close Hygiene",
        "- [ ] Completed work closed within 24 hours: TODO note any merged-but-open items.",
        "- [ ] Partially complete work has exact remaining tasks: TODO note any partial closes.",
        f"- [ ] Stale items rephased or closed: {issue_list_summary(stale_issues)}",
        "",
        "### Label Snapshot",
        f"- Priorities: {counter_summary(priority_counts)}",
        f"- Effort: {counter_summary(effort_counts)}",
        f"- Phase: {counter_summary(phase_counts)}",
        "",
        "### Outcomes And Decisions",
        "- TODO",
    ]
    return "\n".join(lines) + "\n"


def missing_triage_fields(issue: BacklogIssue) -> list[str]:
    missing = [f"{prefix}*" for prefix in TRIAGE_LABEL_PREFIXES if label_with_prefix(issue, prefix) is None]
    if not issue.assignees:
        missing.append("assignee")
    if issue.milestone is None:
        missing.append("milestone")
    return missing


def label_with_prefix(issue: BacklogIssue, prefix: str) -> str | None:
    for label in issue.labels:
        if label.startswith(prefix):
            return label
    return None


def issue_has_label(issue: BacklogIssue, label: str) -> bool:
    return label in issue.labels


def is_ready_to_start(issue: BacklogIssue) -> bool:
    return any(label in READY_LABELS for label in issue.labels)


def is_blocked(issue: BacklogIssue) -> bool:
    return any(label in BLOCKED_LABELS for label in issue.labels)


def has_dependency_note(issue: BacklogIssue) -> bool:
    body = issue.body.lower()
    return any(marker in body for marker in DEPENDENCY_NOTE_MARKERS)


def label_counts_by_prefix(issues: Iterable[BacklogIssue], prefix: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for issue in issues:
        label = label_with_prefix(issue, prefix)
        if label is not None:
            counts[label] += 1
    return counts


def triage_gap_summary(gaps: Sequence[tuple[BacklogIssue, Sequence[str]]]) -> str:
    if not gaps:
        return "no gaps found"
    entries = [f"#{issue.number} missing {', '.join(missing)}" for issue, missing in gaps[:8]]
    suffix = f"; +{len(gaps) - 8} more" if len(gaps) > 8 else ""
    return "; ".join(entries) + suffix


def issue_list_summary(issues: Sequence[BacklogIssue]) -> str:
    if not issues:
        return "none"
    entries = [f"#{issue.number} {issue.title}" for issue in issues[:8]]
    suffix = f"; +{len(issues) - 8} more" if len(issues) > 8 else ""
    return "; ".join(entries) + suffix


def phase_mix_summary(counts: Counter[str], unphased_count: int) -> str:
    parts = [f"{label} `{count}`" for label, count in sorted(counts.items())]
    if unphased_count:
        parts.append(f"unphased `{unphased_count}`")
    return ", ".join(parts) if parts else "no phase labels found"


def counter_summary(counts: Counter[str]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{label} `{count}`" for label, count in sorted(counts.items()))


def load_issues(path: Path) -> list[BacklogIssue]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Backlog issue input must be a JSON array.")
    return [BacklogIssue.from_json(item) for item in payload if isinstance(item, Mapping)]


def fetch_issues(repo: str, *, limit: int) -> list[BacklogIssue]:
    command = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        "number,title,url,labels,assignees,milestone,updatedAt,body",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list):
        raise ValueError("GitHub issue list response was not a JSON array.")
    return [BacklogIssue.from_json(item) for item in payload if isinstance(item, Mapping)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="honua-io/honua-sdk-python", help="GitHub repository in owner/name form.")
    parser.add_argument("--input", type=Path, help="Optional saved `gh issue list --json ...` payload.")
    parser.add_argument("--date", help="Review date as YYYY-MM-DD. Defaults to today's UTC date.")
    parser.add_argument("--owner", help="Owner handle or name to render in the weekly comment.")
    parser.add_argument("--limit", type=int, default=200, help="Maximum open issues to fetch when --input is omitted.")
    parser.add_argument("--stale-days", type=int, default=30, help="Days since update before an open issue is stale.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        review_date = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
        issues = load_issues(args.input) if args.input else fetch_issues(args.repo, limit=args.limit)
        sys.stdout.write(
            render_backlog_review(
                issues,
                repo=args.repo,
                review_date=review_date,
                owner=args.owner,
                stale_days=args.stale_days,
            )
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def _label_names(raw_labels: Any) -> list[str]:
    if not isinstance(raw_labels, list):
        return []
    names: list[str] = []
    for item in raw_labels:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, Mapping) and item.get("name"):
            names.append(str(item["name"]))
    return names


def _assignee_logins(raw_assignees: Any) -> list[str]:
    if not isinstance(raw_assignees, list):
        return []
    logins: list[str] = []
    for item in raw_assignees:
        if isinstance(item, str):
            logins.append(item)
        elif isinstance(item, Mapping) and item.get("login"):
            logins.append(str(item["login"]))
    return logins


def _milestone_title(raw_milestone: Any) -> str | None:
    if isinstance(raw_milestone, str):
        return raw_milestone
    if isinstance(raw_milestone, Mapping) and raw_milestone.get("title"):
        return str(raw_milestone["title"])
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
