"""The literals, provider files and home facts of the merged configuration are scrub terms."""

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.scrub_terms import terms_for
from tests.conftest import make_installation


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    faked = tmp_path / "homes" / "quuxuser"
    faked.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(faked))
    return faked


def _inst(tmp_path: Path, **overrides) -> Installation:
    return make_installation(tmp_path / "planning", **overrides)


def _target(tmp_path: Path) -> Path:
    target = tmp_path / "checkout"
    target.mkdir()
    return target


def test_a_literal_value_is_a_term_unless_it_is_all_digits(tmp_path: Path, home: Path) -> None:
    inst = _inst(
        tmp_path,
        verify={
            "env": {
                "AGENT_CMD": {"from": "literal", "value": "agentcmd --flag"},
                "PORT": {"from": "literal", "value": "7140"},
            }
        },
    )

    terms = terms_for(inst, target=_target(tmp_path))

    assert "agentcmd --flag" in terms
    assert "7140" not in terms


def test_an_env_file_provider_gives_its_home_directory_and_file_name(
    tmp_path: Path, home: Path
) -> None:
    inst = _inst(
        tmp_path,
        verify={
            "env": {
                "TOKEN": {
                    "from": "env-file",
                    "file": str(home / ".secretdir" / "creds.env"),
                    "key": "TOKEN",
                }
            }
        },
    )

    terms = terms_for(inst, target=_target(tmp_path))

    assert ".secretdir" in terms
    assert "creds.env" in terms


def test_the_user_name_of_the_home_is_a_term(tmp_path: Path, home: Path) -> None:
    terms = terms_for(_inst(tmp_path), target=_target(tmp_path))

    assert "quuxuser" in terms


def test_a_path_under_the_runtime_s_own_directory_gives_none(tmp_path: Path, home: Path) -> None:
    inst = _inst(
        tmp_path,
        planning={"worktree_root": str(home / ".claude" / "trees")},
        repos={"app": {"path": str(home / ".claude" / "app"), "slug": "example/app"}},
    )

    terms = terms_for(inst, target=_target(tmp_path))

    assert ".claude" not in terms


def test_a_dot_directory_of_a_configured_path_is_a_term(tmp_path: Path, home: Path) -> None:
    inst = _inst(tmp_path, planning={"worktree_root": str(home / ".trees-x" / "wt")})

    assert ".trees-x" in terms_for(inst, target=_target(tmp_path))


def test_a_literal_only_the_overlay_holds_is_still_a_term(tmp_path: Path, home: Path) -> None:
    # The installation stands in for the merged configuration the overlay's loader gives.
    merged = _inst(
        tmp_path,
        verify={"env": {"HOSTNAME_X": {"from": "literal", "value": "only-in-overlay"}}},
    )

    assert "only-in-overlay" in terms_for(merged, target=_target(tmp_path))


def test_a_provider_file_in_the_planning_root_does_not_name_the_root(
    tmp_path: Path, home: Path
) -> None:
    root = home / "plan"
    inst = make_installation(
        root,
        repos={"app": {"path": str(root), "slug": "example/app"}},
        verify={"env": {"TOKEN": {"from": "env-file", "file": str(root / ".env"), "key": "TOKEN"}}},
    )

    assert "plan" not in terms_for(inst, target=root)


def test_a_provider_file_in_a_tool_directory_gives_no_directory(tmp_path: Path, home: Path) -> None:
    inst = _inst(
        tmp_path,
        verify={
            "env": {
                "TOKEN": {
                    "from": "env-file",
                    "file": str(home / ".config" / "x" / "creds.env"),
                    "key": "TOKEN",
                }
            }
        },
    )

    terms = terms_for(inst, target=_target(tmp_path))

    assert ".config" not in terms
    assert "creds.env" in terms


def test_a_bare_dotfile_name_is_not_a_term(tmp_path: Path, home: Path) -> None:
    inst = _inst(
        tmp_path,
        verify={
            "env": {
                "TOKEN": {
                    "from": "env-file",
                    "file": str(home / ".secretdir" / ".env"),
                    "key": "TOKEN",
                }
            }
        },
    )

    terms = terms_for(inst, target=_target(tmp_path))

    assert ".secretdir" in terms
    assert ".env" not in terms
