# Operating Cadence

This repo uses a weekly backlog review to keep SDK scope, priority, and close
hygiene explicit. Each review should produce a dated markdown comment on the
active backlog review thread. If there is no active thread, create one for that
week and close it after the decisions are applied.

## Weekly Review

Run the review once per week before starting new backlog work:

```bash
python scripts/backlog_review.py \
  --repo honua-io/honua-sdk-python \
  --owner @mikemcdougall
```

Post the generated markdown as a dated comment on the active review issue:

```bash
python scripts/backlog_review.py \
  --repo honua-io/honua-sdk-python \
  --owner @mikemcdougall \
  | gh issue comment <issue-number> --repo honua-io/honua-sdk-python --body-file -
```

For an offline or audited run, capture the issue list first and render from that
snapshot:

```bash
gh issue list \
  --repo honua-io/honua-sdk-python \
  --state open \
  --limit 200 \
  --json number,title,url,labels,assignees,milestone,updatedAt,body \
  > backlog-issues.json

python scripts/backlog_review.py \
  --repo honua-io/honua-sdk-python \
  --input backlog-issues.json \
  --date 2026-04-27 \
  --owner @mikemcdougall
```

## Backlog Review Gate

Every open issue should have:

- one `area/*` label
- one `priority/*` label
- one `effort/*` label
- one `phase/*` label
- an assignee when the work is owned
- a milestone when the target release is known

The generated review calls out missing triage fields. Fix straightforward gaps
directly in GitHub. If a gap reflects uncertainty, leave it visible in the
weekly comment and add the decision needed to resolve it.

Maintain at least two weeks of `status/ready-to-start` work. If the generated
review shows no ready work, convert the next highest-priority issues into
smaller, unblocked tickets before pulling more implementation scope.

Blocked issues should use `status/blocked` and include an explicit dependency
note in the issue body, such as `Blocked by honua-server#813` or `Depends on
honua-devops#42`.

## Scope Gate

Every new scope addition needs an explicit tradeoff in the weekly comment:

- what was added
- what was deferred or removed
- whether the change affects MVP, Beta, or GA scope
- whether another repo owns a blocker

Tickets labeled `effort/XL` should be split before implementation unless the
weekly review explicitly accepts the oversized ticket and names the reason.

## Done/Close Hygiene

Close completed work within 24 hours of merge. If a PR only partially satisfies
an issue, leave a comment on the issue with exact remaining tasks before moving
on.

The review marks open issues as stale when they have not been updated for 30
days by default. Use `--stale-days` to adjust that window for a special review:

```bash
python scripts/backlog_review.py --stale-days 14
```

Stale items should be rephased, closed, or refreshed with a current decision.
