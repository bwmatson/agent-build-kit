"""`abk e2e-test check` warns about a group declared in one e2e-test split whose own tests are in
another, and exits as it would without the warning (spec: split-start-gate)."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_build_kit.cli import e2e_cmd
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.e2e_check_support import ACP, BASE, CLAUDE, CLEAN, Pytest, installation
from tests.factories import git, init_repo, stored_unit


class Lookup:
    """The own-test lookup: the tests each unit's groups add, as the real lookup gives them
    (file-qualified ids from the checkout's root, with no parameter id), and the units it was
    asked about. A started unit declared `rest` found at e2e-test to hold `acp` tests parks for
    `acp` as before: tests/pipeline/test_e2e_split_groups.py pins that backstop."""

    def __init__(self, tests: dict[str, Sequence[str]]) -> None:
        self.tests = tests
        self.asked: list[str] = []

    def __call__(self, inst: Installation, unit: StoredUnit) -> Sequence[str]:
        self.asked.append(unit.id)
        return self.tests.get(unit.id, ())


def check(
    inst: Installation, capsys: pytest.CaptureFixture[str], lookup: Lookup, run: Pytest
) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = e2e_cmd.cmd_e2e_check(argparse.Namespace(repo="app"), inst, run=run, own_tests=lookup)
    shown = capsys.readouterr()
    return code, (shown.out + shown.err).splitlines()


def plan(inst: Installation, *units: StoredUnit) -> None:
    UnitStore(inst.state_dir / "units.json").upsert(list(units))


def test_a_group_declared_rest_with_an_own_test_in_acp_is_warned_about(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    plan(inst, stored_unit("feature/1", change="feature", split="rest", groups=(3,)))

    code, lines = check(inst, capsys, Lookup({"feature/1": [ACP]}), Pytest(CLEAN))

    [warning] = [line for line in lines if "feature" in line and "warn" in line.lower()]
    assert "3" in warning and "rest" in warning and "acp" in warning
    assert code == 0, "a warning does not fail the check"


def test_the_exit_status_is_the_one_it_would_be_without_the_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    overlap = Pytest({**CLEAN, "local_stack and runtime_claude_code": [CLAUDE, ACP]})
    inst = installation(tmp_path)
    plan(inst, stored_unit("feature/1", change="feature", split="rest", groups=(3,)))
    without = check(inst, capsys, Lookup({}), overlap)[0]

    with_warning = check(inst, capsys, Lookup({"feature/1": [ACP]}), overlap)

    assert without == with_warning[0] == 1
    assert any("warn" in line.lower() and "acp" in line for line in with_warning[1])


def test_a_group_in_the_split_of_its_own_tests_and_a_unit_without_tests_print_nothing_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    plan(
        inst,
        stored_unit("agree/1", change="agree", split="acp", groups=(1,)),
        stored_unit("bare/1", change="bare", split="rest", groups=(2,)),
        stored_unit("wrong/1", change="wrong", split="rest", groups=(4,)),
    )
    lookup = Lookup({"agree/1": [ACP], "wrong/1": [ACP]})

    code, lines = check(inst, capsys, lookup, Pytest(CLEAN))

    warnings = [line for line in lines if "warn" in line.lower()]
    assert code == 0
    assert len(warnings) == 1 and "wrong" in warnings[0]
    assert not any("agree" in line or "bare" in line for line in warnings)


def commit_test(app: Path, name: str, source: str) -> None:
    (app / "tests" / "integration" / name).write_text(source)
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", f"add {name}")


def test_the_default_lookup_names_only_the_tests_the_branch_added_since_it_forked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    app = init_repo(tmp_path / "app")
    (app / ".gitignore").write_text("__pycache__/\n")
    git(app, "add", "-A")
    git(app, "commit", "-q", "-m", "start")
    git(app, "checkout", "-q", "-b", "spec/feature/1")
    commit_test(
        app,
        "test_own.py",
        "import pytest\n\n\n@pytest.mark.parametrize('v', ['a', 'b'])\ndef test_own_acp(v):\n"
        "    pass\n\n\ndef test_own_plain():\n    pass\n",
    )
    git(app, "checkout", "-q", "main")
    commit_test(app, "test_later.py", "def test_main_acp():\n    pass\n")
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("feature/1", change="feature", split="rest", groups=(3,))])
    store.set_state("feature/1", PLANNED, branch="spec/feature/1")
    own = "tests/integration/test_own.py"
    listings = {
        f"{BASE} and runtime_acp": [
            f"{own}::test_own_acp[a]",
            f"{own}::test_own_acp[b]",
            "tests/integration/test_later.py::test_main_acp",
        ],
        f"{BASE} and runtime_claude_code": [CLAUDE],
        f"{BASE} and not runtime_acp and not runtime_claude_code": [f"{own}::test_own_plain"],
    }
    capsys.readouterr()

    code = e2e_cmd.cmd_e2e_check(argparse.Namespace(repo="app"), inst, run=Pytest(listings))

    lines = capsys.readouterr().out.splitlines()
    [warning] = [line for line in lines if "warning" in line]
    assert code == 0
    assert "feature group 3" in warning and "test_own_acp" in warning
    assert "rest" in warning and "acp" in warning
