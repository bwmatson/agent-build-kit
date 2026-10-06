"""GitHub's answers as it sends them: the GraphQL pull request nodes, job lists
and job logs, with the fields the code does not read kept on purpose.

A node carries what the host adds to every one: node ids, authors, timestamps,
`null` for a review decision nobody required, `null` for a rollup a commit
without checks has, and a rollup context that is a commit status rather than a
check run (which has no conclusion and is not one of the checks).
"""

from __future__ import annotations

from typing import Any

OWNER = "example"
NAME = "app"
WEB = f"https://github.com/{OWNER}/{NAME}"


def check_run(
    name: str,
    conclusion: str | None,
    *,
    run: int = 1,
    job: int = 2,
    status: str = "COMPLETED",
) -> dict[str, Any]:
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": f"{WEB}/actions/runs/{run}/job/{job}",
        "startedAt": "2026-09-28T09:18:40Z",
        "completedAt": "2026-09-28T09:20:01Z" if conclusion else None,
        "databaseId": job,
        "isRequired": False,
    }


STATUS_CONTEXT = {
    "__typename": "StatusContext",
    "context": "local/tier2",
    "state": "FAILURE",
    "targetUrl": None,
    "description": "tier 2 failed",
    "createdAt": "2026-09-28T09:21:00Z",
}


def pull(
    number: int,
    *,
    head: str | None = None,
    base: str = "main",
    state: str = "OPEN",
    draft: bool = False,
    merged_at: str | None = None,
    mergeable: str = "MERGEABLE",
    review_decision: str | None = None,
    labels: tuple[str, ...] = (),
    comments: tuple[tuple[str, str], ...] = (),
    reviews: tuple[tuple[str, str, str], ...] = (),
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One pull request as the listing query answers it.

    `comments` are `(node id, body)`, `reviews` `(node id, state, body)`;
    `checks=None` is a commit with no checks, whose rollup is `null`.
    """
    rollup = (
        None
        if checks is None
        else {"state": "FAILURE", "contexts": {"totalCount": len(checks), "nodes": checks}}
    )
    return {
        "id": f"PR_kwDOAAAAAc{number:08d}",
        "number": number,
        "title": f"add-marker/{number}: Register the marker",
        "headRefName": head or f"spec/add-marker/{number}",
        "baseRefName": base,
        "state": state,
        "isDraft": draft,
        "mergedAt": merged_at,
        "closedAt": merged_at,
        "mergeable": mergeable,
        "mergeStateStatus": "CLEAN",
        "reviewDecision": review_decision,
        "url": f"{WEB}/pull/{number}",
        "author": {"__typename": "User", "login": OWNER},
        "labels": {
            "totalCount": len(labels),
            "nodes": [
                {"id": f"LA_kwDOAAAAAc8AAAAB{i:04d}", "name": name, "color": "2563eb"}
                for i, name in enumerate(labels)
            ],
        },
        "comments": {
            "totalCount": len(comments),
            "nodes": [
                {
                    "id": node,
                    "body": body,
                    "author": {"__typename": "User", "login": OWNER},
                    "createdAt": "2026-09-28T09:12:44Z",
                    "isMinimized": False,
                }
                for node, body in comments
            ],
        },
        "reviews": {
            "totalCount": len(reviews),
            "nodes": [
                {
                    "id": node,
                    "state": review_state,
                    "body": body,
                    "author": {"__typename": "User", "login": "reviewer"},
                    "submittedAt": None if review_state == "PENDING" else "2026-09-28T10:00:00Z",
                }
                for node, review_state, body in reviews
            ],
        },
        "commits": {
            "totalCount": 1,
            "nodes": [
                {
                    "commit": {
                        "oid": f"{number:040x}",
                        "statusCheckRollup": rollup,
                    }
                }
            ],
        },
    }


def job(job_id: int, name: str, conclusion: str | None, run: int = 1) -> dict[str, Any]:
    """A job of a workflow run, as the run's job list carries it."""
    return {
        "id": job_id,
        "run_id": run,
        "name": name,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "started_at": "2026-10-01T16:33:50Z",
        "completed_at": "2026-10-01T16:34:23Z" if conclusion else None,
        "html_url": f"{WEB}/actions/runs/{run}/job/{job_id}",
        "steps": [],
    }


BOM = "﻿"

# A job's whole log: the first line carries a byte order mark, the error is
# followed by the runner's clean-up, and one line holds colour escapes.
JOB_LOG = "\n".join(
    [
        f"{BOM}2026-10-01T16:34:04.0987227Z ##[group]Run uv run pre-commit run --all-files",
        "2026-10-01T16:34:21.1000000Z pyrefly check....Failed",
        "2026-10-01T16:34:21.2000000Z \x1b[31mERROR\x1b[0m Argument `str` is not assignable",
        "2026-10-01T16:34:21.3000000Z    --> tests/runtimes/acp_agent.py:641:24",
        "2026-10-01T16:34:21.4000000Z ##[error]Process completed with exit code 1.",
        "2026-10-01T16:34:22.5554669Z Cleaning up orphan processes",
        "2026-10-01T16:34:22.5861981Z ##[warning]Node.js 20 is deprecated.",
    ]
)
