"""Post-merge verification takes the tier 2 selection, leaves the held splits out and waits for
a held split that holds a live test among the change's files (spec: tier2-runtime-parking)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import SOURCE_COMMAND, remove_hold, write_hold
from agent_build_kit.pipeline.verify import VerifyRecord, verify_change
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.pipeline.test_verify import Host

LIVE = "svc-a/tests/integration/test_drive_live_stack.py"
OTHER_LIVE = "svc-b/tests/integration/test_other_live_stack.py"
ACP_TEST = f"{LIVE}::test_acp_scenario"
PLAIN_TEST = f"{LIVE}::test_plain_scenario"
PLAIN = "local_stack and not dev_stack"

# What the change merged: a service change to deploy, and the live test beside it.
FILES = {
    ("platform", 30): ["svc-a/src/mcp.py", LIVE],
    ("app", 31): [OTHER_LIVE],
}


class Listing(Host):
    """A host whose pytest lists `acp_tests` for a selection that asks for the `runtime_acp`
    tests and the untagged ones for any other, in pytest's own `--collect-only -q` shape."""

    def __init__(self, *, acp_tests: tuple[str, ...] = (ACP_TEST,), **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.acp_tests = acp_tests

    def __call__(self, command, *, cwd, env=None, **kwargs):
        done = super().__call__(command, cwd=cwd, env=env, **kwargs)
        if "--collect-only" not in command:
            return done
        expression = command[command.index("-m") + 1]
        asks_for_acp = "runtime_acp" in expression and "not runtime_acp" not in expression
        found = self.acp_tests if asks_for_acp else (PLAIN_TEST,)
        listing = "".join(f"{test}\n" for test in found)
        count = f"\n{len(found)} tests collected in 0.01s\n"
        return subprocess.CompletedProcess(command, 0 if found else 5, listing + count, "")

    def lists(self) -> list[tuple[str, ...]]:
        return [command for _, command, _ in self.calls if "--collect-only" in command]

    def started(self) -> list[tuple[str, ...]]:
        """Everything that changed or ran something: not a git read and not a listing."""
        reads = (("git", "status"), ("git", "rev-parse"))
        return [
            command
            for _, command, _ in self.calls
            if "--collect-only" not in command and command[:2] not in reads
        ]

    def pytest_runs(self) -> list[tuple[str, ...]]:
        return [c for _, c, _ in self.calls if "pytest" in c and "--collect-only" not in c]


def expression_of(command: tuple[str, ...]) -> str:
    return command[command.index("-m") + 1]


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    """`platform` declares the splits `acp` and `claude_code` and has a service with a deploy
    rule and a live test; `app` declares none and has a live test of its own."""
    installation = make_installation(
        tmp_path,
        repos={
            "platform": {
                "path": str(tmp_path / "checkouts" / "platform"),
                "slug": "example/platform",
                "deploy": {
                    "rules": [{"prefix": "svc-a/", "run": [["scripts/deploy.sh", "svc-a"]]}]
                },
                "tests": {
                    "e2e_splits": {
                        "acp": {"marker": "runtime_acp"},
                        "claude_code": {"marker": "runtime_claude_code"},
                    }
                },
            },
            "app": {
                "path": str(tmp_path / "checkouts" / "app"),
                "slug": "example/app",
                "tests": {"e2e_splits": {}},
            },
        },
    )
    for repo, member, live in (("platform", "svc-a", LIVE), ("app", "svc-b", OTHER_LIVE)):
        checkout = tmp_path / "checkouts" / repo
        (checkout / member).mkdir(parents=True)
        (checkout / member / "pyproject.toml").write_text(f'[project]\nname = "{member}"\n')
        (checkout / live).parent.mkdir(parents=True)
        (checkout / live).touch()
    (tmp_path / "checkouts" / "platform" / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["svc-a"]\n'
    )
    (tmp_path / "checkouts" / "app" / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["svc-b"]\n'
    )
    installation.state_dir.mkdir(parents=True, exist_ok=True)
    return installation


def hold_acp(inst: Installation) -> None:
    write_hold(
        inst.state_dir,
        "acp",
        reason="no usage window left",
        source=SOURCE_COMMAND,
        by="test",
        now=datetime.now(UTC),
    )


def units(*repos: str) -> list:
    numbers = {"platform": 30, "app": 31}
    return [
        stored_unit(f"c/{n}", change="c", repo=repo, state="merged", pr=numbers[repo])
        for n, repo in enumerate(repos, start=1)
    ]


def verify(host: Host, inst: Installation, *repos: str):
    return verify_change(
        "c",
        units(*repos),
        installation=inst,
        pr_files=lambda repo, pr: FILES[(repo, pr)],
        run=host,
        env={},
    )


def ready(host: Host, inst: Installation, *repos: str):
    """The round's own step: verifies the change that is ready and says whether it may archive."""
    return cli.verify_ready(
        inst,
        units(*repos),
        verify=lambda change, merged: verify_change(
            change,
            merged,
            installation=inst,
            pr_files=lambda repo, pr: FILES[(repo, pr)],
            run=host,
            env={},
        ),
    )


def test_the_commands_of_the_verification_leave_the_held_splits_out(inst: Installation) -> None:
    unheld = Listing()
    assert verify(unheld, inst, "platform").passed
    [before] = unheld.pytest_runs()
    assert expression_of(before) == PLAIN, "the commands it gave before"

    hold_acp(inst)
    held = Listing(acp_tests=())
    result = verify(held, inst, "platform")

    assert result.passed, result.detail
    [after] = held.pytest_runs()
    assert expression_of(after) == f"{PLAIN} and not runtime_acp"
    swapped = tuple(expression_of(after) if word == PLAIN else word for word in before)
    assert after == swapped, "nothing but the selection differs"


def test_a_repo_with_no_declared_split_is_verified_as_before_beside_one_that_has_them(
    inst: Installation,
) -> None:
    hold_acp(inst)
    host = Listing(acp_tests=())

    result = verify(host, inst, "platform", "app")

    assert result.passed, result.detail
    by_where = {
        where: expression_of(command)
        for where, command, _ in host.calls
        if "-m" in command and "--collect-only" not in command
    }
    assert by_where["app"] == PLAIN, "the repo without a split is not narrowed"
    assert by_where["platform"] == f"{PLAIN} and not runtime_acp"
    assert not [c for c in host.lists() if "svc-b" in " ".join(c)], "and nothing is listed for it"


def test_a_held_split_holding_a_live_test_among_the_files_skips_the_verification(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    hold_acp(inst)
    host = Listing()

    may_archive = ready(host, inst, "platform")

    assert host.lists(), "the listing is asked before anything is deployed"
    assert host.started() == [], "nothing deployed, pulled or run"
    assert VerifyRecord(inst.state_dir / "verified.json").get("c") is None, "nothing recorded"
    said = [line for line in capsys.readouterr().out.splitlines() if "skipped" in line]
    assert any("acp" in line for line in said), "logged as skipped for the split"
    assert not may_archive("c"), "not archived meanwhile"


def test_a_skipped_verification_is_tried_again_the_next_round_and_runs_once_released(
    inst: Installation,
) -> None:
    hold_acp(inst)
    host = Listing()
    assert not ready(host, inst, "platform")("c")
    assert not ready(host, inst, "platform")("c"), "tried again, still held"
    assert host.started() == []

    assert remove_hold(inst.state_dir, "acp")
    may_archive = ready(host, inst, "platform")

    record = VerifyRecord(inst.state_dir / "verified.json").get("c")
    assert record is not None and record.passed, "run and recorded as before"
    assert ("platform", ("scripts/deploy.sh", "svc-a")) in host.ran()
    assert may_archive("c")
    [run] = host.pytest_runs()
    assert "runtime_acp" not in expression_of(run), "and with the split in the selection"


def test_a_held_split_with_no_test_among_the_files_does_not_delay_the_verification(
    inst: Installation,
) -> None:
    hold_acp(inst)
    host = Listing(acp_tests=())

    may_archive = ready(host, inst, "platform")

    record = VerifyRecord(inst.state_dir / "verified.json").get("c")
    assert record is not None and record.passed
    assert may_archive("c")
    assert ("platform", ("scripts/deploy.sh", "svc-a")) in host.ran()
    [run] = host.pytest_runs()
    assert expression_of(run) == f"{PLAIN} and not runtime_acp"


@pytest.mark.usefixtures("inst")
def test_a_repo_whose_own_split_is_not_held_is_verified_although_another_repo_holds_the_name(
    tmp_path: Path,
) -> None:
    """`platform` sets `hold: true` on `acp` and `app` declares it without one: the split is
    held for `platform` alone, so `app`'s verification is not skipped and leaves nothing out."""
    acp = {"marker": "runtime_acp"}
    inst = make_installation(
        tmp_path,
        repos={
            "platform": {
                "path": str(tmp_path / "checkouts" / "platform"),
                "slug": "example/platform",
                "tests": {"e2e_splits": {"acp": {**acp, "hold": True}}},
            },
            "app": {
                "path": str(tmp_path / "checkouts" / "app"),
                "slug": "example/app",
                "tests": {"e2e_splits": {"acp": acp}},
            },
        },
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host = Listing(acp_tests=(f"{OTHER_LIVE}::test_acp",))

    result = verify(host, inst, "app")

    assert result.passed, result.detail
    [run] = host.pytest_runs()
    assert expression_of(run) == PLAIN, "acp runs for app"
