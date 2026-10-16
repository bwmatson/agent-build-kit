"""`abk doctor` fails `planning.publish: direct` where the default branch is protected, in an
installation whose planning repository is also a code repo (spec: planning-publish)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import RepoConfig
from tests.cli.in_repo_doctor import (
    PROTECTED,
    STATE_IGNORES,
    UNPROTECTED,
    UNREADABLE,
    checks_of,
    in_repo,
    named,
    separate,
)
from tests.cli.public_content_repo import planning
from tests.factories import init_repo

CHECK = "planning publish"


def test_direct_with_a_protected_default_branch_fails_naming_the_setting_to_change(
    tmp_path: Path,
) -> None:
    config = in_repo(tmp_path / "app", publish="direct", guard=PROTECTED)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "FAIL"
    assert "planning.publish: branch" in found.fix


def test_the_default_publish_is_direct_and_fails_the_same(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish=None, guard=PROTECTED)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "FAIL"


def test_branch_with_a_protected_default_branch_is_ok(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="branch", guard=PROTECTED)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "ok"
    assert "is protected" in found.detail
    assert "not protected" not in found.detail


def test_direct_where_nothing_protects_the_default_branch_is_ok(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="direct", guard=UNPROTECTED)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "ok"


def test_a_forge_that_cannot_say_gives_an_info_line_saying_so(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app", publish="direct", guard=UNREADABLE)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "info"
    assert "cannot tell" in found.detail


def test_a_separate_installation_gets_no_such_check_where_an_in_repo_one_does(
    tmp_path: Path,
) -> None:
    in_repo_config = in_repo(tmp_path / "app", publish="direct", guard=PROTECTED)
    code = init_repo(tmp_path / "code")
    separate_config = separate(tmp_path / "plan", code, publish="direct", guard=PROTECTED)

    assert len(named(checks_of(in_repo_config), CHECK)) == 1
    assert named(checks_of(separate_config), CHECK) == []


def test_a_local_forge_repo_with_the_default_publish_is_ok_not_protected(tmp_path: Path) -> None:
    """Nothing on a server guards a local repo, so a direct push works."""
    repos = {"app": RepoConfig(path=Path("."), forge="local", changelog=None)}
    config = planning(tmp_path / "app", repos=repos, ignore=STATE_IGNORES)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "ok"
    assert "no server guards" in found.detail
