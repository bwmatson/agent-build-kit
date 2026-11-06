"""`abk e2e-test check` names the tests a unit's own branch adds or changes by the remote's trunk,
as the e2e-test step does: a local trunk that nothing updates is never the base (spec:
unit-own-tests)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.e2e_cmd import unit_own_tests
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.e2e_scope_fakes import CHANGED, NEW, OLD
from tests.factories import commit_files, git, init_repo, stored_unit

BRANCH = "spec/add-marker/1"


def installation_with_checkout(tmp_path: Path) -> tuple[Installation, Path]:
    installation = make_installation(tmp_path)
    return installation, installation.checkouts["app"]


def behind_the_remote(checkout: Path) -> None:
    """A unit branch that adds one test and changes another. The remote's trunk has the tests the
    trunk merged since (one changed that the checkout has, one new); the local `main` is where it
    stood when the unit started, behind both."""
    init_repo(checkout)
    git(checkout, "remote", "add", "origin", "git@github.com:example/app.git")
    commit_files(checkout, "A", {"pyproject.toml": "[project]\nname = 'app'\n"})
    commit_files(
        checkout, "tests", {"tests/live/test_old.py": OLD, "tests/live/test_shared.py": OLD}
    )
    started = git(checkout, "rev-parse", "HEAD").strip()
    commit_files(
        checkout, "merged", {"tests/live/test_shared.py": CHANGED, "tests/live/test_trunk.py": NEW}
    )
    git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(checkout, "switch", "-q", "-c", BRANCH)
    commit_files(
        checkout, "unit", {"tests/live/test_new.py": NEW, "tests/live/test_old.py": CHANGED}
    )
    git(checkout, "branch", "-q", "-f", "main", started)


def test_a_local_trunk_behind_the_remotes_adds_no_test_to_the_unit(tmp_path: Path) -> None:
    installation, checkout = installation_with_checkout(tmp_path)
    behind_the_remote(checkout)

    listed = unit_own_tests(installation, stored_unit(branch=BRANCH))

    assert sorted(listed) == [
        "tests/live/test_new.py::test_new",
        "tests/live/test_old.py::test_old",
    ]


def test_a_unit_with_no_branch_lists_none(tmp_path: Path) -> None:
    installation, checkout = installation_with_checkout(tmp_path)
    behind_the_remote(checkout)

    assert list(unit_own_tests(installation, stored_unit(branch=""))) == []
