"""`abk scrub-check`: the terms come from the installation, never the framework."""

import argparse
from pathlib import Path

from agent_build_kit.cli.scrub import cmd_scrub_check, scan, terms_for
from tests.conftest import make_installation


def _inst(tmp_path: Path):
    return make_installation(
        tmp_path / "planning-repo",
        repos={
            "platform": {
                "path": str(tmp_path / "checkouts" / "plat"),
                "slug": "acme/platform",
                "deploy": {
                    "ssh_key": str(tmp_path / "keys" / "deploy_key_x"),
                    "live_written": ["notes"],
                    "rules": [
                        {"prefix": "svc-a/", "run": [["scripts/deploy.sh", "svc-a"]]},
                        {"prefix": "gateway/", "run": [["docker", "compose", "restart", "gw-x"]]},
                        {
                            "prefix": "docker-compose.yml",
                            "run": [["docker", "compose", "up", "-d"]],
                        },
                    ],
                    "credentials": {
                        "names_from": {"file": "scripts/dev-stack.sh", "shell_array": "STACK_CREDS"}
                    },
                },
            }
        },
        verify={"env": {"CONSUMER_KEY_X": {"from": "literal", "value": "v"}}},
    )


def test_terms_come_from_the_installation_s_own_config(tmp_path: Path) -> None:
    terms = terms_for(_inst(tmp_path))

    for expected in (
        "planning-repo", "platform", "acme", "plat", "svc-a", "gw-x",
        "notes", "deploy_key_x", "CONSUMER_KEY_X",
    ):  # fmt: skip
        assert expected in terms, expected
    # a credential array's name is a convention, not an identity
    assert "STACK_CREDS" not in terms
    # generic deploy words and paths are not installation facts
    for generic in (
        "docker",
        "compose",
        "restart",
        "up",
        "-d",
        "scripts/deploy.sh",
        "docker-compose.yml",
    ):
        assert generic not in terms, generic


def test_scan_reports_each_hit_with_its_term(tmp_path: Path) -> None:
    target = tmp_path / "framework"
    (target / "src").mkdir(parents=True)
    (target / "src" / "a.py").write_text("# talks to GW-X here\nx = 1\n")
    (target / "src" / "b.md").write_text("nothing here\n")
    (target / ".venv").mkdir()
    (target / ".venv" / "c.py").write_text("svc-a\n")  # ignored: dependency dir

    hits = scan(target, terms_for(_inst(tmp_path)))

    assert hits == ["src/a.py:1: GW-X"]


def test_the_command_fails_on_a_hit_and_passes_clean(tmp_path: Path, capsys) -> None:
    inst = _inst(tmp_path)
    target = tmp_path / "framework"
    target.mkdir()
    (target / "x.py").write_text("print('acme')\n")

    assert cmd_scrub_check(argparse.Namespace(target=str(target), show_terms=False), inst) == 1
    assert "x.py:1: acme" in capsys.readouterr().out

    (target / "x.py").write_text("print('hello')\n")
    assert cmd_scrub_check(argparse.Namespace(target=str(target), show_terms=True), inst) == 0
    assert "clean" in capsys.readouterr().out


def test_the_target_may_be_one_of_the_workspace_repos_and_name_itself(tmp_path: Path) -> None:
    # An installation can list the framework checkout as a repo of its own
    # (to build units for it); scanning that checkout must not flag its name.
    inst = make_installation(
        tmp_path / "planning",
        repos={"kit": {"path": str(tmp_path / "kit"), "slug": "acme/build-kit"}},
    )
    (tmp_path / "kit").mkdir()
    (tmp_path / "kit" / "README.md").write_text("# build-kit, by kit\n")

    assert scan(tmp_path / "kit", terms_for(inst, target=tmp_path / "kit")) == []
    assert scan(tmp_path / "kit", terms_for(inst)) != []
