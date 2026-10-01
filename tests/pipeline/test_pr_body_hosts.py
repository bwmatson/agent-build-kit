"""A PR body that names the repo's real default branch and its real CI.

The body used to say "already in `main`" for a repo that integrates on `dev`,
and "GitHub Actions runs the whole of it" for a repo that is not on GitHub.
Both are facts about the repo, so both come from it: the branch from
`abk.yaml`, the CI's name from the forge the repo lives on.
"""

from __future__ import annotations

from agent_build_kit import config as config_module
from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.pr_body import assumptions, build_pr_body
from tests.factories import stored_unit as unit


def repo_with(**fields) -> None:
    """The active workspace with `app` changed: its default branch, its host."""
    current = config_module.active()
    repos = dict(current.repos)
    repos["app"] = RepoConfig.model_validate({**repos["app"].model_dump(mode="json"), **fields})
    config_module.activate(current.model_copy(update={"repos": repos}), config_module.active_root())


AZURE = {
    "forge": "azure_devops",
    "slug": "",
    "azure_devops": {"org": "acme", "project": "Some Project", "repo": "Some Repo"},
}


def test_the_assumption_names_the_integration_branch() -> None:
    repo_with(default_branch="dev")

    body = build_pr_body(unit(depends_on=()), graph=[unit(depends_on=())], base="dev")

    assert "already in `dev`" in body
    assert "already in `main`" not in body


def test_a_repo_on_main_still_says_main() -> None:
    body = build_pr_body(unit(depends_on=()), graph=[unit(depends_on=())], base="main")

    assert "already in `main`" in body


def test_assumptions_take_the_trunk_they_are_told() -> None:
    text = assumptions(unit(depends_on=()), [unit(depends_on=())], trunk="dev")

    assert "already in `dev`" in text


def test_an_azure_tier_one_body_names_no_github_service() -> None:
    repo_with(**AZURE)

    body = build_pr_body(unit(tier="tier1"), graph=[unit()], base="main")

    assert "GitHub Actions" not in body
    assert "tier 1" in body.lower()


def test_an_azure_tier_one_body_names_its_own_ci() -> None:
    """The name comes from the forge, so a host's body says its own."""
    from agent_build_kit.forges.azure_devops import FORGE

    repo_with(**AZURE)

    body = build_pr_body(unit(tier="tier1"), graph=[unit()], base="main")

    assert FORGE.ci_name
    assert FORGE.ci_name in body


def test_a_github_tier_one_body_is_unchanged() -> None:
    body = build_pr_body(unit(tier="tier1"), graph=[unit()], base="main")

    assert "so GitHub Actions runs the whole of it" in body
