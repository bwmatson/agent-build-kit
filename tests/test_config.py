"""The workspace configuration: what `abk.yaml` may say, and what it may not.

The schema refuses at load rather than at the moment a value would have
mattered, so a configuration that cannot be satisfied never reaches a plan.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.config import ConfigError, LimitsConfig, load
from tests.conftest import make_installation


def test_the_ceiling_on_a_unit_defaults_to_a_thousand_lines() -> None:
    """With nothing configured, the default floor still sits under it, and a
    floor raised to meet it is refused — the default is a ceiling, not a
    number nothing reads."""
    assert LimitsConfig().max_unit_lines == 1000

    with pytest.raises(ValidationError):
        LimitsConfig(min_unit_lines=1000)


def test_a_floor_above_the_ceiling_is_refused_naming_both() -> None:
    """No plan could satisfy both, so it fails here rather than producing
    units that miss one or the other."""
    with pytest.raises(ValidationError) as refused:
        LimitsConfig(min_unit_lines=1200, max_unit_lines=800)

    message = str(refused.value)
    assert "min_unit_lines" in message and "1200" in message
    assert "max_unit_lines" in message and "800" in message


def test_a_floor_equal_to_the_ceiling_is_refused() -> None:
    """The ceiling must exceed the floor: at equality every unit would have to
    land on exactly one number."""
    with pytest.raises(ValidationError) as refused:
        LimitsConfig(min_unit_lines=700, max_unit_lines=700)

    assert "min_unit_lines" in str(refused.value)


def test_abk_yaml_with_the_floor_above_the_ceiling_fails_to_load(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("limits:\n  min_unit_lines: 1500\n  max_unit_lines: 900\n")

    with pytest.raises(ConfigError) as refused:
        load(path)

    message = str(refused.value)
    assert "1500" in message and "900" in message
    assert "min_unit_lines" in message


def test_a_repo_on_an_unknown_forge_fails_at_load_naming_it_and_the_known_ones(
    tmp_path: Path,
) -> None:
    """The same rule the runtime selection follows: a host abk cannot reach
    fails here, rather than every unit in that repo being held with the
    failure named once per tick."""
    path = tmp_path / "abk.yaml"
    path.write_text("repos:\n  app:\n    path: app\n    slug: example/app\n    forge: nonesuch\n")

    with pytest.raises(ConfigError) as refused:
        load(path)

    message = str(refused.value)
    assert "nonesuch" in message
    assert "github" in message, "the known forges are named, as for a runtime"
    assert "app" in message, "and which repo asked for it"


def test_a_repo_on_a_known_forge_loads(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("repos:\n  app:\n    path: app\n    slug: example/app\n    forge: github\n")

    assert load(path).repos["app"].forge == "github"


def test_a_repo_on_a_forge_without_the_facts_it_needs_fails_at_load(tmp_path: Path) -> None:
    """The same rule a runtime selection follows: an identity abk cannot build
    fails here, naming the keys that are missing, rather than every call
    against that repo failing later with an empty organisation."""
    path = tmp_path / "abk.yaml"
    path.write_text("repos:\n  app:\n    path: app\n    forge: azure_devops\n")

    with pytest.raises(ConfigError) as refused:
        load(path)

    message = str(refused.value)
    assert "azure_devops.org" in message
    assert "azure_devops.project" in message
    assert "repos.app" in message


def test_a_github_repo_without_a_slug_fails_at_load(tmp_path: Path) -> None:
    """`slug` stopped being required when a second host arrived, so what makes
    it required for GitHub is the forge saying it needs it."""
    path = tmp_path / "abk.yaml"
    path.write_text("repos:\n  app:\n    path: app\n")

    with pytest.raises(ConfigError, match="repos.app.slug"):
        load(path)


def test_an_azure_repo_with_its_block_loads(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(
        "repos:\n  app:\n    path: app\n    forge: azure_devops\n"
        "    azure_devops:\n      org: acme\n      project: Some Project\n      repo: Some Repo\n"
    )

    loaded = load(path)

    assert loaded.repos["app"].azure_devops.project == "Some Project"


def test_the_adapt_rounds_must_allow_at_least_one_answer() -> None:
    with pytest.raises(ValidationError):
        LimitsConfig(max_adapt_rounds=0)


def test_the_old_depth_cap_name_fails_to_load_naming_the_new_one(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("limits:\n  stack_depth_cap: 3\n")

    with pytest.raises(ConfigError) as refused:
        load(path)

    message = str(refused.value)
    assert "stack_depth_cap" in message
    assert "stack_depth_build_cap" in message


def test_the_old_depth_cap_name_is_refused_by_the_schema() -> None:
    with pytest.raises(ValidationError) as refused:
        LimitsConfig.model_validate({"stack_depth_cap": 3})

    assert "stack_depth_build_cap" in str(refused.value)


def test_the_build_cap_keeps_the_depth_cap_s_default() -> None:
    assert LimitsConfig().stack_depth_build_cap == 3


@pytest.mark.parametrize("build", [1, 3, 7])
def test_an_unset_rebase_cap_resolves_to_the_build_cap(tmp_path: Path, build: int) -> None:
    inst = make_installation(tmp_path, limits={"stack_depth_build_cap": build})

    assert inst.stack_depth_build_cap == build
    assert inst.stack_depth_rebase_cap == build


def test_an_unset_rebase_cap_follows_the_default_build_cap(tmp_path: Path) -> None:
    inst = make_installation(tmp_path)

    assert inst.stack_depth_rebase_cap == inst.stack_depth_build_cap == 3


@pytest.mark.parametrize(("build", "rebase"), [(5, 2), (2, 5)])
def test_the_two_caps_are_read_independently(tmp_path: Path, build: int, rebase: int) -> None:
    inst = make_installation(
        tmp_path, limits={"stack_depth_build_cap": build, "stack_depth_rebase_cap": rebase}
    )

    assert inst.stack_depth_build_cap == build
    assert inst.stack_depth_rebase_cap == rebase


def test_the_limit_on_units_in_progress_defaults_to_five() -> None:
    assert LimitsConfig().max_units_in_progress == 5


def test_the_limit_on_units_in_progress_must_be_at_least_one() -> None:
    assert LimitsConfig.model_validate({"max_units_in_progress": 1}).max_units_in_progress == 1

    for refused in (0, -1):
        with pytest.raises(ValidationError) as error:
            LimitsConfig.model_validate({"max_units_in_progress": refused})
        assert "max_units_in_progress" in str(error.value)


def test_the_open_pr_ceiling_is_no_longer_accepted() -> None:
    with pytest.raises(ValidationError) as error:
        LimitsConfig.model_validate({"max_open_prs": 5})
    assert "max_open_prs" in str(error.value)


def test_the_installation_reads_the_limit_on_units_in_progress(tmp_path: Path) -> None:
    assert make_installation(tmp_path / "default").max_units_in_progress == 5
    inst = make_installation(tmp_path / "set", limits={"max_units_in_progress": 2})
    assert inst.max_units_in_progress == 2
