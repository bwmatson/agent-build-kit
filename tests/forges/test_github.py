"""The GitHub forge: the identity half.

These are the cases `init.parse_slug` covered before the forges existed - the
same four URL forms, including the ssh host alias, which is why the GitHub
pattern has to stay permissive and be tried last.
"""

from __future__ import annotations

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.github import FORGE


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:example/app.git",
        "https://github.com/example/app",
        "https://github.com/example/app.git",
        "ssh://git@github.com/example/app.git",
        "github-example:example/app.git",
    ],
)
def test_every_origin_form_yields_the_same_identity(url: str) -> None:
    repo = FORGE.parse_remote(url)

    assert repo is not None
    assert (repo.forge, repo.account, repo.name) == ("github", "example", "app")
    assert repo.project == "", "GitHub has no project segment"


def test_a_url_that_is_not_a_remote_is_refused() -> None:
    assert FORGE.parse_remote("/srv/git/app.git") is None
    assert FORGE.parse_remote("") is None


def test_the_identity_key_is_the_slug_the_rest_of_the_kit_uses() -> None:
    """`own-posts.json` and the poller's state are keyed on it, so it has to
    stay `owner/name` for GitHub or a running installation loses its history."""
    repo = FORGE.parse_remote("git@github.com:example/app.git")

    assert repo is not None
    assert forges.key(repo) == "example/app"


def test_the_web_url_points_at_the_pull_request() -> None:
    """`diagram.py` links every unit to its PR; it hardcoded github.com."""
    repo = FORGE.parse_remote("git@github.com:example/app.git")

    assert repo is not None
    assert forges.get("github").web_url(repo) == "https://github.com/example/app"
    assert forges.get("github").web_url(repo, pr=7) == "https://github.com/example/app/pull/7"
