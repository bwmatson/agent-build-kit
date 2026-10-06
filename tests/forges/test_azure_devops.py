"""The Azure DevOps forge's identity and the commands an agent may not run.

What the forge does over the wire is in `test_azure_rest_*.py`.
"""

from __future__ import annotations

import pytest

from agent_build_kit import forges
from agent_build_kit.config import AzureDevOpsConfig, RepoConfig
from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import RepoId


@pytest.mark.parametrize(
    "url",
    [
        "git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo",
        "ssh://git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo",
        "https://acme@dev.azure.com/acme/Some%20Project/_git/Some%20Repo",
        "https://dev.azure.com/acme/Some%20Project/_git/Some%20Repo",
    ],
)
def test_every_origin_form_yields_the_same_decoded_identity(url: str) -> None:
    """Decoded: an Azure remote percent-encodes a project with a space in it,
    and every API call wants the readable form back, and encodes it itself."""
    repo = FORGE.parse_remote(url)

    assert repo is not None
    assert (repo.forge, repo.account, repo.project, repo.name) == (
        "azure_devops",
        "acme",
        "Some Project",
        "Some Repo",
    )


def test_a_github_remote_is_not_claimed() -> None:
    """Both forges see every remote, so each has to refuse the other's."""
    assert FORGE.parse_remote("git@github.com:example/app.git") is None
    assert FORGE.parse_remote("") is None


def test_the_registry_asks_the_host_anchored_forge_first() -> None:
    """GitHub's pattern accepts any `alias:owner/name`, so asked first it
    would claim this remote and name the repo `v3/acme`."""
    repo = forges.identify("git@ssh.dev.azure.com:v3/acme/Some%20Project/Some%20Repo")

    assert repo is not None
    assert repo.forge == "azure_devops"
    assert repo.project == "Some Project"


def test_the_identity_key_carries_all_three_segments() -> None:
    """Two repos in one organisation can share a name across projects, so the
    project has to be in the key the state files are written under."""
    repo = FORGE.parse_remote("https://dev.azure.com/acme/Some%20Project/_git/Some%20Repo")

    assert repo is not None
    assert forges.key(repo) == "acme/Some Project/Some Repo"


def test_the_identity_comes_from_its_own_block_in_abk_yaml() -> None:
    """Not from `slug`: three segments re-split from one string is exactly the
    ambiguity a project name containing a slash would break."""
    config = RepoConfig(
        path="app",
        forge="azure_devops",
        azure_devops=AzureDevOpsConfig(org="acme", project="Some Project", repo="Some Repo"),
    )

    assert FORGE.identity(config) == RepoId(
        forge="azure_devops", account="acme", project="Some Project", name="Some Repo"
    )


def test_the_web_url_points_at_the_pull_request() -> None:
    repo = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

    assert FORGE.web_url(repo) == "https://dev.azure.com/acme/Some%20Project/_git/Some%20Repo"
    assert FORGE.web_url(repo, pr=7).endswith("/pullrequest/7")


def test_every_way_of_merging_is_denied_to_the_agent() -> None:
    """Wider than GitHub's one command: an update can complete a PR, a vote
    can approve one, and both `az rest` and `az devops invoke` reach the same
    API directly."""
    denied = {" ".join(command) for command in FORGE.denied_commands}

    assert "az repos pr update" in denied
    assert "az repos pr set-vote" in denied
    assert "az repos policy" in denied
    assert "az rest" in denied
    assert "az devops invoke" in denied


@pytest.mark.parametrize(
    "command",
    [
        "az repos pr update --id 5 --status completed",
        "az repos pr update --id 5 --status abandoned --auto-complete true",
        "az repos pr update --id 5 --status abandoned --bypass-policy true",
        "az repos pr update --id 5 --status abandoned --squash true",
        "az repos pr update --id 5 --status abandoned --delete-source-branch true",
        "az repos pr update --id 5 --status abandoned --merge-commit-message x",
        "az repos pr update --id 5 --title x",
        "az repos pr update --id 5 --stat abandoned",
        "az repos pr update --id 5 --status abandoned --auto-c true",
        "az repos pr update --id 5 --description x",
        "az repos pr update --id five --status abandoned",
        "az repos pr update --id 5 --status abandoned --status active",
        "az repos pr update --id 5 --status",
        "az repos pr update --id 5 --status --draft true",
        "az repos pr update --id 5 --status abandoned extra",
        "az repos pr update --id 5 --draft maybe",
        "az repos pr set-vote --id 5 --vote approve",
        "az repos policy create",
        "az rest --method patch --url https://x --body {status:abandoned}",
        "az devops invoke --area git --resource pullRequests",
    ],
)
def test_anything_else_under_a_denied_prefix_stays_denied(command: str) -> None:
    assert forges.denies(command.split()), command


def test_the_source_branch_is_ours_to_delete() -> None:
    """Azure keeps the source branch unless the PR asked for it to go, so
    unlike GitHub the remote branch is left behind after a merge."""
    assert FORGE.deletes_head_branch_on_merge is False


def test_the_forge_is_now_complete() -> None:
    """Every method answers, so units in an Azure DevOps repo build rather
    than being held."""
    assert FORGE.implemented is True
