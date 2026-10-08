"""A fake GitHub host a process can reach over HTTP, for tests that run `abk` as
a subprocess and point `ABK_GITHUB_API_URL` at it.

It answers the REST and GraphQL routes the forge calls from the recorded answers
in `github_answers.py` and `github_host.py`, keeps its state in memory, and lets
the test change that state the way a reviewer would on the host.
"""

from __future__ import annotations

from types import TracebackType


class FakeGitHub:
    # What the server requires in `Authorization`; the test makes the stand-in
    # `gh auth token` print the same.
    token: str
    # `http://127.0.0.1:<port>`, once started.
    url: str

    def __init__(self, token: str = "fake-github-token", *, first_number: int = 1) -> None:
        raise NotImplementedError

    def __enter__(self) -> FakeGitHub:
        raise NotImplementedError

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    def add_comment(self, number: int, body: str) -> None:
        """A conversation comment on the pull request, as a person leaves one."""
        raise NotImplementedError

    def add_review(self, number: int, state: str, body: str) -> None:
        """A submitted review (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`)."""
        raise NotImplementedError

    def merge(self, number: int) -> None:
        raise NotImplementedError

    def requests(self, method: str | None = None, path: str | None = None) -> list[tuple[str, str]]:
        """Every `(method, path)` that reached the server carrying the token."""
        raise NotImplementedError

    def unrouted(self) -> list[tuple[str, str]]:
        """Every `(method, path)` the server had no route for."""
        raise NotImplementedError
