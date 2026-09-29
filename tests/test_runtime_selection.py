"""Which runtime a workspace runs on, and which model names it is sent.

`abk.yaml` names the runtime for the whole workspace (`runtime:`, defaulting
to Claude Code so an existing file needs no edit); `ABK_RUNTIME` overrides it
for one machine or one invocation. A runtime that needs a fact abk cannot
default takes it from its own `runtimes.<name>` entry, and a selection that
cannot work fails when the file is loaded rather than when every unit is held.

Models resolve against the active runtime: the per-machine `ABK_*_MODEL`
overrides, then that runtime's own `runtimes.<name>.models`, then the roles the
flat `models:` block names, then the runtime's own defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config, runtimes
from agent_build_kit.config import ConfigError, ModelsConfig
from agent_build_kit.settings import Settings, reload, settings
from tests.runtimes.selectable import SelectableRuntime, select

FLAT_MODELS = "models:\n  implement: opus\n  rework: opus\n  review: opus\n  rework_review: fable\n"

# A second runtime's names for the same roles, in its own block.
OTHER_MODELS = "runtimes:\n  other:\n    models:\n      review: other-reviewer\n"


def write(root: Path, text: str) -> Path:
    path = root / "abk.yaml"
    path.write_text(text)
    return path


def activate(path: Path) -> config.WorkspaceConfig:
    loaded = config.load(path)
    config.activate(loaded, path.parent)
    return loaded


@pytest.fixture
def other(monkeypatch: pytest.MonkeyPatch) -> SelectableRuntime:
    return select(monkeypatch, SelectableRuntime("other"))


@pytest.fixture
def machine_runtime(monkeypatch: pytest.MonkeyPatch):
    """Sets `ABK_RUNTIME` the way a machine would, and puts the settings back."""

    def set_to(name: str) -> None:
        monkeypatch.setenv("ABK_RUNTIME", name)
        reload(None)

    yield set_to
    monkeypatch.delenv("ABK_RUNTIME", raising=False)
    reload(None)


# --- an existing file ----------------------------------------------------------------


def test_a_file_naming_neither_key_runs_on_claude_code_with_its_own_models(
    tmp_path: Path,
) -> None:
    path = write(tmp_path, "models:\n  implement: sonnet\n  review: haiku\n")

    loaded = activate(path)

    assert loaded.runtime == "claude_code"
    assert loaded.runtimes == {}
    assert runtimes.active().name == "claude_code"
    models = config.models()
    assert (models.implement, models.review) == ("sonnet", "haiku")
    assert (models.rework, models.rework_review) == ("opus", "fable")


def test_a_workspace_on_the_default_never_grows_either_key(tmp_path: Path) -> None:
    loaded = activate(write(tmp_path, f"runtime: claude_code\nruntimes: {{}}\n{FLAT_MODELS}"))

    dumped = config.dump(loaded)

    assert "runtime" not in dumped


# --- per-runtime models -----------------------------------------------------------------


def test_a_runtime_s_own_models_apply_when_it_is_the_active_one(
    tmp_path: Path, other: SelectableRuntime
) -> None:
    activate(write(tmp_path, f"runtime: other\n{FLAT_MODELS}{OTHER_MODELS}"))

    models = config.models()

    assert models.review == "other-reviewer"
    # A role its block does not name keeps the flat block's.
    assert models.implement == "opus"


def test_another_runtime_s_models_are_not_sent_to_the_active_one(
    tmp_path: Path, other: SelectableRuntime
) -> None:
    activate(write(tmp_path, f"runtime: claude_code\n{FLAT_MODELS}{OTHER_MODELS}"))

    assert config.models().review == "opus"


# A runtime's own names for every role, none of them Claude Code's.
OWN_DEFAULTS = ModelsConfig(
    implement="own-builder",
    rework="own-reworker",
    review="own-reviewer",
    rework_review="own-second-look",
)


def test_a_role_nothing_names_falls_back_to_the_active_runtime_s_own_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never to another runtime's: a workspace on a runtime with its own model
    names, and no `models:` block, is sent none of Claude Code's."""
    select(monkeypatch, SelectableRuntime("other", default_models=OWN_DEFAULTS))
    activate(write(tmp_path, "runtime: other\n"))

    models = config.models()

    assert models == OWN_DEFAULTS
    assert not {"opus", "fable"} & set(models.model_dump().values())


def test_a_flat_block_naming_some_roles_leaves_the_rest_to_the_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("other", default_models=OWN_DEFAULTS))
    activate(write(tmp_path, "runtime: other\nmodels:\n  implement: named\n"))

    models = config.models()

    assert models.implement == "named"
    assert (models.rework, models.review, models.rework_review) == (
        "own-reworker",
        "own-reviewer",
        "own-second-look",
    )


def test_claude_code_with_no_models_block_keeps_today_s_names(tmp_path: Path) -> None:
    activate(write(tmp_path, "runtime: claude_code\n"))

    assert config.models() == ModelsConfig(
        implement="opus", rework="opus", review="opus", rework_review="fable"
    )


def test_the_machine_s_model_overrides_still_win(
    tmp_path: Path, other: SelectableRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(write(tmp_path, f"runtime: other\n{FLAT_MODELS}{OTHER_MODELS}"))
    monkeypatch.setattr(settings, "review_model", "this-machine")

    assert config.models().review == "this-machine"


# --- a selection that cannot work --------------------------------------------------------


def test_an_unknown_runtime_fails_at_load_naming_it_and_the_known_ones(tmp_path: Path) -> None:
    path = write(tmp_path, "runtime: nonesuch\n")

    with pytest.raises(ConfigError) as raised:
        config.load(path)

    assert "nonesuch" in str(raised.value)
    assert "claude_code" in str(raised.value)


def test_a_runtime_missing_a_fact_it_requires_fails_at_load_naming_the_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("spawned", requires=("command",)))
    path = write(tmp_path, "runtime: spawned\n")

    with pytest.raises(ConfigError) as raised:
        config.load(path)

    message = str(raised.value)
    assert "spawned" in message
    assert "command" in message


def test_a_runtime_given_the_facts_it_requires_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("spawned", requires=("command",)))
    path = write(
        tmp_path,
        "runtime: spawned\nruntimes:\n  spawned:\n    command: [some-agent, acp]\n"
        "    policy_fix: [scripts/constrain-agent.sh]\n",
    )

    loaded = config.load(path)

    entry = loaded.runtimes["spawned"]
    assert entry.command == ["some-agent", "acp"]
    assert entry.policy_fix == ["scripts/constrain-agent.sh"]


def test_an_entry_for_a_runtime_that_is_not_selected_needs_nothing_it_requires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the selected runtime's facts are demanded: a workspace keeping an
    entry for a runtime it tried out is not made to complete it."""
    select(monkeypatch, SelectableRuntime("spawned", requires=("command",)))
    path = write(tmp_path, "runtimes:\n  spawned:\n    models:\n      review: x\n")

    assert config.load(path).runtime == "claude_code"


# --- the per-machine override -------------------------------------------------------------


def test_the_setting_reads_abk_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABK_RUNTIME", "other")

    assert Settings(_env_file=None).runtime == "other"


def test_the_environment_selects_another_runtime_without_touching_the_file(
    tmp_path: Path, other: SelectableRuntime, machine_runtime
) -> None:
    path = write(tmp_path, f"runtime: claude_code\n{FLAT_MODELS}{OTHER_MODELS}")
    before = path.read_text()
    activate(path)

    machine_runtime("other")

    assert runtimes.active() is other
    assert config.active().runtime == "claude_code"
    assert path.read_text() == before
    # Its models are the overriding runtime's, as if the file had named it.
    assert config.models().review == "other-reviewer"


def test_without_the_override_the_file_s_runtime_is_used(
    tmp_path: Path, other: SelectableRuntime
) -> None:
    activate(write(tmp_path, "runtime: other\n"))

    assert runtimes.active() is other
