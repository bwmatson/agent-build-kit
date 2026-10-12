"""One abk.yaml fragment by every route (typed answers, `--set`, `--runtime-config`), an
unknown key refused by name, nothing written until confirmed, and `--dry-run`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.cli import main
from tests.cli.init_choice_fakes import (
    Answers,
    Listing,
    ModelAnswers,
    Offering,
    answering,
    machine,
)
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.factories import recognised_planning

ANSWERED = ("runtime", "runtimes", "models")
FRAGMENT = {
    "runtime": "alpha",
    "runtimes": {"alpha": {"command": ["alpha-bin", "serve"]}},
    "models": {"review": "a-2"},
}


@pytest.fixture
def events() -> list[str]:
    return []


@pytest.fixture(autouse=True)
def alpha(
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    stubs: None,  # noqa: F811 — fixture: the machine is faked after the stubs' own
) -> Listing:
    runtime = Listing("alpha", models=("a-1", "a-2", "a-3"), events=events)
    machine(monkeypatch, ("alpha-bin",), runtime, events=events)
    return runtime


def planning_in(tmp_path: Path, name: str) -> Path:
    return recognised_planning(tmp_path / name)


def answered(planning: Path) -> dict[str, Any]:
    raw = yaml.safe_load((planning / "abk.yaml").read_text())
    return {key: raw[key] for key in ANSWERED if key in raw}


def snapshot(*roots: Path) -> dict[str, bytes]:
    """Every file under `roots` but git's own, with its bytes."""
    return {
        str(path): path.read_bytes()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def test_typed_answers_set_and_a_runtime_config_file_write_the_same_fragment(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    typed = planning_in(tmp_path, "typed")
    answering(monkeypatch, ModelAnswers("", "alpha-bin serve", per_role={"review": "a-2"}))
    assert main(init_args(typed, app)) == 0

    flagged = planning_in(tmp_path, "flagged")
    set_flags = ["--set", "runtimes.alpha.command=alpha-bin serve", "--set", "models.review=a-2"]
    assert main(init_args(flagged, app, "--yes", "--runtime", "alpha", *set_flags)) == 0

    filed = planning_in(tmp_path, "filed")
    fragment = tmp_path / "fragment.yaml"
    fragment.write_text(yaml.safe_dump(FRAGMENT))
    assert main(init_args(filed, app, "--yes", "--runtime-config", str(fragment))) == 0

    assert answered(typed)["models"] == {"review": "a-2"}
    assert answered(typed) == answered(flagged) == answered(filed)
    assert answered(filed)["runtimes"]["alpha"]["command"] == ["alpha-bin", "serve"]


@pytest.mark.parametrize(
    ("flag", "value", "named"),
    [
        ("--set", "nonsense=1", "nonsense"),
        ("--set", "models.nonsense=x", "nonsense"),
        ("--runtime-config", "bogus: 1\n", "bogus"),
        ("--runtime-config", "models:\n  nope: x\n", "nope"),
    ],
    ids=["set top level", "set nested", "file top level", "file nested"],
)
def test_an_unknown_key_fails_naming_it_and_writes_nothing(
    flag: str,
    value: str,
    named: str,
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    planning = planning_in(tmp_path, "planning")
    before = snapshot(planning, app)
    if flag == "--runtime-config":
        path = tmp_path / "fragment.yaml"
        path.write_text(value)
        value = str(path)

    code = main(init_args(planning, app, "--yes", "--runtime", "alpha", flag, value))

    out = capsys.readouterr()
    assert code == 2
    assert named in out.out + out.err
    assert snapshot(planning, app) == before


def test_declining_at_the_confirmation_writes_and_changes_no_file(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    planning = planning_in(tmp_path, "planning")
    before = snapshot(planning, app)
    answering(monkeypatch, Answers(by_keyword={"proceed": "n"}))

    main(init_args(planning, app))

    assert "runtime: alpha" in capsys.readouterr().out  # the fragment was shown first
    assert snapshot(planning, app) == before


def test_declining_the_confirmation_leaves_a_kept_file_as_it_was(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    machine(
        monkeypatch,
        ("alpha-bin", "beta-bin"),
        Listing("alpha", models=("a-1",), events=events),
        Offering("beta", events=events),
        events=events,
    )
    planning = planning_in(tmp_path, "planning")
    assert main(init_args(planning, app, "--yes", "--runtime", "alpha")) == 0
    before = snapshot(planning, app)
    answering(monkeypatch, Answers(by_keyword={"instead": "y", "proceed": "n"}))

    main(init_args(planning, app, "--runtime", "beta"))

    assert snapshot(planning, app) == before


def test_a_dry_run_prints_the_fragment_the_answers_make_and_writes_nothing(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    planning = planning_in(tmp_path, "planning")
    before = snapshot(planning, app)
    flags = ["--yes", "--dry-run", "--runtime", "alpha", "--set", "models.review=a-2"]

    code = main(init_args(planning, app, *flags))

    out = capsys.readouterr().out
    assert code == 0
    assert "runtime: alpha" in out
    assert "review: a-2" in out
    assert snapshot(planning, app) == before


def test_an_unknown_key_is_refused_even_when_a_kept_file_leaves_its_runtime_alone(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    planning = planning_in(tmp_path, "planning")
    assert main(init_args(planning, app, "--yes")) == 0
    before = snapshot(planning, app)

    code = main(init_args(planning, app, "--yes", "--set", "nonsense=1"))

    out = capsys.readouterr()
    assert code == 2
    assert "nonsense" in out.out + out.err
    assert snapshot(planning, app) == before
