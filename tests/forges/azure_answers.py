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
