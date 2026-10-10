"""The one table of fake GitHub routes, and the one state they answer from.

A route is a method, a path pattern and a handler over `GitHubState`. The in-process
host (`github_host.GitHubHost`) and the HTTP server (`github_server.FakeGitHub`) both
look a request up in a scripted override first and then here.
"""

from __future__ import annotations


class GitHubState:
    """Pull requests, their reviews and inline comments, labels, statuses and the
    counters that give things ids."""

    def __init__(self) -> None:
        raise NotImplementedError
