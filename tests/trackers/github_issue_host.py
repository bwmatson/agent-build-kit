"""GitHub issues at the HTTP boundary: a stand-in answering the issues REST calls.

It keeps the issues, their sub-issues, the owner's kind and whether it has issue types, and
the body of every create it was sent; the documents it answers with are shaped after the
reference-written bodies under `recorded/github`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import httpx


class IssueHost(httpx.MockTransport):
    # Every issue by number, as the host answers it, and the body of each create sent.
    issues: dict[int, dict[str, Any]]
    creates: list[dict[str, Any]]

    def __init__(
        self,
        *,
        owner_kind: Literal["Organization", "User"] = "Organization",
        types_enabled: bool = True,
        sub_issue_limit: int = 100,
        lose_create_answer: bool = False,
    ) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500.
        `sub_issue_limit` is the most sub-issues a parent holds. `types_enabled` only counts
        for an organization."""
        raise NotImplementedError

    def seed(
        self,
        title: str,
        *,
        parent: str | None = None,
        labels: Sequence[str] = (),
        type: str | None = None,
    ) -> str:
        """An issue that already exists, as a person made it; its number."""
        raise NotImplementedError

    def sub_issues_of(self, parent: str) -> list[str]:
        """The numbers of the sub-issues of an issue, in order."""
        raise NotImplementedError
