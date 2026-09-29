"""The forge registry: which code host a repo lives on.

A workspace can hold repos on more than one host, so the pipeline asks a forge
rather than shelling `gh` directly. The registry is the same shape as
`profiles/`: filled in-process, no plugin discovery, and an unknown name says
which names it knows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import forges
from tests.conftest import make_installation


def test_a_forge_comes_back_by_name() -> None:
    assert forges.get("github").name == "github"


def test_an_unknown_forge_names_the_ones_it_knows() -> None:
    """The error a typo in abk.yaml's `forge:` produces, so it reads as a typo
    rather than as a missing feature."""
    with pytest.raises(KeyError) as caught:
        forges.get("gitlab")

    assert "gitlab" in str(caught.value)
    for known in forges.names():
        assert known in str(caught.value)


def test_every_registered_forge_satisfies_the_protocol() -> None:
    """Structural typing is checked statically, so this asserts the parts a
    static check cannot: that the registry is not empty and each entry is
    registered under the name it reports."""
    assert forges.names()
    for name in forges.names():
        assert forges.get(name).name == name


def test_a_remote_this_kit_knows_nothing_about_is_not_identified() -> None:
    """`abk init` writes a placeholder rather than guessing, and doctor reports
    the drift. Silently calling it GitHub would send every request to the wrong
    API and read back as an empty repo."""
    assert forges.identify("/srv/git/app.git") is None
    assert forges.identify("") is None


def test_a_repo_declares_its_forge_and_identity(tmp_path: Path) -> None:
    """What `Installation.forge_of` answers: which host, and the repo's name on
    it. `forge` defaults to github, so every abk.yaml written before forges
    existed keeps meaning what it meant."""
    inst = make_installation(tmp_path / "planning")

    forge, repo = inst.forge_of("app")

    assert forge.name == "github"
    assert (repo.account, repo.name) == ("example", "app")
    assert forges.key(repo) == "example/app"


def test_the_denied_prefixes_cover_every_registered_forge() -> None:
    """The deny list handed to an agent is the union, like `denies`: an agent
    in a GitHub checkout has no business completing an Azure pull request."""
    prefixes = forges.denied_prefixes()

    assert "gh pr merge" in prefixes
    assert "az repos pr update" in prefixes
    assert "az devops invoke" in prefixes


def test_a_denied_prefix_is_a_command_not_a_runtime_s_flag_syntax() -> None:
    """The runtime renders these in its own words (Claude Code's
    `Bash(...*)`); the forge only says which command it is."""
    assert all("(" not in prefix and "*" not in prefix for prefix in forges.denied_prefixes())
