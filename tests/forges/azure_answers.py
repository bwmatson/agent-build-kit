"""Pull request documents as Azure DevOps really returns them.

Recorded from live `az repos pr list` output and then stripped of anything
naming an installation — the organisation, the project, the people, the
identity GUIDs and the branch names are fixtures' own.

**The fields the code does not read are kept on purpose.** `mergeStatus`,
`lastMergeCommit` and `closedDate` are exactly what makes the merge trap
catchable by a test rather than by an incident: an open pull request carries
`mergeStatus: succeeded` and a populated `lastMergeCommit` just as a merged one
does, so anything but `status` read as proof of a merge marks every open PR
merged — which restacks its children and deletes their branches.
"""

from __future__ import annotations

from copy import deepcopy

GUID = "00000000-0000-0000-0000-000000000000"
_URL = f"https://dev.azure.com/acme/{GUID}/_apis/git/repositories/{GUID}/pullRequests"

# An open pull request. Note what it already has: a successful merge status and
# a merge commit, neither of which says it was merged.
OPEN = {
    "pullRequestId": 162,
    "codeReviewId": 162,
    "status": "active",
    "mergeStatus": "succeeded",
    "mergeId": GUID,
    "lastMergeCommit": {"commitId": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"},
    "closedDate": None,
    "isDraft": False,
    "labels": None,  # null, not [], when a PR has none
    "sourceRefName": "refs/heads/spec/add-marker/1",
    "targetRefName": "refs/heads/main",
    "title": "add-marker/1: Register the marker",
    "reviewers": [],
    "supportsIterations": True,
    "url": f"{_URL}/162",
}

# The same document once a human completed it. `status` is the only field that
# changed meaning; `closedDate` arrives with it.
COMPLETED = {
    **deepcopy(OPEN),
    "pullRequestId": 157,
    "codeReviewId": 157,
    "status": "completed",
    "closedDate": "2026-09-11T22:35:38.150623+00:00",
    "reviewers": [
        {
            "displayName": "A Reviewer",
            "uniqueName": "reviewer@example.com",
            "id": GUID,
            "vote": 10,
            "isContainer": None,
            "hasDeclined": False,
            "isFlagged": False,
            "isRequired": None,
        }
    ],
}

ABANDONED = {**deepcopy(OPEN), "pullRequestId": 158, "status": "abandoned"}


def reviewer(vote: int, *, container: bool = False) -> dict:
    """One reviewer's verdict. Azure's scale: 10 approved, 5 approved with
    suggestions, 0 no vote, -5 waiting for the author, -10 rejected."""
    return {
        "displayName": "A Reviewer",
        "uniqueName": "reviewer@example.com",
        "id": GUID,
        "vote": vote,
        "isContainer": container,
        "hasDeclined": False,
        "isFlagged": False,
        "isRequired": None,
    }


def pull(**overrides) -> dict:
    """An open pull request with these fields changed."""
    return {**deepcopy(OPEN), **overrides}


# --- review threads ---------------------------------------------------------------
#
# Recorded from a real pull request's `pullRequestThreads` response. Six of its
# thirteen threads were the server talking to itself — see SYSTEM_PUSH below,
# which is the shape that arrives on *every push*.

# A reviewer's note on a line, with the pipeline's reply and the reviewer's
# answer to that. Comment ids restart at 1 in every thread, which is why a
# note's id has to carry the thread's.
REVIEW_THREAD = {
    "id": 478,
    "status": "closed",
    "isDeleted": None,
    "publishedDate": "2026-09-24T18:02:11.483Z",
    "lastUpdatedDate": "2026-09-26T14:51:02.117Z",
    "threadContext": {
        "filePath": "/poc/validate/effective_schema.py",
        "rightFileStart": {"line": 14, "offset": 1},
        "rightFileEnd": {"line": 14, "offset": 42},
    },
    "pullRequestThreadContext": None,
    "properties": {},
    "identities": None,
    "comments": [
        {
            "id": 1,
            "parentCommentId": 0,
            "commentType": "text",
            "content": "The declared schema does not match what extraction stores.",
            "author": {"displayName": "A Reviewer", "uniqueName": "reviewer@example.com"},
            "publishedDate": "2026-09-24T18:02:11.483Z",
            "usersLiked": [],
        },
        {
            "id": 2,
            "parentCommentId": 478,
            # Null, not "text". A rule that kept only "text" would drop this.
            "commentType": None,
            "content": "Addressed in a1b2c3d.",
            "author": {"displayName": "A Reviewer", "uniqueName": "reviewer@example.com"},
            "publishedDate": "2026-09-25T09:14:00.000Z",
            "usersLiked": [],
        },
        {
            "id": 3,
            "parentCommentId": 1,
            "commentType": "text",
            "content": "Confirmed against real data, thanks.",
            "author": {"displayName": "A Reviewer", "uniqueName": "reviewer@example.com"},
            "publishedDate": "2026-09-26T14:51:02.117Z",
            "usersLiked": [],
        },
    ],
}

# What Azure writes on the thread list every time a branch is pushed. The
# pipeline pushes on every rework and every restack, so counted as a comment
# this reworks the unit that just pushed, forever.
SYSTEM_PUSH = {
    "id": 473,
    "status": None,
    "threadContext": None,
    "properties": {"CodeReviewRefNewCommits": {"$type": "String", "$value": "1"}},
    "comments": [
        {
            "id": 1,
            "parentCommentId": 0,
            "commentType": "system",
            "content": "The reference refs/heads/spec/add-marker/1 was updated.",
            "author": {"displayName": "A Reviewer", "uniqueName": "reviewer@example.com"},
            "usersLiked": [],
        }
    ],
}

SYSTEM_REVIEWER_ADDED = {
    **deepcopy(SYSTEM_PUSH),
    "id": 474,
    "comments": [
        {
            **deepcopy(SYSTEM_PUSH["comments"][0]),
            "content": "A Reviewer added Another Reviewer as a reviewer",
        }
    ],
}


def thread(**overrides) -> dict:
    """A reviewer's thread with these fields changed."""
    return {**deepcopy(REVIEW_THREAD), **overrides}


def threads(*items: dict) -> dict:
    """The response body: Azure wraps a list in `value`."""
    return {"value": list(items), "count": len(items)}


# --- statuses and changes ---------------------------------------------------------

FAILED_STATUS = {
    "id": 1,
    "state": "failed",
    "description": "CI build failed",
    "context": {"genre": "continuous-integration", "name": "build"},
    "targetUrl": "https://dev.azure.com/acme/_build/results?buildId=1",
    "creationDate": "2026-09-24T18:02:11.483Z",
}

PASSED_STATUS = {
    **deepcopy(FAILED_STATUS),
    "id": 2,
    "state": "succeeded",
    "description": "CI build succeeded",
    "context": {"genre": "continuous-integration", "name": "lint"},
}

# `pending` and `notSet` are waiting, not failing: a check still running would
# otherwise send the unit back for rework while its build was in progress.
PENDING_STATUS = {
    **deepcopy(FAILED_STATUS),
    "id": 3,
    "state": "pending",
    "context": {"genre": "continuous-integration", "name": "deploy"},
}

# Each push to the source branch makes one of these. A status belongs to the
# code that was evaluated, so the changed files come from the newest.
ITERATIONS = {
    "value": [
        {"id": 1, "sourceRefCommit": {"commitId": "1111111111111111111111111111111111111111"}},
        {"id": 5, "sourceRefCommit": {"commitId": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"}},
    ],
    "count": 2,
}

CHANGES = {
    "changeEntries": [
        {"changeType": "edit", "item": {"path": "/poc/validate/verdict.py", "isFolder": False}},
        {"changeType": "add", "item": {"path": "/poc/validate/params.py", "isFolder": False}},
        # A folder is not a changed file, and would read as one path too many.
        {"changeType": "add", "item": {"path": "/poc/validate", "isFolder": True}},
    ]
}


# --- build policy evaluations -----------------------------------------------------
#
# `az repos pr policy list` answers one of these per policy configured on the
# target branch. `status` is `approved`, `rejected`, `running`, `queued`,
# `broken` or `notApplicable`; what makes it a *build* is the configuration's
# type, and what names it is the configuration's own `displayName`.

BUILD_POLICY_TYPE = {"id": "0609b952-1397-4640-95ec-e00a01b2c241", "displayName": "Build"}


def evaluation(status: str, name: str = "CI build", policy_type: dict | None = None) -> dict:
    """One evaluation of an open pull request: build validation unless a
    `policy_type` of another policy says otherwise."""
    finished = status not in ("running", "queued")
    return {
        "evaluationId": GUID,
        "configuration": {
            "id": 12,
            "isEnabled": True,
            "isBlocking": True,
            "isDeleted": False,
            "revision": 1,
            "type": deepcopy(policy_type or BUILD_POLICY_TYPE),
            "settings": {
                "buildDefinitionId": 3,
                "displayName": name,
                "queueOnSourceUpdateOnly": False,
                "validDuration": 0.0,
                "scope": [{"refName": "refs/heads/main", "matchKind": "Exact"}],
            },
        },
        "status": status,
        # Null until a build has been queued: kept, because a reader that
        # indexes into it breaks on the very evaluations that are not failing.
        "context": {"buildId": 41, "isExpired": False} if status != "queued" else None,
        "startedDate": "2026-09-24T18:02:11.483Z",
        "completedDate": "2026-09-24T18:09:00.000Z" if finished else None,
    }
