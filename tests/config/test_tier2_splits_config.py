"""`tests.tier2_splits`, at the top of the file and per repo (spec: tier2-splits)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit.cli import main
from agent_build_kit.config import Tier2Split, WorkspaceConfig, dump, tier2_splits

TWO = {"claude_code": {"marker": "runtime_claude_code"}, "acp": {"marker": "runtime_acp"}}


def config(splits: dict[str, Any] | None = None, *, own: dict[str, Any] | None = None) -> Any:
    app: dict[str, Any] = {"path": "/work/app", "slug": "example/app"}
    if own is not None:
        app["tests"] = {"tier2_splits": own}
    return WorkspaceConfig.model_validate(
        {
            "tests": {} if splits is None else {"tier2_splits": splits},
            "repos": {
                "app": app,
                "platform": {"path": "/work/platform", "slug": "example/platform"},
            },
        }
    )


def names(loaded: Any, repo: str = "app") -> list[str]:
    return [split.name for split in tier2_splits(loaded.repos[repo], loaded)]


def test_nothing_declared_gives_rest_alone() -> None:
    loaded = config()

    assert loaded.tests.tier2_splits == {}
    assert tier2_splits(loaded.repos["app"], loaded) == (Tier2Split(name="rest"),)


def test_two_splits_are_given_in_declaration_order_then_rest_with_their_markers() -> None:
    loaded = config(TWO)

    assert tier2_splits(loaded.repos["app"], loaded) == (
        Tier2Split(name="claude_code", marker="runtime_claude_code"),
        Tier2Split(name="acp", marker="runtime_acp"),
        Tier2Split(name="rest"),
    )


def test_config_show_prints_both_splits(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(dump(config(TWO)))

    assert main(["--config", str(path), "config", "--show"]) == 0

    shown = yaml.safe_load(capsys.readouterr().out)
    # `--show` prints defaults too, so each entry carries its unset `hold` and `gate`.
    assert shown["tests"]["e2e_splits"] == {
        name: {**entry, "hold": None, "gate": None} for name, entry in TWO.items()
    }
    assert names(config(TWO)) == ["claude_code", "acp", "rest"]


@pytest.mark.parametrize(
    ("splits", "value"),
    [
        ({"gpu": {}}, "gpu"),
        ({"gpu": {"marker": ""}}, "gpu"),
        ({"Bad-Name": {"marker": "m"}}, "Bad-Name"),
        ({"two words": {"marker": "m"}}, "two words"),
        ({"rest": {"marker": "m"}}, "rest"),
        ({"a": {"marker": "same"}, "b": {"marker": "same"}}, "same"),
    ],
    ids=["no-marker", "empty-marker", "bad-name", "space", "rest-marker", "twice"],
)
def test_a_bad_split_is_refused_naming_the_setting_and_the_value(
    splits: dict[str, Any], value: str
) -> None:
    with pytest.raises(ValidationError) as refused:
        config(splits)
    with pytest.raises(ValidationError) as refused_own:
        config(own=splits)

    assert "tests.tier2_splits" in str(refused.value)
    assert value in str(refused.value)
    assert "repos.app.tests.tier2_splits" in str(refused_own.value)


def test_an_unknown_key_is_refused_though_the_split_without_it_loads() -> None:
    loaded = config({"gpu": {"marker": "gpu"}})
    assert names(loaded) == ["gpu", "rest"]

    with pytest.raises(ValidationError, match="gate"):
        config({"gpu": {"marker": "gpu", "gate": True}})


@pytest.mark.parametrize("hold", [True, False])
def test_hold_accepts_true_and_false(hold: bool) -> None:
    loaded = config({"gpu": {"marker": "gpu", "hold": hold}})

    assert tier2_splits(loaded.repos["app"], loaded)[0].hold is hold


def test_hold_is_unset_when_absent() -> None:
    loaded = config({"gpu": {"marker": "gpu"}})

    assert [split.hold for split in tier2_splits(loaded.repos["app"], loaded)] == [None, None]


def test_rest_may_carry_a_hold() -> None:
    loaded = config({"gpu": {"marker": "gpu"}, "rest": {"hold": True}})

    assert tier2_splits(loaded.repos["app"], loaded) == (
        Tier2Split(name="gpu", marker="gpu"),
        Tier2Split(name="rest", hold=True),
    )


def test_a_rest_entry_with_no_hold_is_refused_as_empty() -> None:
    with pytest.raises(ValidationError, match="rest"):
        config({"rest": {}})


def test_a_repos_own_splits_replace_the_top_level_map() -> None:
    loaded = config({"acp": {"marker": "runtime_acp"}}, own={"gpu": {"marker": "gpu"}})

    assert names(loaded) == ["gpu", "rest"]
    assert names(loaded, "platform") == ["acp", "rest"]


def test_an_empty_own_map_is_set_and_leaves_rest_alone() -> None:
    loaded = config(TWO, own={})

    assert names(loaded) == ["rest"]
