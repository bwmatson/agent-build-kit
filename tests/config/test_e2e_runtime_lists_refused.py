"""The runtime lists `tests.<old e2e list>`, `tests.runtimes_blocked` and
`tests.runtimes_allowed` are gone, each refused naming what replaces it (spec: e2e-splits)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import WorkspaceConfig, dump

APP: dict[str, Any] = {"path": "/work/app", "slug": "example/app"}
# The refused key keeps the old test-kind spelling: it is what an installation still has.
OLD_RUNTIMES = "tier" + "2_runtimes"
REPLACED_BY_HOLD = "tests.e2e_splits.<name>.hold"
SPLIT = {"acp": {"marker": "runtime_acp"}}


def load(*, tests: dict[str, Any] | None = None, own: dict[str, Any] | None = None) -> Any:
    repo = {**APP, **({} if own is None else {"tests": own})}
    return WorkspaceConfig.model_validate({"tests": tests or {}, "repos": {"app": repo}})


@pytest.mark.parametrize("setting", ["runtimes_blocked", "runtimes_allowed"])
def test_a_hold_list_is_refused_naming_the_hold_setting(setting: str) -> None:
    with pytest.raises(ValidationError) as refused:
        load(tests={setting: ["acp"]})

    text = str(refused.value)
    assert f"tests.{setting}" in text
    assert REPLACED_BY_HOLD in text


def test_the_top_level_runtime_list_is_refused_naming_a_declared_split() -> None:
    with pytest.raises(ValidationError) as refused:
        load(tests={OLD_RUNTIMES: ["acp"]})

    text = str(refused.value)
    assert f"tests.{OLD_RUNTIMES}" in text
    assert "tests.e2e_splits" in text


def test_a_repos_own_runtime_list_is_refused_naming_a_declared_split() -> None:
    with pytest.raises(ValidationError) as refused:
        load(own={OLD_RUNTIMES: ["acp"]})

    text = str(refused.value)
    assert f"repos.app.tests.{OLD_RUNTIMES}" in text
    assert "tests.e2e_splits" in text


@pytest.mark.parametrize("repo_level", [False, True], ids=["top-level", "repo"])
def test_a_split_named_base_is_refused_as_the_older_name_of_rest(repo_level: bool) -> None:
    base = {"base": {"marker": "runtime_base"}}
    setting = "repos.app.tests.e2e_splits" if repo_level else "tests.e2e_splits"

    with pytest.raises(ValidationError) as refused:
        if repo_level:
            load(own={"e2e_splits": base})
        else:
            load(tests={"e2e_splits": base})

    text = str(refused.value)
    assert setting in text
    assert "base" in text
    assert "rest" in text


def test_config_show_no_longer_prints_the_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(dump(load(tests={"e2e_splits": SPLIT})))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    assert {OLD_RUNTIMES, "runtimes_blocked", "runtimes_allowed"}.isdisjoint(shown["tests"])
    assert OLD_RUNTIMES not in shown["repos"]["app"]["tests"]
