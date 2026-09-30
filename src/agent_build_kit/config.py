"""The workspace configuration: `abk.yaml` in the planning repo.

Everything that describes one installation — which repos, where they are
checked out, who owns them on GitHub, how each one deploys, what the planner
should know about how they relate — lives in this file and nowhere in the
framework. The schema is strict (`extra="forbid"`): a misspelled key fails at
load, not silently at the moment it would have mattered.

Two ways to reach it:

- `Installation` (installation.py) loads it and derives paths from it; the
  CLI and the runner take that object.
- `active()` returns the loaded config for the leaf modules that need a
  scalar from it (the branch prefix, a limit, a model name) without every
  function in between having to carry it. It is set once, by
  `Installation.activate()`, and defaults to an empty workspace so the
  library is usable — and testable — without a file on disk.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from agent_build_kit import forges, runtimes
from agent_build_kit.model import Frozen

CONFIG_FILENAME = "abk.yaml"
CONFIG_ENV = "ABK_CONFIG"


class ConfigError(Exception):
    """abk.yaml is missing, unreadable or does not match the schema."""


# --- planning repo -----------------------------------------------------------


class PlanningConfig(Frozen):
    # Relative to the planning root unless absolute.
    state_dir: str = "runs"
    specs_dir: str = "openspec"
    graph_page: str = "docs/unit_graph.md"
    # Where per-unit worktrees are checked out. Never inside the planning root:
    # an agent reached a sibling unit's worktree through `--add-dir` when they
    # were, and a type checker resolved a code repo's imports against the
    # planning repo's own source. None = ~/.local/share/<planning dir name>/worktrees.
    worktree_root: Path | None = None
    # The tracks pull the planning repo before running, so their run logs land
    # on the latest main.
    self_pull: bool = True


class OpenSpecConfig(Frozen):
    # The command that runs the OpenSpec CLI, when it is not the default
    # `npx --yes @fission-ai/openspec@<settings.openspec_version>`.
    command: list[str] | None = None


class GithubConfig(Frozen):
    # An ssh host alias (see ~/.ssh/config) carrying the key for the account
    # the pipeline pushes agent branches as. "" means push to `origin`, which
    # authenticates as whoever owns the default key.
    push_host: str = ""
    # Marks a branch and its PR as agent-owned: the poller ignores everything
    # else, and the force-push exception is scoped to this prefix.
    branch_prefix: str = "spec/"


class ModelsConfig(Frozen):
    """Which model runs which part of a unit. Bare aliases, not pinned ids, so
    they track new releases on their own. In abk.yaml's flat `models:` block
    only the roles the file names count: one it leaves out takes the active
    runtime's own `default_models` (`config.models()`), not these defaults."""

    implement: str = "opus"
    rework: str = "opus"
    review: str = "opus"
    # A rework is a small targeted edit and the model that made it is the worst
    # judge of whether it landed, so a different model reviews it.
    rework_review: str = "fable"


class RuntimeModelsConfig(Frozen):
    """One runtime's own names for the roles in `ModelsConfig`. A role left
    out keeps the flat `models:` block's name, or the runtime's default."""

    implement: str | None = None
    rework: str | None = None
    review: str | None = None
    rework_review: str | None = None


class RuntimeConfig(Frozen):
    """What one agent runtime needs from this installation (`runtimes.<name>`)."""

    # The argv that starts the runtime's agent, for a runtime that spawns one.
    command: list[str] | None = None
    # What an operator runs to make the agent refuse what abk forbids, when the
    # runtime's policy check finds a class unenforced. abk only runs it when
    # asked to, and never interprets it.
    policy_fix: list[str] | None = None
    models: RuntimeModelsConfig = RuntimeModelsConfig()


class LimitsConfig(Frozen):
    # Longest chain of in-review PRs from main to a branch.
    stack_depth_cap: int = 3
    # How many units are implemented at once, across all repos.
    max_concurrent_stacks: int = 4
    # Estimated changed lines before a unit stops absorbing the next task group.
    min_unit_lines: int = 500
    # Estimated changed lines one unit may carry. It shapes plans only: a
    # branch is not measured against it, so a unit can still land larger.
    max_unit_lines: int = 1000
    # How many times a unit may be sent back by review before it fails.
    max_review_rounds: int = 3
    # How many times, the first included, the adapt step's test accounting is
    # asked for before the unit fails, when it is incomplete rather than wrong.
    max_adapt_rounds: Annotated[int, Field(ge=1)] = 2
    # Percent of the Claude usage window at which no NEW unit starts, for
    # most of a window. Near the reset this rises — see `usage_ceiling_pct`.
    usage_pause_pct: int = 70
    # The most a window may ever be run to: the threshold at the moment it
    # resets. Quota not used before a reset is lost, and the headroom the
    # pause protects matters less the closer the reset is. Below 100 because
    # credits pay past the plan limit.
    usage_ceiling_pct: Annotated[int, Field(ge=0, lt=100)] = 90
    # The trailing fraction of a window over which the threshold ramps from
    # `usage_pause_pct` to `usage_ceiling_pct`. 0.25 is the last ~75 minutes
    # of a five-hour session, the last ~42 hours of the week.
    usage_relief_fraction: Annotated[float, Field(gt=0, le=1)] = 0.25
    # How much room above the current usage the ramp must offer before a
    # paused pipeline is woken: enough that a unit which starts can finish,
    # rather than being admitted exactly at the margin.
    usage_resume_buffer_pct: Annotated[int, Field(ge=0)] = 5
    # How many times one version of a tasks.md is sent to the planner.
    max_plan_attempts: int = 3

    @model_validator(mode="after")
    def _ceiling_above_pause(self) -> LimitsConfig:
        """A ceiling under the pause percent would make the threshold *fall*
        as a reset approaches, which is the opposite of what it is for."""
        if self.usage_ceiling_pct < self.usage_pause_pct:
            raise ValueError(
                f"usage_ceiling_pct ({self.usage_ceiling_pct}) is below "
                f"usage_pause_pct ({self.usage_pause_pct})"
            )
        return self

    @model_validator(mode="after")
    def _ceiling_above_floor(self) -> LimitsConfig:
        """A floor at or above the ceiling is a unit size no plan can meet."""
        if self.max_unit_lines <= self.min_unit_lines:
            raise ValueError(
                f"max_unit_lines ({self.max_unit_lines}) must exceed "
                f"min_unit_lines ({self.min_unit_lines})"
            )
        return self


class TracksConfig(Frozen):
    """The scheduled health/improve/recommend/implement tracks."""

    # Claude Code's alias, sent as is to whichever runtime is active: not
    # resolved per runtime, so a workspace on another runtime sets it.
    model: str = "sonnet"
    implement_max_prs: int = 3
    # Claude Code's --allowedTools/--disallowedTools syntax; neither list has
    # any effect under the acp runtime.
    allowed_tools: str = (
        "Read Grep Glob Edit Write TodoWrite Agent Skill WebSearch WebFetch "
        "Bash(git *) Bash(uv run *) Bash(pre-commit *) Bash(gh pr *) "
        "Bash(gh repo view*) Bash(docker compose config*)"
    )
    # Every registered forge's way of merging is added to whatever this names
    # (`tracks/runner.py`), so a workspace overriding it cannot drop them.
    disallowed_tools: str = (
        "Bash(git push --force*) Bash(git reset --hard*) Bash(rm -rf*) Bash(git branch -D*)"
    )
    # A directory of prompt files overriding the built-in ones (same names).
    prompts_dir: Path | None = None
    # Where each phase's raw `claude -p` JSON goes, relative to the planning root.
    raw_output_dir: str = ".last-runs"


# --- repos -------------------------------------------------------------------


class TestsConfig(Frozen):
    # Extra packages the repo-root tests (outside every workspace member) need.
    root_extras: list[str] = []
    # The pytest marker on tests that need the real local stack (tier 2).
    tier2_marker: str = "local_stack"
    # The marker on tier-2 tests only the dev stack can run (left out of live checks).
    dev_stack_marker: str = "dev_stack"


class DevStackConfig(Frozen):
    # A script with `up`, `test` and `down` subcommands. Tier 2 runs a unit's
    # branch on it instead of the live stack.
    script: str = "scripts/dev-stack.sh"


class DeployRule(Frozen):
    # A path prefix (a directory with its trailing slash, or a file).
    prefix: str
    # Commands to run from the checkout when a changed path matches; each is
    # an argv list. Empty means "nothing to deploy".
    run: list[list[str]] = []


class NamesFrom(Frozen):
    # A shell script holding an array of credential names: `NAME=(A B C)`.
    file: str
    shell_array: str


class CredentialsConfig(Frozen):
    names_from: NamesFrom | None = None
    # An env file the values are read from, relative to the checkout.
    values_from: str = ".env"


class DeployConfig(Frozen):
    # Image builds that fetch a dependency over SSH need an agent holding the key.
    needs_ssh_agent: bool = False
    ssh_key: Path | None = None
    # Which commands (by their first argv word) run inside that agent.
    agent_for: list[str] = ["scripts/deploy.sh", "scripts/deploy-blue-green.sh"]
    # Paths the running system writes into the checkout, ignored when checking
    # that main is clean before a deploy.
    live_written: list[str] = []
    # First match wins. Test and documentation paths never match (they deploy
    # nothing), and a change inside a library member counts as a change in
    # every member that depends on it — both conventions, not rules.
    rules: list[DeployRule] = []
    credentials: CredentialsConfig | None = None


class ProjectConfig(Frozen):
    """One project inside a repo: where it is, and what it is written in.

    A repo's `profile` is one toolchain for the whole checkout. When the repo
    holds more than one project - a Python service with a web app beneath it -
    this is where each one's own path and toolchain are recorded.
    """

    # Relative to the repo root; `.` when the root itself is the project.
    path: str
    languages: list[str] = []
    profile: str = "python-uv"


class AzureDevOpsConfig(Frozen):
    """Where a repo lives on Azure DevOps, decoded.

    Three separate values rather than one string: the remote percent-encodes a
    project with a space in it, and a project name containing a slash would
    make a re-split of `org/project/repo` ambiguous.
    """

    org: str = ""
    project: str = ""
    repo: str = ""


class RepoConfig(Frozen):
    path: Path
    # GitHub owner/name. The owner decides which `gh` account's token is used.
    # Empty for a repo on a host that names itself some other way.
    slug: str = ""
    default_branch: str = "main"
    # The code host this repo lives on (forges/). Inferred by `abk init` from
    # the origin URL; set it here when the origin does not say.
    forge: str = "github"
    # Where the repo lives, for a forge that does not use `slug`.
    azure_devops: AzureDevOpsConfig = AzureDevOpsConfig()
    # The toolchain profile (profiles/): how to lint, test and read results.
    profile: str = "python-uv"
    languages: list[str] = []
    # Every project found in the checkout, root first.
    projects: list[ProjectConfig] = []
    # One paragraph for prompts and the planning context.
    description: str = ""
    # Repos this one depends on. Drives deploy order (consumed first), which
    # dev stack a unit's own comes up on top of, and the planner's ordering.
    consumes: list[str] = []
    # Prose the planner is given about how this repo relates to the others.
    relationships: str = ""
    tests: TestsConfig = TestsConfig()
    dev_stack: DevStackConfig | None = None
    deploy: DeployConfig = DeployConfig()


# --- verify env providers -----------------------------------------------------


class YamlProvider(Frozen):
    from_: Literal["yaml"] = Field(alias="from")
    file: Path
    # Dotted key path into the document.
    path: str
    # "last-word" takes the last whitespace-separated word ("Bearer x" -> "x").
    take: Literal["last-word"] | None = None
    strip_prefix: str = ""


class EnvFileProvider(Frozen):
    from_: Literal["env-file"] = Field(alias="from")
    file: Path
    key: str


class CommandProvider(Frozen):
    from_: Literal["command"] = Field(alias="from")
    argv: list[str]


class LiteralProvider(Frozen):
    from_: Literal["literal"] = Field(alias="from")
    value: str


Provider = Annotated[
    YamlProvider | EnvFileProvider | CommandProvider | LiteralProvider,
    Field(discriminator="from_"),
]


class VerifyConfig(Frozen):
    # Recorded beside a tier-2 result so a reviewer can see what the stack
    # was. None records nothing.
    stack_versions_command: list[str] | None = [
        "docker",
        "ps",
        "--format",
        "{{.Names}}\t{{.Image}}",
    ]
    # Environment handed to the live-stack tests, each value resolved by a
    # provider at verify time.
    env: dict[str, Provider] = {}


class WorkspaceConfig(Frozen):
    version: int = 1
    planning: PlanningConfig = PlanningConfig()
    openspec: OpenSpecConfig = OpenSpecConfig()
    github: GithubConfig = GithubConfig()
    # The agent runtime (runtimes/) every call runs on; ABK_RUNTIME overrides it.
    runtime: str = runtimes.DEFAULT
    # Per-runtime facts, only the selected runtime's demanded.
    runtimes: dict[str, RuntimeConfig] = {}
    models: ModelsConfig = ModelsConfig()
    limits: LimitsConfig = LimitsConfig()
    tracks: TracksConfig = TracksConfig()
    # Ordered: a task group's `[repo]` tag must be one of these keys.
    repos: dict[str, RepoConfig] = {}
    verify: VerifyConfig = VerifyConfig()


# --- locating and loading ------------------------------------------------------


def locate(explicit: Path | None = None, *, cwd: Path | None = None) -> Path:
    """The abk.yaml in force: `--config`, then `ABK_CONFIG`, then the nearest
    one walking up from the working directory."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    from_env = os.environ.get(CONFIG_ENV)
    if from_env:
        return Path(from_env).expanduser().resolve()
    here = (cwd or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate / CONFIG_FILENAME
    raise ConfigError(
        f"no {CONFIG_FILENAME} found in {here} or above it; pass --config, set "
        f"{CONFIG_ENV}, or run `abk init` to create one"
    )


def load(path: Path) -> WorkspaceConfig:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must hold a mapping at the top level")
    try:
        loaded = WorkspaceConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError(f"{path} does not match the schema:\n{error}") from error
    _check_runtime(loaded, path)
    _check_forges(loaded, path)
    return loaded


def _check_forges(config: WorkspaceConfig, path: Path) -> None:
    """A repo on a host abk has no forge for fails here, not once every unit
    in it is held with the same message per tick."""
    for name, repo in config.repos.items():
        try:
            forge = forges.get(repo.forge)
        except KeyError as error:
            raise ConfigError(f"{path}: repo {name!r}: {error.args[0]}") from None
        missing = [fact for fact in forge.requires if not _reach(repo, fact)]
        if missing:
            raise ConfigError(
                f"{path}: repo {name!r} on {repo.forge} needs "
                + ", ".join(f"repos.{name}.{fact}" for fact in missing)
            )


def _reach(value: object, dotted: str) -> object:
    """A config field by its abk.yaml key, `block.field` included."""
    for part in dotted.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def runtime_name(config: WorkspaceConfig | None = None) -> str:
    """The runtime in force: this machine's `ABK_RUNTIME`, then the file's."""
    from agent_build_kit.settings import settings

    return settings.runtime or (config or _active).runtime


def runtime_entry(
    config: WorkspaceConfig | None = None, *, name: str | None = None
) -> RuntimeConfig:
    """The `runtimes.<name>` entry for the runtime in force (or for `name`),
    or an empty one when the file has none."""
    config = config or _active
    return config.runtimes.get(name or runtime_name(config), RuntimeConfig())


def _check_runtime(config: WorkspaceConfig, path: Path) -> None:
    """A selection that cannot work fails here, not when every unit is held:
    an unknown runtime, or one missing a fact it cannot run without."""
    name = runtime_name(config)
    try:
        runtime = runtimes.get(name)
    except KeyError as error:
        raise ConfigError(f"{path}: {error.args[0]}") from None
    entry = runtime_entry(config)
    missing = [fact for fact in runtime.requires if not getattr(entry, fact, None)]
    if missing:
        raise ConfigError(
            f"{path}: runtime {name!r} needs {', '.join(f'runtimes.{name}.{m}' for m in missing)}"
        )


def dump(config: WorkspaceConfig) -> str:
    """The config as block-style YAML, defaults left out."""
    data = config.model_dump(by_alias=True, exclude_defaults=True, mode="json")
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


# --- the active workspace ------------------------------------------------------

_active: WorkspaceConfig = WorkspaceConfig()
_active_root: Path | None = None


def activate(config: WorkspaceConfig, root: Path | None = None) -> None:
    global _active, _active_root
    _active, _active_root = config, root


def active() -> WorkspaceConfig:
    return _active


def active_root() -> Path | None:
    """The planning root of the active workspace, or None when none is loaded."""
    return _active_root


def models() -> ModelsConfig:
    """The active workspace's models for the runtime in force, role by role:
    this machine's `ABK_*_MODEL`, then that runtime's own
    `runtimes.<name>.models`, then a role the flat `models:` block names, then
    the runtime's own default — never another runtime's names."""
    from agent_build_kit.settings import settings

    own = runtime_entry().models
    named = _active.models.model_fields_set
    flat = {role: getattr(_active.models, role) for role in named}
    default = runtimes.active().default_models

    def pick(role: str, machine: str | None) -> str:
        return machine or getattr(own, role) or flat.get(role) or getattr(default, role)

    return ModelsConfig(
        implement=pick("implement", settings.implement_model),
        rework=pick("rework", settings.rework_model),
        review=pick("review", settings.review_model),
        rework_review=pick("rework_review", settings.rework_review_model),
    )
