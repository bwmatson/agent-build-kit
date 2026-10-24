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

import logging
import os
import re
import shlex
from collections.abc import Callable, Iterable, Iterator
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Annotated, Any, Literal

import yaml
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agent_build_kit import forges, infra, path_patterns, runtimes, sandboxes
from agent_build_kit.compat_names import Place, is_old_spelling, new_spelling, notice, old_spelling
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.replay.models import DEFAULT_KEYED_HEADERS, UpstreamKind
from agent_build_kit.runtimes import known_agents, providers
from agent_build_kit.sandboxes.base import Coverage

if TYPE_CHECKING:
    from agent_build_kit.pipeline.verdict import ReviewTier

CONFIG_FILENAME = "abk.yaml"
OVERLAY_FILENAME = "abk.local.yaml"
CONFIG_ENV = "ABK_CONFIG"


logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """abk.yaml is missing, unreadable or does not match the schema."""


# --- environment ---------------------------------------------------------------


class EnvironmentInputs(Frozen):
    """The files whose contents decide when `sync` must run again, as path patterns
    relative to the repository (`path_patterns.py`); a literal path matches itself."""

    dependencies: list[str] = []
    lock: list[str] = []
    other: list[str] = []

    @field_validator("dependencies", "lock", "other")
    @classmethod
    def _patterns(cls, patterns: list[str], info: ValidationInfo) -> list[str]:
        # A wildcard-free path leaving the repository was documented and written by
        # `abk init` for a path-source checkout, so it loads for one more release.
        path_patterns.validate(patterns, allow_outside=True)
        for pattern in filter(path_patterns.is_outside_literal, patterns):
            logger.warning(
                "environment.inputs.%s lists %r, which leaves the repository; it is hashed "
                "but will be refused in the next release; use `check` to detect drift",
                info.field_name,
                pattern,
            )
        return patterns


class EnvironmentConfig(Frozen):
    """How an environment is brought up to date and told healthy: argv lists
    and path lists, never a tool the framework knows."""

    sync: list[str]
    check: list[str]
    inputs: EnvironmentInputs = EnvironmentInputs()
    # Path patterns of what `sync` and `check` produce: the pipeline's own, never an input,
    # never committed and never counted as a leftover.
    artifacts: list[str] = []

    @field_validator("artifacts")
    @classmethod
    def _artifact_patterns(cls, patterns: list[str]) -> list[str]:
        return path_patterns.validate(patterns)

    @field_validator("sync", "check")
    @classmethod
    def _not_empty(cls, command: list[str]) -> list[str]:
        if not command:
            raise ValueError("the command must not be empty")
        return command


class DraftedEnvironment(EnvironmentConfig):
    """A section `abk init` drafted, with the comment it writes above it. The note is
    not configuration: it is never dumped and is lost on loading the file back."""

    note: str = Field("", exclude=True)


# --- planning repo -----------------------------------------------------------


class PlanningPublish(StrEnum):
    DIRECT = "direct"
    BRANCH = "branch"


class PlanningConfig(Frozen):
    # Relative to the planning root unless absolute.
    state_dir: str = "runs"
    specs_dir: str = "openspec"
    graph_page: str = "docs/unit_graph.md"
    usage_page: str = "docs/unit_cost.md"
    # Where per-unit worktrees are checked out. Never inside the planning root:
    # an agent reached a sibling unit's worktree through `--add-dir` when they
    # were, and a type checker resolved a code repo's imports against the
    # planning repo's own source. None = ~/.local/share/<planning dir name>/worktrees.
    worktree_root: Path | None = None
    # The tracks pull the planning repo before running, so their run logs land
    # on the latest main.
    self_pull: bool = True
    # Where abk's own planning commits in a pipeline worktree go: pushed to the default branch
    # (`direct`), or to a `planning/...` branch with a pull request (`branch`). No effect in a
    # separate planning repo or a working copy.
    publish: PlanningPublish = PlanningPublish.DIRECT


class OpenSpecConfig(Frozen):
    # The command that runs the OpenSpec CLI, when it is not the default
    # `npx --yes @fission-ai/openspec@<settings.openspec_version>`.
    command: list[str] | None = None


class RetentionConfig(Frozen):
    """How long the files the pipeline writes for diagnosis are kept."""

    # The size, in megabytes, of the decision log and of the admission records; past it the
    # oldest lines are dropped.
    decision_log_mb: Annotated[float, Field(gt=0)] = 50
    # How old a unit's run log may get once its summary is in the usage ledger.
    unit_log_days: Annotated[int, Field(ge=0)] = 30


class GitConfig(Frozen):
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

    implement: str = "sonnet"
    rework: str = "sonnet"
    review: str = "opus"
    # A rework is a small targeted edit and the model that made it is the worst
    # judge of whether it landed. With sonnet building and reworking, opus
    # reviewing both is already a different model; an author set to opus wants
    # this set to something else.
    rework_review: str = "opus"


class RuntimeModelsConfig(Frozen):
    """One runtime's own names for the roles in `ModelsConfig`. A role left
    out keeps the flat `models:` block's name, or the runtime's default."""

    implement: str | None = None
    rework: str | None = None
    review: str | None = None
    rework_review: str | None = None


# Points a unit is assumed to spend of each window before the history says otherwise.
BUILTIN_UNIT_ALLOWANCES = {"session": 10, "weekly": 2}


class WindowLimits(Frozen):
    """The ramp every usage window shares: where its threshold sits and how it moves
    toward the window's reset (a subscription window and a provider's month alike)."""

    # Percent of the window at which no NEW unit starts, for most of that window.
    usage_pause_pct: Annotated[int, Field(ge=0, lt=100)] = 70
    # The most the window may ever be run to: the threshold at the moment it
    # resets. Quota not used before a reset is lost, and the headroom the pause
    # protects matters less the closer the reset is. Below 100 because credits
    # pay past the plan limit. Unset, it is the pause percent: the threshold
    # then never moves, and the ramp is skipped.
    usage_pause_ceiling_pct: Annotated[int, Field(ge=0, lt=100)] | None = None
    # The trailing fraction of the window, counted back from its reset, over
    # which the threshold ramps from the pause percent to the ceiling: 0.25 is
    # the last ~75 minutes of a session, the last ~42 hours of a week. Before it
    # the threshold is the pause percent. Meaningless with no ramp.
    usage_relief_fraction: Annotated[float, Field(gt=0, le=1)] = 0.25
    # How much room above current usage the threshold must offer before a
    # paused pipeline is woken: enough that a unit which starts can finish,
    # rather than being admitted exactly at the margin.
    usage_resume_buffer_pct: Annotated[int, Field(ge=0)] = 5

    @property
    def usage_ceiling_pct(self) -> int:
        """The ceiling as it applies: the pause percent when unset."""
        ceiling = self.usage_pause_ceiling_pct
        return self.usage_pause_pct if ceiling is None else ceiling

    @model_validator(mode="after")
    def _ceiling_not_below_pause(self) -> WindowLimits:
        """A ceiling under the pause percent would make the threshold *fall* as
        a reset approaches, which is the opposite of what it is for."""
        if self.usage_ceiling_pct < self.usage_pause_pct:
            raise ValueError(
                f"usage_pause_ceiling_pct ({self.usage_ceiling_pct}) is below "
                f"usage_pause_pct ({self.usage_pause_pct})"
            )
        return self


class UsageWindowConfig(WindowLimits):
    """How full one usage window may get before the pipeline stops starting
    units. The session and the week are both this, with the same names."""

    # Points of this window one unit may spend, counted for each unit that has spent since
    # the last reading or started on an estimate. `auto` (the default) calibrates it from the
    # recorded history and falls back to 10 for the session and 2 for the weekly: a unit costs
    # a larger share of the five-hour window than of the week. A number is the fallback and the
    # cap on the calibrated figure.
    usage_unit_allowance_pct: Annotated[int, Field(ge=0)] | Literal["auto"] = "auto"
    # The least a calibrated allowance of this window may be, in points per unit.
    usage_allowance_floor_pct: Annotated[int, Field(ge=0)] = 1
    # What this window's estimate is built from: the recorded cost of the work (`cost`, used
    # once a fit has earned it) or the flat allowance per unit (`units`).
    usage_estimate_basis: Literal["cost", "units"] = "cost"
    # Whether the cost fit also has a points-per-hour term. The session defaults on and the
    # week off (see ClaudeLimitsConfig).
    usage_estimate_intercept: bool = False

    @model_validator(mode="after")
    def _floor_not_above_cap(self) -> UsageWindowConfig:
        """A floor set above the number set as the allowance would never be reachable."""
        cap = self.usage_unit_allowance_pct
        if (
            "usage_allowance_floor_pct" in self.model_fields_set
            and cap != "auto"
            and self.usage_allowance_floor_pct > cap
        ):
            raise ValueError(
                f"usage_allowance_floor_pct ({self.usage_allowance_floor_pct}) is above "
                f"usage_unit_allowance_pct ({cap})"
            )
        return self


class ClaudeLimitsConfig(Frozen):
    """The Claude subscription's two usage windows (`runtimes.claude_code.limits`).
    They fill independently, so each has its own section."""

    session: UsageWindowConfig = UsageWindowConfig(usage_estimate_intercept=True)
    weekly: UsageWindowConfig = UsageWindowConfig()
    # How long a start is refused when the only reading is too old to trust.
    usage_stale_retry_minutes: Annotated[int, Field(gt=0)] = 5
    # How long a good live usage reading answers every reader before the endpoint is asked again.
    usage_cache_minutes: Annotated[int, Field(gt=0)] = 15
    # How long a block in Claude Code's own cache answers a decision before the endpoint is asked.
    # Unset follows `usage_cache_minutes`; 0 turns the step off.
    usage_claude_cache_minutes: Annotated[int, Field(ge=0)] = 15
    # The longest a good reading is kept once refusals have doubled the time.
    usage_cache_max_minutes: Annotated[int, Field(gt=0)] = 30
    # How old the last good live reading may be and still stand in for a failed call.
    usage_fallback_minutes: Annotated[int, Field(gt=0)] = 30
    # The slowest climb, in percentage points a minute, a window is assumed to make.
    usage_climb_floor: Annotated[float, Field(ge=0)] = 0.2
    # Percentage points added to the usage a reading could have gained since it was taken.
    usage_climb_margin_pct: Annotated[int, Field(ge=0)] = 2
    # The room an estimate must leave under a threshold before a start is allowed on it:
    # what the pipeline cannot see (the person's own use) may fill it.
    usage_headroom_margin_pct: Annotated[int, Field(ge=0)] = 5
    # How many units may start on an estimate for one reading; 0 never allows one.
    usage_estimate_max_starts: Annotated[int, Field(ge=0)] = 3
    # Whether each window's allowance is derived from the recorded readings and ledger.
    calibrate_usage_allowances: bool = True
    # The quantile of points gained per unit the calibrated allowance is, over the newest
    # `usage_allowance_window` pairs, needing at least `usage_allowance_min_pairs`.
    usage_allowance_quantile: Annotated[float, Field(gt=0, le=1)] = 0.9
    usage_allowance_window: Annotated[int, Field(ge=1)] = 30
    usage_allowance_min_pairs: Annotated[int, Field(ge=1)] = 8
    # The cost fit needs at least this many pairs with a cost, within `usage_allowance_window`,
    # and is scaled by this quantile of the gain over its prediction.
    usage_cost_min_pairs: Annotated[int, Field(ge=1)] = 8
    usage_cost_quantile: Annotated[float, Field(gt=0, le=1)] = 0.9
    # Whether a start is forecast from the recorded history of the unit's review tier, the units
    # a tier needs before its history is used, and the quantile its chances are bounded at.
    usage_forecast: bool = True
    usage_forecast_min_runs: Annotated[int, Field(ge=1)] = 10
    usage_forecast_quantile: Annotated[float, Field(gt=0, le=1)] = 0.9

    def configured_allowance(self, window: Literal["session", "weekly"]) -> int:
        """The allowance a window has without calibration: its number, else the built-in one."""
        set_to = getattr(self, window).usage_unit_allowance_pct
        return BUILTIN_UNIT_ALLOWANCES[window] if set_to == "auto" else set_to

    def allowance_ceiling(self, window: Literal["session", "weekly"]) -> int:
        """The most a calibrated allowance may be: the number set, else twice the built-in one."""
        set_to = getattr(self, window).usage_unit_allowance_pct
        return 2 * BUILTIN_UNIT_ALLOWANCES[window] if set_to == "auto" else set_to

    @model_validator(mode="after")
    def _minimum_pairs_within_window(self) -> ClaudeLimitsConfig:
        if self.usage_allowance_min_pairs > self.usage_allowance_window:
            raise ValueError(
                f"usage_allowance_min_pairs ({self.usage_allowance_min_pairs}) is above "
                f"usage_allowance_window ({self.usage_allowance_window})"
            )
        if self.usage_cost_min_pairs > self.usage_allowance_window:
            raise ValueError(
                f"usage_cost_min_pairs ({self.usage_cost_min_pairs}) is above "
                f"usage_allowance_window ({self.usage_allowance_window})"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _session_fit_has_an_intercept(cls, data: object) -> object:
        """The session window's `usage_estimate_intercept` is on where it is not set."""
        if not isinstance(data, dict) or not isinstance(data.get("session", {}), dict):
            return data
        session = {"usage_estimate_intercept": True, **data.get("session", {})}
        return {**data, "session": session}

    @model_validator(mode="before")
    @classmethod
    def _claude_cache_follows_cache(cls, data: object) -> object:
        """`usage_claude_cache_minutes` is `usage_cache_minutes` where it is not set."""
        if not isinstance(data, dict) or data.get("usage_claude_cache_minutes") is not None:
            return data
        default = cls.model_fields["usage_cache_minutes"].default
        return {**data, "usage_claude_cache_minutes": data.get("usage_cache_minutes", default)}


class RestackCheck(StrEnum):
    """How much of unit-test a clean move of a unit's branch onto a moved base runs."""

    AFFECTED = "affected"
    FULL = "full"


class E2eUnitScope(StrEnum):
    """How much of a repo's e2e-test marker a unit's e2e-test step runs."""

    OWN = "own"
    FULL = "full"


def e2e_unit_scope(repo: RepoConfig, limits: LimitsConfig) -> E2eUnitScope:
    """The scope in effect for `repo`: its own `tests.e2e_unit_scope` when set, else the
    `global_limits` one."""
    return repo.tests.e2e_unit_scope or limits.e2e_unit_scope


def review_ceiling(
    repo: RepoConfig | None, config: WorkspaceConfig, tier: ReviewTier | None
) -> int:
    """The changed-lines ceiling in effect for a unit of `repo` expected to get `tier`: the
    tier's own with `review.enabled`, the `full` one without it or when `tier` is None. A repo
    that is None, or not configured, has the workspace's ceilings."""
    ceilings = ceilings_in_effect(repo, config)
    if not config.review.enabled or tier is None:
        return ceilings.full
    return getattr(ceilings, tier.value)


def ceilings_in_effect(repo: RepoConfig | None, config: WorkspaceConfig) -> CeilingsConfig:
    """The ceilings in effect for `repo`: its own value for a tier if set, else the workspace's
    (which is all of them for a repo that is None)."""
    base = CeilingsConfig(
        auto=config.review.ceilings.auto,
        light=config.review.ceilings.light,
        full=workspace_full_ceiling(config),
    )
    own = repo.review.ceilings if repo is not None else None
    if own is None:
        return base
    return CeilingsConfig(
        auto=own.auto if own.auto is not None else base.auto,
        light=own.light if own.light is not None else base.light,
        full=own.full if own.full is not None else base.full,
    )


def workspace_full_ceiling(config: WorkspaceConfig) -> int:
    """`review.ceilings.full` when set, else the deprecated `global_limits.max_unit_lines`."""
    if "full" in config.review.ceilings.model_fields_set:
        return config.review.ceilings.full
    return config.global_limits.max_unit_lines


class E2eBeforeMerge(StrEnum):
    """Whether a unit's e2e-test step runs before its pull request merges or is left to verify."""

    REQUIRED = "required"
    DEFERRED = "deferred"


def e2e_before_merge(repo: RepoConfig, limits: LimitsConfig) -> E2eBeforeMerge:
    """The value in effect for `repo`: its own `tests.e2e_before_merge` when set, else the
    `global_limits` one."""
    return repo.tests.e2e_before_merge or limits.e2e_before_merge


class E2eSchedule(StrEnum):
    """How often a repo's whole e2e-test suite is due to run on its own."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    OFF = "off"


def e2e_schedule(repo: RepoConfig, limits: LimitsConfig) -> E2eSchedule:
    """The schedule in effect for `repo`: its own `tests.e2e_schedule` when set, else the
    `limits` one."""
    return repo.tests.e2e_schedule or limits.e2e_schedule


def e2e_splits(repo: RepoConfig, config: WorkspaceConfig) -> tuple[E2eSplit, ...]:
    """The splits in effect for `repo`: its declared ones in declaration order, then `rest`."""
    own = repo.tests.e2e_splits
    return _splits_of(config.tests.e2e_splits if own is None else own)


def _splits_of(declared: dict[str, E2eSplitEntry]) -> tuple[E2eSplit, ...]:
    """The splits a `tests.e2e_splits` mapping declares, in order, then `rest`."""
    named = [
        E2eSplit(name=name, marker=entry.marker, hold=entry.hold)
        for name, entry in declared.items()
        if name != REST_SPLIT
    ]
    rest = declared.get(REST_SPLIT, E2eSplitEntry())
    return (*named, E2eSplit(name=REST_SPLIT, hold=rest.hold))


def e2e_dimensions(
    repo: RepoConfig, config: WorkspaceConfig
) -> dict[str, dict[str, E2eDimensionValue]]:
    """The dimensions in effect for `repo`: its own `tests.e2e_dimensions` when set, else the
    top level's."""
    own = repo.tests.e2e_dimensions
    return config.tests.e2e_dimensions if own is None else own


def unavailable_markers(repo: RepoConfig, config: WorkspaceConfig) -> tuple[str, ...]:
    """The markers of the values `tests.e2e_available` leaves out for `repo`."""
    available = config.tests.e2e_available
    return tuple(
        entry.marker
        for dimension, values in e2e_dimensions(repo, config).items()
        if dimension in available
        for value, entry in values.items()
        if value not in available[dimension]
    )


def known_runtime_names(configured: Iterable[str] = ()) -> set[str]:
    """The runtimes a test tag or a `tests` list may name: the registry's, the protocol
    runtime's and the keys under `runtimes`, never the reserved name of the base group."""
    return {*runtimes.names(), known_agents.RUNTIME_NAME, *configured} - {BASE_GROUP}


def _unquoted_off(value: object) -> object:
    # YAML 1.1 reads an unquoted `off`, the documented default, as the boolean False.
    return "off" if value is False else value


class PolicyMarker(StrEnum):
    """What the person said about the runtime's policy check (`runtimes.<name>.policy`)."""

    UNCHECKED = "unchecked"  # carried on without the check; doctor says so rather than probing


class AccountConfig(Frozen):
    """One Claude account by label (`runtimes.claude_code.accounts.<label>`), set per person."""

    # The account's Claude Code config directory: an absolute path, never in the committed file.
    config_dir: Path | None = None
    limits: ClaudeLimitsConfig = ClaudeLimitsConfig()
    max_units_in_progress: Annotated[int, Field(gt=0)] | None = None

    @field_validator("config_dir")
    @classmethod
    def _config_dir_is_absolute(cls, value: Path | None) -> Path | None:
        if value is not None and not value.expanduser().is_absolute():
            raise ValueError(
                f"{str(value)!r} is relative; write an absolute path, since a relative one "
                "would mean a different directory under each shell and timer"
            )
        return value.expanduser() if value is not None else None


def _committed_config_dirs(document: dict[str, Any]) -> list[str]:
    """The keys of `runtimes.claude_code.accounts.<label>.config_dir` the document sets."""
    runtimes = document.get("runtimes")
    runtime = runtimes.get(CLAUDE_CODE) if isinstance(runtimes, dict) else None
    accounts = runtime.get("accounts") if isinstance(runtime, dict) else None
    if not isinstance(accounts, dict):
        return []
    return [
        f"runtimes.{CLAUDE_CODE}.accounts.{label}.config_dir"
        for label, entry in accounts.items()
        if isinstance(entry, dict) and "config_dir" in entry
    ]


class RuntimeConfig(Frozen):
    """What one agent runtime needs from this installation (`runtimes.<name>`)."""

    # The argv that starts the runtime's agent, for a runtime that spawns one.
    command: list[str] | None = None
    # What an operator runs to make the agent refuse what abk forbids, when the
    # runtime's policy check finds a class unenforced. abk only runs it when
    # asked to, and never interprets it.
    policy_fix: list[str] | None = None
    # `unchecked`: the person carried on without confirming the agent refuses what abk
    # forbids. Unset for every runtime whose check was run or is yet to be.
    policy: PolicyMarker | None = None
    # The installation's own command globs, merged after the kit's recommended ones.
    policy_extra: list[str] | None = None

    @field_validator("policy_extra")
    @classmethod
    def _extras_are_not_blank(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not item.strip() for item in value):
            raise ValueError("policy_extra: an item is blank")
        return value

    models: RuntimeModelsConfig = RuntimeModelsConfig()
    # The context window, in tokens, of each model, for when the agent does not say
    # (read by the Claude Code runtime only).
    context_windows: dict[str, int] = {}

    # Claude's usage windows (`runtimes.claude_code` only): see ClaudeLimitsConfig.
    limits: ClaudeLimitsConfig = ClaudeLimitsConfig()
    # The accounts a repo may name by label (`runtimes.claude_code` only).
    accounts: dict[str, AccountConfig] = {}


class ContextConfig(Frozen):
    """How a call's context window use is read (`context`)."""

    # A fall in the fill between two requests larger than this share of the window
    # is a compaction, for a runtime with no marker of its own.
    compaction_drop_share: float = 0.3
    # A step ending above this share of the window logs a warning.
    warn_share: float = 0.8


# A block holding test-kind settings: written under the new key names (the aliases), still built
# by the field names. The old key names are renamed to the new ones where a file is read.
TEST_KIND_SETTINGS = ConfigDict(validate_by_name=True, serialize_by_alias=True)


class TestKindSettings(Frozen):
    """A block of settings named for a test kind. An old key name in a file is read as the new
    one, with a warning; the old names are not attributes."""

    model_config = TEST_KIND_SETTINGS
    __test__ = False

    @model_validator(mode="before")
    @classmethod
    def _read_old_names(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        renamed = {k: new_spelling(Place.SETTING, k) if isinstance(k, str) else k for k in data}
        for key, new in renamed.items():
            if new != key and new in data:
                raise ValueError(
                    f"`{key}` and `{new}` are both set; `{key}` is the deprecated name of "
                    f"`{new}`, keep one"
                )
        return {
            (renamed[k] if renamed[k] in cls.model_fields and k not in cls.model_fields else k): v
            for k, v in data.items()
        }


class ProjectLimitsConfig(Frozen):
    """The scheduling settings (`project_limits`), configured once at the root for every project."""

    # How many units are implemented at once in one project (a repo's project).
    max_concurrent_stacks: int = 4
    # How many restacks (moving a unit's branch onto a changed base) run at once in one
    # project, in a lane apart from the build workers: a restack takes no build slot.
    max_concurrent_restacks: Annotated[int, Field(ge=1)] = 2
    # How many units may be started and not finished at once in one project (a repo's project).
    # At it no unit that has never started does; what drains the queue
    # (finishing, rework, resuming, a further review round) still runs.
    max_units_in_progress: Annotated[int, Field(ge=1)] = 5

    # The cap on priority-0 units started past the normal limits at once; 0 is off.
    emergency_extra: Annotated[int, Field(ge=0)] = 1


# The scheduling settings that moved from the limits block to `project_limits`.
MOVED_TO_PROJECT_LIMITS = (
    "max_units_in_progress",
    "max_concurrent_stacks",
    "max_concurrent_restacks",
)


class WaitEndRequeue(StrEnum):
    """How a failed unit is requeued when the wait it was recorded in ends: the mode its
    record gives, a forced mode, or not at all."""

    AUTO = "auto"
    RESUME = "resume"
    REWORK = "rework"
    OFF = "off"


class LimitsConfig(TestKindSettings):
    # How a failed unit that waited on another unit is requeued once, when its wait ends.
    wait_end_requeue: WaitEndRequeue = WaitEndRequeue.AUTO
    # Longest chain of in-review PRs from main to a branch that a unit may
    # start building on.
    stack_depth_build_cap: int = 3
    # Deepest a dependent may sit when a merge restacks it; one beyond it is
    # held until a later merge brings it within. Unset: the build cap's value.
    stack_depth_rebase_cap: int | None = None
    # Most tests that may fail a run's first pass and pass the serial rerun before the run
    # is recorded as one flake storm (a disturbed host), with no fix change per test.
    max_flakes_per_run: Annotated[int, Field(ge=1)] = 5
    # Seconds after a push in which a pull request with no checks yet still reads
    # `checking`: CI may not have registered.
    checks_register_seconds: int = 120
    # How many times in a row a unit may be put back to planned or held with the same cause,
    # each run shorter than `bounce_span_seconds`, before it is named as looping.
    bounce_limit: Annotated[int, Field(ge=2)] = 3
    bounce_span_seconds: Annotated[int, Field(ge=1)] = 120
    # How many pull requests of finished units a round (each tick and each refresh of a
    # pass) takes their stale state label off, so a backlog does not spend the code
    # host's rate limit at once.
    label_sweep_per_tick: Annotated[int, Field(ge=1)] = 20
    # Seconds a manual step's check script may run before it counts as timed out.
    manual_check_seconds: Annotated[int, Field(ge=1)] = 30
    # Estimated changed lines before a unit stops absorbing the next task group.
    min_unit_lines: int = 400
    # Estimated changed lines one unit may carry. It shapes plans; a unit whose
    # pull request lands over it is logged and listed by `abk status`, never
    # blocked. A plan is held to it after calibration (`calibrate_estimates`).
    max_unit_lines: int = 750
    # Whether a unit's estimate is multiplied by what units of its kind (repo, tier and
    # group flag) landed at before it is held to the ceiling. The ratio is the median of
    # the last `calibration_window` merged units' actual over estimate, each sample
    # clamped to `calibration_sample_clamp`, moved toward 1 by n / (n + calibration_shrink),
    # 1 with fewer than `calibration_min` samples, and kept between 1 and `calibration_max`.
    calibrate_estimates: bool = True
    calibration_window: Annotated[int, Field(ge=1)] = 20
    calibration_min: Annotated[int, Field(ge=1)] = 3
    calibration_shrink: Annotated[float, Field(ge=0)] = 5
    calibration_sample_clamp: tuple[float, float] = (0.5, 4.0)
    calibration_max: Annotated[float, Field(ge=1)] = 3.0
    # What the planner is shown of each calibrated kind: how many of its newest merged units
    # (0 shows none) and how many kinds, the ones with most samples first.
    calibration_examples: Annotated[int, Field(ge=0)] = 3
    calibration_kinds_listed: Annotated[int, Field(ge=1)] = 5
    # Path patterns (fnmatch, against the whole path or the file name) of
    # generated files, left out of a unit's actual size.
    generated_files: tuple[str, ...] = ()
    # How many times a unit may be sent back by review before it fails.
    max_review_rounds: int = 3
    # How many times a branch that fails its checks (lint, types, tests) is sent
    # back to the builder before a reviewer is asked for it. Counted per round of
    # review: the budget starts again before each one, so a rework that breaks
    # the build gets its own attempts. null is no limit (a fix that changes
    # nothing still ends the run). The checks always run, as they are the gate
    # before a review and a push; 0 only means a failure fails the unit at once,
    # with no fix attempt.
    max_check_rounds: Annotated[int, Field(ge=0)] | None = 3
    # How many times, the first included, the adapt step's test accounting is
    # asked for before the unit fails, when it is incomplete rather than wrong.
    max_adapt_rounds: Annotated[int, Field(ge=1)] = 2
    # How many times one version of a tasks.md is sent to the planner.
    max_plan_attempts: int = 3
    # How many times a head commit's cancelled checks are re-run before the
    # host is taken to be cancelling them for good.
    max_check_reruns: Annotated[int, Field(ge=0)] = 2
    # Longest tool result, in characters, that a unit's transcript keeps whole.
    transcript_result_chars: Annotated[int, Field(ge=1)] = 20000
    # How many runs of one unit keep their transcript.
    transcript_runs_kept: Annotated[int, Field(ge=1)] = 3
    # Longest a unit-test command may run before it is asked to abort, in seconds.
    unit_test_command_seconds: Annotated[float, Field(gt=0, alias="unit_test_command_seconds")] = (
        3600
    )
    # How long an aborted unit-test command has to exit before it is ended, in seconds.
    unit_test_abort_grace_seconds: Annotated[
        float, Field(gt=0, alias="unit_test_abort_grace_seconds")
    ] = 10
    # How many times the tests a unit added or changed are run again, under the same
    # load, after unit-test passes; 0 turns the check off.
    unit_test_repeat_runs: Annotated[int, Field(ge=0, alias="unit_test_repeat_runs")] = 3
    # What unit-test runs after a clean move onto a moved base: `affected` scopes it by the
    # files the move brought in, `full` runs the whole suite as before.
    restack_check: RestackCheck = RestackCheck.AFFECTED
    # Whether the untouched tests that fail e2e-test are run once on the base, to tell a
    # failure the unit caused from one already there; 0 turns the run off. A switch, not a
    # count: one run answers the question.
    e2e_base_runs: Annotated[int, Field(ge=0, le=1, alias="e2e_base_runs")] = 1
    # How much of a repo's e2e-test marker a unit's e2e-test step runs: `own` the tests its branch
    # added or changed, `full` the whole marker. A repo's `tests.e2e_unit_scope` wins.
    e2e_unit_scope: E2eUnitScope = Field(E2eUnitScope.OWN, alias="e2e_unit_scope")
    # Whether a unit's e2e-test runs before its PR merges (`required`) or is left to verify
    # after the merge (`deferred`). A repo's `tests.e2e_before_merge` wins.
    e2e_before_merge: E2eBeforeMerge = Field(E2eBeforeMerge.REQUIRED, alias="e2e_before_merge")
    # How often a repo's whole e2e-test suite is due to run on its own; a repo's
    # `tests.e2e_schedule` wins.
    e2e_schedule: E2eSchedule = Field(E2eSchedule.WEEKLY, alias="e2e_schedule")
    e2e_schedule_off = field_validator("e2e_schedule", mode="before")(_unquoted_off)
    # Longest a unit waits for the e2e-test lock before its e2e-test step fails as busy, in seconds.
    e2e_lock_wait_seconds: Annotated[int, Field(gt=0, alias="e2e_lock_wait_seconds")] = 5400
    # How many of an e2e-test run's slowest test entries the posted result lists; 0 lists every one.
    e2e_durations_shown: Annotated[int, Field(ge=0, alias="e2e_durations_shown")] = 15
    # Longest the connectivity probe waits to connect to one host, in seconds (a name lookup
    # waits on the system resolver instead). The probe tells a network
    # outage from a model service outage when an agent run ends on a failure to connect.
    network_probe_timeout_seconds: Annotated[int, Field(gt=0)] = 5
    # Bare host names the probe also tries, beside the code hosts, to tell whether the
    # network as a whole is down. Port 443; an empty list leaves the code hosts alone.
    network_control_hosts: tuple[str, ...] = ("one.one.one.one", "dns.google")
    # How many times in a row a unit is parked because the model service answered 5xx or
    # 529; the next such failure fails it, as a persistent 5xx can be a real fault.
    service_unavailable_attempts: Annotated[int, Field(gt=0)] = 5

    @field_validator("network_control_hosts")
    @classmethod
    def _bare_host_names(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        """A host name and nothing else: no scheme, path, port or space."""
        for host in hosts:
            if not host or any(mark in host for mark in ("/", ":", " ")):
                raise ValueError(f"{host!r} is not a bare host name")
        return hosts

    @model_validator(mode="after")
    def _calibration_usable(self) -> LimitsConfig:
        """The calibration settings must be usable. The floor against the ceiling is checked by
        the workspace, where the ceiling in effect is known (`review.ceilings.full` or this)."""
        if self.calibration_min > self.calibration_window:
            raise ValueError(
                f"calibration_min ({self.calibration_min}) must not exceed "
                f"calibration_window ({self.calibration_window})"
            )
        low, high = self.calibration_sample_clamp
        if not 0 < low <= 1 <= high:
            raise ValueError(
                f"calibration_sample_clamp ({low}, {high}) must have a low above 0 and "
                "not above 1, and a high not below 1"
            )
        return self


class TracksConfig(Frozen):
    """The scheduled health/improve/recommend tracks and the propose pass."""

    # Claude Code's alias, sent as is to whichever runtime is active: not
    # resolved per runtime, so a workspace on another runtime sets it.
    model: str = "sonnet"
    propose_max_issues: int = 3
    # Claude Code's --allowedTools/--disallowedTools syntax; neither list has
    # any effect under the acp runtime.
    # None is the built-in list (`tracks.runner.allowed_tools_value`): the base
    # tools plus every forge's way of reading a PR. A list set here is used as is.
    allowed_tools: str | None = None
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


class ReplayUpstream(Frozen):
    name: str
    # The upstream's real base URL.
    url: str
    kind: UpstreamKind
    # The environment variables that point the code under test at the proxy's listener.
    env: list[str] = []
    # The request headers that change this upstream's answer, and so are part of a key.
    keyed_headers: list[str] = list(DEFAULT_KEYED_HEADERS)


class ReplayConfig(Frozen):
    upstreams: list[ReplayUpstream] = []
    directory: Path = Path("tests/cassettes")
    max_age_days: int = 30
    llm_max_age_days: int = 14
    max_body_bytes: int = 2 * 1024 * 1024
    max_directory_mb: int = 100
    review_after_runs: int = 5


# The reserved split of the tests that sit in no declared split.
REST_SPLIT = "rest"
SPLIT_NAME = re.compile(r"[a-z0-9_]+")


class ProviderLimitsConfig(WindowLimits):
    """`gate.provider.limits`: one window's ramp, and nothing a subscription window alone has."""

    @model_validator(mode="before")
    @classmethod
    def _no_subscription_settings(cls, data: object) -> object:
        if isinstance(data, dict):
            own = set(cls.model_fields)
            only_claude = (
                set(ClaudeLimitsConfig.model_fields) | set(UsageWindowConfig.model_fields)
            ) - own
            for key in data:
                if key in set(GateConfig.model_fields) - {"command", "provider"}:
                    raise ValueError(
                        f"gate.provider.limits.{key}: set `{key}` on `gate`, beside `provider`"
                    )
                if key in only_claude:
                    raise ValueError(
                        f"gate.provider.limits.{key}: belongs to runtimes.{CLAUDE_CODE}.limits, "
                        "the only runtime with subscription usage windows"
                    )
        return data


class GateProviderConfig(Frozen):
    """The provider whose usage a split's gate reads."""

    name: str
    budget_usd: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    limits: ProviderLimitsConfig = ProviderLimitsConfig()

    @field_validator("name")
    @classmethod
    def _name_in_table(cls, name: str) -> str:
        if name not in providers.names():
            raise ValueError(
                f"gate.provider.name: {name!r} is not a provider; "
                f"the table has {', '.join(providers.names())}"
            )
        return name


class OnUnknown(StrEnum):
    """What a gate whose answer cannot be had does: let the split run, or hold it."""

    ALLOW = "allow"
    HOLD = "hold"


class GateConfig(Frozen):
    """A split's gate: the provider it reads usage from, or a command that answers."""

    command: Annotated[list[str], Field(min_length=1)] | None = None
    provider: GateProviderConfig | None = None
    timeout_seconds: Annotated[int, Field(gt=0)] = 30
    on_unknown: OnUnknown = OnUnknown.ALLOW
    usage_cache_minutes: Annotated[int, Field(gt=0)] = 15
    usage_stale_retry_minutes: Annotated[int, Field(gt=0)] = 5

    @model_validator(mode="before")
    @classmethod
    def _limits_belong_under_provider(cls, data: object) -> object:
        if isinstance(data, dict) and "limits" in data:
            if data.get("command") is not None:
                raise ValueError("gate.limits: a command has no window for limits to mean anything")
            raise ValueError("gate.limits: set limits under gate.provider")
        return data

    @model_validator(mode="after")
    def _exactly_one_answer(self) -> GateConfig:
        if (self.command is None) == (self.provider is None):
            raise ValueError(
                "gate: set exactly one of `provider` and `command`"
                + (", not both" if self.command is not None else ", neither is set")
            )
        return self


class E2eSplitEntry(Frozen):
    """One `tests.e2e_splits.<name>` entry as written: a selector, a hold and a gate."""

    marker: str | None = None
    hold: bool | None = None
    gate: GateConfig | None = None


class E2eSplit(Frozen):
    """A repo's e2e-test split: its name, its marker (None for `rest`) and its configured hold."""

    name: str
    marker: str | None = None
    hold: bool | None = None


class E2eDimensionValue(Frozen):
    """One value of a `tests.e2e_dimensions.<dimension>` entry: the marker its tests carry."""

    marker: str


class E2eSandboxConfig(Frozen):
    """What an e2e-test step may touch beyond a unit-test step's sandbox policy: paths to read
    and write, hosts the proxy lets through, and the local ports of the services it needs."""

    read: list[str] = []
    write: list[str] = []
    hosts: list[str] = []
    ports: list[int] = []


class TestsConfig(TestKindSettings):
    # Extra packages the repo-root tests (outside every workspace member) need.
    root_extras: list[str] = []
    # The command that applies this repo's fixers, to which the file names are appended; None
    # follows the profile and the empty list turns the fixer pass off.
    fix_command: list[str] | None = None
    # The pytest marker on tests that need the real local stack (e2e-test).
    e2e_marker: str = Field("local_stack", alias="e2e_marker")
    # What an e2e-test step's sandbox allows beyond a unit-test step's.
    e2e_sandbox: E2eSandboxConfig = E2eSandboxConfig()
    # This repo's e2e-test scope; None follows `global_limits.e2e_unit_scope`.
    e2e_unit_scope: E2eUnitScope | None = Field(None, alias="e2e_unit_scope")
    # This repo's e2e-before-merge choice; None follows `global_limits.e2e_before_merge`.
    e2e_before_merge: E2eBeforeMerge | None = Field(None, alias="e2e_before_merge")
    # This repo's schedule; None follows `limits.e2e_schedule`.
    e2e_schedule: E2eSchedule | None = Field(None, alias="e2e_schedule")
    e2e_schedule_off = field_validator("e2e_schedule", mode="before")(_unquoted_off)
    # The marker on e2e tests only the dev stack can run (left out of live checks).
    dev_stack_marker: str = "dev_stack"
    # Record and replay of the calls e2e tests make outside the stack; None: none.
    replay: ReplayConfig | None = None
    # This repo's e2e-test splits; None follows the top-level `tests.e2e_splits`.
    e2e_splits: dict[str, E2eSplitEntry] | None = Field(None, alias="e2e_splits")
    # This repo's dimensions; None follows the top-level `tests.e2e_dimensions`.
    e2e_dimensions: dict[str, dict[str, E2eDimensionValue]] | None = None


# The older name of `rest`, the e2e tests in no split; reserved, so no split has this name.
# Deleted with the last caller that still uses it.
BASE_GROUP = "base"


# The runtime lists that no longer exist, each with the setting that replaces it.
REPLACED_RUNTIME_LISTS = {
    "runtimes_blocked": "`tests.e2e_splits.<name>.hold: true`",
    "runtimes_allowed": "`tests.e2e_splits.<name>.hold: false`",
    f"{old_spelling(TestTier.E2E_TEST)}_runtimes": "a split declared under `tests.e2e_splits`",
}


class RuntimeTestsConfig(TestKindSettings):
    """The installation-wide `tests` block: the declared e2e-test splits."""

    e2e_splits: dict[str, E2eSplitEntry] = Field({}, alias="e2e_splits")
    e2e_dimensions: dict[str, dict[str, E2eDimensionValue]] = {}
    # The values this machine has, per dimension; a dimension with no entry has every value.
    e2e_available: dict[str, list[str]] = {}


# The words of a `command` template that stand for a list of arguments.
TEMPLATE_PLACEHOLDERS = ("{changed_files}", "{failed_ids}")


class AffectedConfig(Frozen):
    # How a fix round picks the tests it runs: `off` runs the full tests, `profile`
    # asks the toolchain profile, `command` runs `command`.
    mode: Literal["off", "profile", "command"] = "off"
    # In `command` mode: a template whose `{changed_files}` and `{failed_ids}` are
    # each replaced by separate quoted arguments.
    command: str | None = None

    mode_off = field_validator("mode", mode="before")(_unquoted_off)

    @model_validator(mode="after")
    def _command_mode_needs_its_template(self) -> AffectedConfig:
        if self.mode == "command" and not self.command:
            raise ValueError("checks.affected.mode `command` needs a `command` template")
        for word in shlex.split(self.command or ""):
            if word not in TEMPLATE_PLACEHOLDERS and any(p in word for p in TEMPLATE_PLACEHOLDERS):
                raise ValueError(
                    f"checks.affected.command: a placeholder must be a word of its own, "
                    f"not part of `{word}`"
                )
        return self


class ChecksConfig(Frozen):
    affected: AffectedConfig = AffectedConfig()


class DevStackConfig(Frozen):
    # A script with `up`, `test` and `down` subcommands. E2e-test runs a unit's
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


class SandboxConfig(Frozen):
    """Whether agent steps run confined by the kernel, and by which backend."""

    enabled: bool = False
    # `auto` picks the first backend whose probe passes on this machine.
    backend: str = "auto"

    @field_validator("backend")
    @classmethod
    def _known_backend(cls, value: str) -> str:
        known = sandboxes.names()
        if value != "auto" and value not in known:
            raise ValueError(f"unknown sandbox backend {value!r} (known: auto, {', '.join(known)})")
        return value


class ProjectSandboxConfig(Frozen):
    """What a project's steps may touch beyond the built-ins, as `abk.yaml` and
    `abk.local.yaml` list it: paths to write and to read, and hosts the proxy lets through."""

    write: list[str] = []
    read: list[str] = []
    hosts: list[str] = []


class RepoSandboxConfig(ProjectSandboxConfig):
    """A repo's lists, and how much confinement its steps need."""

    # The least coverage a step may run with; `none` lets it run unconfined. Per repo only.
    required: Coverage = Coverage.FILES


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
    sandbox: ProjectSandboxConfig = ProjectSandboxConfig()

    @property
    def prefix(self) -> str:
        """What a path under this project starts with; empty for the root project."""
        return "" if self.path in (".", "") else f"{self.path}/"


def owning_project(projects: list[ProjectConfig], path: str) -> ProjectConfig | None:
    """The project a path relative to the checkout belongs to: the deepest one that holds
    it, so the web app claims its own files rather than the service it sits inside. A
    root project holds everything."""
    ordered = sorted(projects, key=lambda p: len(Path(p.path).parts), reverse=True)
    return next((p for p in ordered if path.startswith(p.prefix)), None)


def by_project(
    projects: list[ProjectConfig], paths: list[str]
) -> list[tuple[ProjectConfig | None, list[str]]]:
    """`paths` (relative to the checkout) grouped by the project that owns each, in the order
    each project first appears, as paths relative to that project. A path no project owns
    is grouped under None and keeps its name."""
    groups: dict[str | None, tuple[ProjectConfig | None, list[str]]] = {}
    for path in paths:
        owner = owning_project(projects, path)
        _, owned = groups.setdefault(owner.path if owner else None, (owner, []))
        owned.append(path.removeprefix(owner.prefix) if owner else path)
    return list(groups.values())


class AzureDevOpsConfig(Frozen):
    """Where a repo lives on Azure DevOps, decoded.

    Three separate values rather than one string: the remote percent-encodes a
    project with a space in it, and a project name containing a slash would
    make a re-split of `org/project/repo` ambiguous.
    """

    org: str = ""
    project: str = ""
    repo: str = ""


AGENT_PATH_WORD = "{path}"


class AgentPurpose(StrEnum):
    TEST = "test"
    LINT = "lint"
    FORMAT = "format"
    CHECK = "check"


class AgentScope(StrEnum):
    WHOLE = "whole"
    FILE = "file"
    NODE_ID = "node-id"


class AgentCommand(Frozen):
    """One command a build agent may run, and what it is for."""

    purpose: AgentPurpose
    # An argument list; a string in abk.yaml is split like a shell would. `{path}` stands for
    # what the agent picks, and is there exactly when the scope is not `whole`.
    command: list[str]
    scope: AgentScope = AgentScope.WHOLE

    @model_validator(mode="before")
    @classmethod
    def _split(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("command"), str):
            return {**data, "command": shlex.split(data["command"])}
        return data

    @model_validator(mode="after")
    def _path_fits_scope(self) -> AgentCommand:
        has_path = AGENT_PATH_WORD in self.command
        if has_path and self.scope is AgentScope.WHOLE:
            raise ValueError(f"{AGENT_PATH_WORD} is for a file or node-id scope, not whole")
        if not has_path and self.scope is not AgentScope.WHOLE:
            raise ValueError(f"a {self.scope} scope needs {AGENT_PATH_WORD} in the command")
        return self


class RepoCeilingsConfig(Frozen):
    """A repo's own ceilings; a tier left unset follows the workspace's."""

    auto: int | None = None
    light: int | None = None
    full: int | None = None


class RepoReviewConfig(Frozen):
    """A repo's own review policy: the protected paths that add to the workspace's."""

    protected_paths: list[str] = []
    ceilings: RepoCeilingsConfig = RepoCeilingsConfig()


class RepoConfig(Frozen):
    path: Path
    # GitHub owner/name. The owner decides which `gh` account's token is used.
    # Empty for a repo on a host that names itself some other way.
    slug: str = ""
    default_branch: str = "main"
    # The label of the Claude account this repo's units run on; see `runtimes.claude_code.accounts`.
    account: str | None = None
    # The code host this repo lives on (forges/). Inferred by `abk init` from
    # the origin URL; set it here when the origin does not say.
    forge: str = "github"
    # Where the repo lives, for a forge that does not use `slug`.
    azure_devops: AzureDevOpsConfig = AzureDevOpsConfig()
    # The toolchain profile (profiles/): how to lint, test and read results.
    profile: str = "python-uv"
    # The infrastructure profile (infra/): what the repo runs on, apart from
    # its language. `none` records nothing about a live stack.
    infra: str = "none"
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
    checks: ChecksConfig = ChecksConfig()
    # The commands a build agent is told it may run; None follows the profiles.
    agent_commands: list[AgentCommand] | None = None
    dev_stack: DevStackConfig | None = None
    deploy: DeployConfig = DeployConfig()
    # Where the repo keeps its changelog; None switches the changelog convention
    # and check off for this repo.
    changelog: str | None = "CHANGELOG.md"
    # How this repo's environment is kept current in a unit's worktree.
    environment: EnvironmentConfig | None = None
    review: RepoReviewConfig = RepoReviewConfig()
    sandbox: RepoSandboxConfig = RepoSandboxConfig()


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
    # Recorded beside an e2e-test result so a reviewer can see what the stack
    # was. "profile" (not set) asks the repo's profile; None records nothing.
    stack_versions_command: list[str] | Literal["profile"] | None = "profile"
    # Environment handed to the live-stack tests, each value resolved by a
    # provider at verify time.
    env: dict[str, Provider] = {}


class NotificationProvider(StrEnum):
    """Which provider shows the cards; `OFF` builds none."""

    OFF = "off"
    COMMAND = "command"
    WINDOWS = "windows"


_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SHOW_PLACEHOLDERS = frozenset({"id", "title", "body", "link"})
_CLEAR_PLACEHOLDERS = frozenset({"id"})


def fill_template(template: str, values: dict[str, str]) -> str:
    """`template` with each `{name}` replaced by its value, in one pass: a value that holds
    a placeholder is left as it is."""
    return _PLACEHOLDER.sub(lambda found: values[found.group(1)], template)


class CommandTemplates(Frozen):
    show: str = ""
    clear: str = ""


class NotificationsConfig(Frozen):
    provider: NotificationProvider = NotificationProvider.OFF
    remind_after_minutes: int = Field(default=30, ge=0)
    delay_minutes: int = Field(default=10, ge=0)
    command: CommandTemplates = CommandTemplates()

    @model_validator(mode="after")
    def _command_templates(self) -> NotificationsConfig:
        if self.provider is NotificationProvider.COMMAND and not self.command.show:
            raise ValueError("notifications.command.show: the command provider needs a template")
        for key, template, known in (
            ("show", self.command.show, _SHOW_PLACEHOLDERS),
            ("clear", self.command.clear, _CLEAR_PLACEHOLDERS),
        ):
            unknown = sorted(set(_PLACEHOLDER.findall(template)) - known)
            if unknown:
                raise ValueError(
                    f"notifications.command.{key}: unknown placeholder {', '.join(unknown)}; "
                    f"use {', '.join(sorted(known))}"
                )
        return self


def stack_versions_for(verify: VerifyConfig, profile: infra.InfraProfile) -> list[str] | None:
    """The command that records the live stack: the config's when set, else the
    repo's infrastructure profile's."""
    command = verify.stack_versions_command
    if command == "profile":
        return list(profile.stack_versions_command) if profile.stack_versions_command else None
    return command


# The runtime whose usage windows the pause thresholds describe.
CLAUDE_CODE = "claude_code"


# Mirrors graph.state.SessionRole, which config cannot import; a test keeps them in step.
SESSION_REUSE_ROLES = ("build", "review")


# The root key `global_limits` was called `limits` before; the old name still loads.
DEPRECATED_ROOT_KEY = "limits"

# The `builders` setting `stubbed_tdd_commits` was called `per_group_commits` before; the old name
# still loads.
DEPRECATED_BUILDERS_KEY = "per_group_commits"
BUILDERS_KEY = "stubbed_tdd_commits"
DEPRECATED_BUILDERS_SETTING = f"builders.{DEPRECATED_BUILDERS_KEY}"

# The setting `review.ceilings.full` replaces, as `abk config` and `abk doctor` name it.
DEPRECATED_MAX_UNIT_LINES = "global_limits.max_unit_lines"


def deprecation_notice(key: str) -> str:
    """What `abk config` and `abk doctor` say of a deprecated key."""
    if key == DEPRECATED_MAX_UNIT_LINES:
        return (
            f"`{key}` is deprecated for `review.ceilings.full`; "
            "`abk config --migrate` moves it, or set `review.ceilings.full` yourself"
        )
    if key == DEPRECATED_BUILDERS_SETTING:
        return (
            f"`{key}` is deprecated for `builders.{BUILDERS_KEY}`; "
            "`abk config --migrate` renames it"
        )
    return (
        f"`{key}` is deprecated for `global_limits`; "
        "`abk config --migrate` moves it to the new names"
    )


class BuildersConfig(Frozen):
    """What a builder run may do beyond writing files (`builders`)."""

    # Base names `abk install-config` may install, besides `.pre-commit-config.yaml`.
    installable_files: list[str] = []
    # Stubs, the check-and-fix loop before the tests commit and one tests/implementation
    # pair per task group, for a unit whose toolchain profile supports stubs.
    stubbed_tdd_commits: StrictBool = True

    @model_validator(mode="before")
    @classmethod
    def _read_old_name(cls, data: Any) -> Any:
        return rename_builders_key(data)

    @field_validator("installable_files")
    @classmethod
    def _base_names(cls, names: list[str]) -> list[str]:
        for name in names:
            if not name.strip() or name in (".", "..") or any(char in name for char in "/\\*?["):
                raise ValueError(
                    f"installable_files: {name!r} is not a base file name "
                    "(no path separators, no patterns)"
                )
        return names


def rename_builders_key(data: Any) -> Any:
    """A `builders` mapping with the deprecated `per_group_commits` renamed to
    `stubbed_tdd_commits`; a mapping that sets both is refused."""
    if not isinstance(data, dict) or DEPRECATED_BUILDERS_KEY not in data:
        return data
    if BUILDERS_KEY in data:
        raise ValueError(
            f"`{DEPRECATED_BUILDERS_KEY}` and `{BUILDERS_KEY}` are both set; "
            f"`{DEPRECATED_BUILDERS_KEY}` is the deprecated name of `{BUILDERS_KEY}`, keep one"
        )
    return {(BUILDERS_KEY if k == DEPRECATED_BUILDERS_KEY else k): v for k, v in data.items()}


def _alias_limits(data: dict[str, Any]) -> dict[str, Any]:
    """`data` with the deprecated root key `limits` renamed to `global_limits`; a mapping
    that sets both spellings is refused."""
    if DEPRECATED_ROOT_KEY not in data:
        return data
    if "global_limits" in data:
        raise ValueError(
            f"`{DEPRECATED_ROOT_KEY}` and `global_limits` are both set; "
            f"`{DEPRECATED_ROOT_KEY}` is the deprecated name of `global_limits`, keep one"
        )
    renamed = dict(data)
    renamed["global_limits"] = renamed.pop(DEPRECATED_ROOT_KEY)
    return renamed


class AutoLandConfig(Frozen):
    """The track record a class needs before it counts as proven."""

    min_samples: int = Field(default=20, ge=1)
    min_clean_rate: float = Field(default=0.95, ge=0, le=1)
    # Whether a unit whose e2e result was deferred to verify may still reach `auto`.
    allow_deferred_e2e: bool = False
    # The classes the pipeline may merge without a person; empty turns landing off.
    classes: list[str] = []


class AuditConfig(Frozen):
    """The share of landed units a person is asked to look at afterwards."""

    sample_rate: float = Field(default=0.1, ge=0, le=1)


class DemotionConfig(Frozen):
    """When a class stops landing: the recent outcomes counted and the agreement they need."""

    window: int = Field(default=30, ge=1)
    min_agreement: float = Field(default=0.9, ge=0, le=1)


class CeilingsConfig(Frozen):
    """The changed-lines ceiling of a unit for each review tier."""

    auto: int = 5000
    light: int = 2000
    full: int = 750


def _check_ceilings(
    label: str,
    ceilings: CeilingsConfig,
    check_floor: bool,
    floor: int,
    owned: frozenset[str] | None = None,
) -> None:
    """Raise unless `auto` >= `light` >= `full`, and `full` is above `floor` when `check_floor`.
    With `owned`, a pair is checked only when one of its tiers is in it: a repo is not blamed
    for a relation between two values it inherits."""
    if (owned is None or {"auto", "light"} & owned) and ceilings.auto < ceilings.light:
        raise ValueError(
            f"{label}: auto ({ceilings.auto}) must not be below light ({ceilings.light})"
        )
    if (owned is None or {"light", "full"} & owned) and ceilings.light < ceilings.full:
        raise ValueError(
            f"{label}: light ({ceilings.light}) must not be below full ({ceilings.full})"
        )
    if check_floor and ceilings.full <= floor:
        raise ValueError(f"{label}: full ({ceilings.full}) must exceed min_unit_lines ({floor})")


# Lines the reviewer model can read in one unit; a buffered `auto` ceiling must stay under it.
REVIEWER_READING_LIMIT = 10_000


def buffered(ceiling: int, buffer: float) -> int:
    """A ceiling with the verdict's allowance on top."""
    return round(ceiling * (1 + buffer))


class ReviewConfig(Frozen):
    """The review policy: which changes never land without a person, and how they are classed."""

    # Off, every unit is held to the `full` ceiling and nothing is classified or recorded.
    enabled: bool = True
    # Globs added to the framework's defaults; a repo's own list adds to these.
    protected_paths: list[str] = []
    protected_defaults: bool = True
    # Class name to path globs, in the order that decides which class a unit belongs to.
    classes: dict[str, list[str]] = {}
    auto_land: AutoLandConfig = AutoLandConfig()
    audit: AuditConfig = AuditConfig()
    demotion: DemotionConfig = DemotionConfig()
    # Changed lines one unit may carry, by the review tier it is expected to get.
    ceilings: CeilingsConfig = CeilingsConfig()
    # The allowance over a tier's ceiling that only the verdict uses.
    ceiling_buffer: float = Field(default=0.2, ge=0, le=1)
    # How many times one unit's lineage may be split.
    split_rounds: int = Field(default=2, ge=0, le=2)
    # Whether a pull request body opens with the "Start here" section, and the review asks for it.
    brief: bool = True

    @field_validator("classes")
    @classmethod
    def _no_slash_in_a_class_name(cls, classes: dict[str, list[str]]) -> dict[str, list[str]]:
        for name in classes:
            if "/" in name:
                raise ValueError(
                    f"the class name {name!r} contains a slash; `<repo>/<kind>` names are the "
                    "framework's own"
                )
        return classes

    @model_validator(mode="after")
    def _listed_classes_are_known(self) -> ReviewConfig:
        for name in self.auto_land.classes:
            if name not in self.classes:
                raise ValueError(
                    f"auto_land.classes: {name!r} is not a class named in review.classes"
                )
        return self


class WorkspaceConfig(Frozen):
    version: int = 1
    planning: PlanningConfig = PlanningConfig()
    openspec: OpenSpecConfig = OpenSpecConfig()
    git: GitConfig = GitConfig()
    retention: RetentionConfig = RetentionConfig()
    # The agent runtime (runtimes/) every call runs on; ABK_RUNTIME overrides it.
    runtime: str = runtimes.DEFAULT
    # Per-runtime facts, only the selected runtime's demanded.
    runtimes: dict[str, RuntimeConfig] = {}
    tests: RuntimeTestsConfig = RuntimeTestsConfig()
    models: ModelsConfig = ModelsConfig()
    # The workspace-wide limits; a root `limits` key is read as this one (see _limits_alias).
    global_limits: LimitsConfig = LimitsConfig()
    # The scheduling settings, read once for every project.
    project_limits: ProjectLimitsConfig = ProjectLimitsConfig()
    builders: BuildersConfig = BuildersConfig()
    context: ContextConfig = ContextConfig()
    tracks: TracksConfig = TracksConfig()
    # Ordered: a task group's `[repo]` tag must be one of these keys.
    repos: dict[str, RepoConfig] = {}
    verify: VerifyConfig = VerifyConfig()
    # Names of environment variables whose values are secret, for text that
    # leaves a run (redaction.py).
    redact: list[str] = []
    # The cards that tell a person a unit waits on them; off by default.
    notifications: NotificationsConfig = NotificationsConfig()
    # How the pipeline's own environment is kept current; None manages none.
    environment: EnvironmentConfig | None = None
    # Per agent role (`build`, `review`), whether its nodes continue the role's
    # latest session. A role the mapping does not name is off.
    session_reuse: dict[str, bool] = {"build": True, "review": False}
    review: ReviewConfig = ReviewConfig()
    # Off by default: no step runs confined until an installation turns it on.
    sandbox: SandboxConfig = SandboxConfig()

    @model_validator(mode="before")
    @classmethod
    def _limits_alias(cls, data: object) -> object:
        """`limits` at the root is the deprecated spelling of `global_limits`; a scheduling
        setting left in either is refused with the pointer to `project_limits`."""
        if not isinstance(data, dict):
            return data
        _refuse_moved_settings(data)
        return _alias_limits(data)

    def generated_file_patterns(self) -> tuple[str, ...]:
        """The patterns left out of a unit's size: the configured ones and the
        lock files the planning and repository environments name. A lock file
        is matched by its file name, wherever it sits: its path is relative to
        the environment's own root, which a diff path is not."""
        environments = [self.environment] + [repo.environment for repo in self.repos.values()]
        return (
            *self.global_limits.generated_files,
            *(PurePosixPath(path).name for env in environments if env for path in env.inputs.lock),
        )

    def reuses_session(self, role: str) -> bool:
        """Whether `role`'s nodes continue the role's latest session. A role
        `session_reuse` does not name is off."""
        return self.session_reuse.get(role, False)

    @model_validator(mode="after")
    def _session_reuse_roles(self) -> WorkspaceConfig:
        """Only the build role may continue a session: a review must judge the
        branch fresh, not through the builder's or an earlier round's eyes."""
        for role, reuse in self.session_reuse.items():
            if role not in SESSION_REUSE_ROLES:
                raise ValueError(
                    f"session_reuse.{role}: unknown role; the roles are "
                    f"{', '.join(SESSION_REUSE_ROLES)}"
                )
            if role == "review" and reuse:
                raise ValueError(
                    "session_reuse.review: a review never continues a session; leave it false"
                )
        return self

    @model_validator(mode="before")
    @classmethod
    def _runtime_lists_are_gone(cls, data: object) -> object:
        """The runtime lists were replaced by `tests.e2e_splits`; refuse each naming the
        setting that replaces it."""
        if not isinstance(data, dict):
            return data
        blocks = {"tests": data.get("tests")}
        for key, repo in (data.get("repos") or {}).items():
            if isinstance(repo, dict):
                blocks[f"repos.{key}.tests"] = repo.get("tests")
        for where, block in blocks.items():
            if not isinstance(block, dict):
                continue
            for setting, replacement in REPLACED_RUNTIME_LISTS.items():
                if setting in block:
                    raise ValueError(f"{where}.{setting}: replaced by {replacement}")
        return data

    @model_validator(mode="after")
    def _e2e_splits_declared_well(self) -> WorkspaceConfig:
        """Each split has a valid name and one marker no other split has; `rest` has none."""
        maps = {"tests.e2e_splits": self.tests.e2e_splits}
        for key, repo in self.repos.items():
            if repo.tests.e2e_splits is not None:
                maps[f"repos.{key}.tests.e2e_splits"] = repo.tests.e2e_splits
        for setting, splits in maps.items():
            seen: dict[str, str] = {}
            for name, entry in splits.items():
                if name == BASE_GROUP:
                    raise ValueError(
                        f"{setting}: {name!r} is reserved as the older name of `{REST_SPLIT}`; "
                        "name the split something else"
                    )
                if not SPLIT_NAME.fullmatch(name):
                    raise ValueError(
                        f"{setting}: {name!r} is not a split name; use lowercase letters, "
                        "digits and underscores"
                    )
                if name == REST_SPLIT:
                    if entry.marker is not None:
                        raise ValueError(
                            f"{setting}.{name}.marker: {entry.marker!r}: `rest` is the tests "
                            "of no other split and takes no marker"
                        )
                    if entry.hold is None and entry.gate is None:
                        raise ValueError(
                            f"{setting}.{name}: empty; set `hold` or `gate`, or leave it out"
                        )
                    continue
                if not entry.marker:
                    raise ValueError(
                        f"{setting}.{name}.marker: {entry.marker!r}: a split needs one"
                    )
                if entry.marker in seen:
                    raise ValueError(
                        f"{setting}.{name}.marker: {entry.marker!r} is also the marker of "
                        f"{seen[entry.marker]}"
                    )
                seen[entry.marker] = name
        return self

    @model_validator(mode="before")
    @classmethod
    def _max_unit_lines_agrees_with_full_ceiling(cls, data: Any) -> Any:
        """Both the deprecated `global_limits.max_unit_lines` and `review.ceilings.full` set to
        different values are refused (`workspace_full_ceiling` reads the one that is set)."""
        if not isinstance(data, dict):
            return data
        limits, review = data.get("global_limits"), data.get("review") or {}
        if not isinstance(limits, dict) or "max_unit_lines" not in limits:
            return data
        if not isinstance(review, dict):
            return data
        ceilings = review.get("ceilings") or {}
        if not isinstance(ceilings, dict):
            return data
        old = limits["max_unit_lines"]
        if "full" in ceilings and ceilings["full"] != old:
            raise ValueError(
                f"{DEPRECATED_MAX_UNIT_LINES} ({old}) and review.ceilings.full "
                f"({ceilings['full']}) disagree; set only review.ceilings.full"
            )
        return data

    @model_validator(mode="after")
    def _ceilings_ordered_above_floor(self) -> WorkspaceConfig:
        """`auto` at least `light`, `light` at least `full`, `full` above the floor, for the
        workspace and for the ceilings in effect for each repo."""
        floor = self.global_limits.min_unit_lines
        ceilings = self.review.ceilings
        _check_ceilings("review.ceilings", ceilings, "full" in ceilings.model_fields_set, floor)
        if "full" not in ceilings.model_fields_set and workspace_full_ceiling(self) <= floor:
            raise ValueError(
                f"max_unit_lines ({workspace_full_ceiling(self)}) must exceed "
                f"min_unit_lines ({floor})"
            )
        for name, repo in self.repos.items():
            own = repo.review.ceilings
            owned = frozenset(
                tier for tier in CeilingsConfig.model_fields if getattr(own, tier) is not None
            )
            if owned:
                _check_ceilings(
                    f"repos.{name}.review.ceilings",
                    ceilings_in_effect(repo, self),
                    "full" in owned,
                    floor,
                    owned,
                )
        buffer = self.review.ceiling_buffer
        for label, scope in [("review.ceilings", None), *self.repos.items()]:
            auto = ceilings_in_effect(scope, self).auto
            if buffered(auto, buffer) >= REVIEWER_READING_LIMIT:
                where = label if scope is None else f"repos.{label}.review.ceilings"
                raise ValueError(
                    f"{where}: auto ceiling {auto} with ceiling_buffer {buffer} reaches the "
                    f"reviewer's reading limit of {REVIEWER_READING_LIMIT}"
                )
        return self

    @model_validator(mode="after")
    def _e2e_dimensions_declared_well(self) -> WorkspaceConfig:
        """A marker belongs to one value or split of a repo, and `e2e_available` names only
        dimensions and values some scope declares."""
        checked = [("tests", self.tests.e2e_dimensions, _splits_of(self.tests.e2e_splits))]
        checked += [
            (
                f"repos.{key}.tests" if repo.tests.e2e_dimensions is not None else "tests",
                e2e_dimensions(repo, self),
                e2e_splits(repo, self),
            )
            for key, repo in self.repos.items()
        ]
        for setting, dimensions, splits in checked:
            seen = {s.marker: f"split {s.name!r}" for s in splits if s.marker}
            for dimension, values in dimensions.items():
                for value, entry in values.items():
                    if entry.marker in seen:
                        raise ValueError(
                            f"{setting}.e2e_dimensions.{dimension}.{value}.marker: "
                            f"{entry.marker!r} is also the marker of {seen[entry.marker]}"
                        )
                    seen[entry.marker] = f"{dimension}={value}"
        declared: dict[str, set[str]] = {}
        scopes = [self.tests.e2e_dimensions]
        scopes += [r.tests.e2e_dimensions for r in self.repos.values() if r.tests.e2e_dimensions]
        for scope in scopes:
            for dimension, values in scope.items():
                declared.setdefault(dimension, set()).update(values)
        for dimension, wanted in self.tests.e2e_available.items():
            if dimension not in declared:
                raise ValueError(
                    f"tests.e2e_available.{dimension}: no such dimension in `e2e_dimensions` "
                    f"(declared: {', '.join(sorted(declared)) or 'none'})"
                )
            for value in wanted:
                if value not in declared[dimension]:
                    raise ValueError(
                        f"tests.e2e_available.{dimension}: {value!r} is not a declared value "
                        f"(declared: {', '.join(sorted(declared[dimension]))})"
                    )
        return self

    @model_validator(mode="after")
    def _usage_limits_only_on_claude(self) -> WorkspaceConfig:
        """The usage windows are Claude's. Set on another runtime they would be
        read by nothing, which looks like a limit and is not one."""
        for name, entry in self.runtimes.items():
            if name != CLAUDE_CODE and "limits" in entry.model_fields_set:
                raise ValueError(
                    f"runtimes.{name}.limits: the usage thresholds belong to "
                    f"runtimes.{CLAUDE_CODE}, the only runtime with usage windows"
                )
        return self


# --- locating and loading ------------------------------------------------------


def _not_a_unit_worktree(found: Path) -> Path:
    """`found`, unless it is the abk.yaml of a unit worktree (a linked worktree on a branch
    shaped `<branch_prefix><change>/<n>`): that is no installation, so the pipeline worktree's
    file stands in, or there is an error when none is live. Any abk.yaml inside a unit worktree
    counts, and the prefix is the committed file's: the local overlay is not consulted."""
    from agent_build_kit.pipeline.planning_repo import common_dir, current_branch, git_dir
    from agent_build_kit.pipeline.planning_sync import read_pipeline_marker

    tree = found.parent
    own = git_dir(tree)
    common = common_dir(tree)
    if own is None or common is None or own == common:
        return found
    branch = current_branch(tree)
    prefix = (read_base(found).get("git") or {}).get("branch_prefix", GitConfig().branch_prefix)
    if not re.fullmatch(re.escape(prefix) + r"[^/]+/\d+", branch):
        return found
    live = read_pipeline_marker(tree)
    if live is not None and (live / CONFIG_FILENAME).is_file():
        return live.resolve() / CONFIG_FILENAME
    raise ConfigError(
        f"{tree} is a unit worktree, not an installation: pass --config, set {CONFIG_ENV}, "
        f"or run `abk install-timers` so the pipeline worktree is live"
    )


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
            return _not_a_unit_worktree(candidate / CONFIG_FILENAME)
    raise ConfigError(
        f"no {CONFIG_FILENAME} found in {here} or above it; pass --config, set "
        f"{CONFIG_ENV}, or run `abk init` to create one"
    )


def merge_local(base: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """`base` with `local` laid over it: two mappings merge key by key, anything else in
    `local` (a scalar, a list, a string, `null`) replaces the committed value whole."""
    merged = dict(base)
    for key, value in local.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_local(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_mapping(path: Path) -> dict[str, Any] | None:
    """The mapping the YAML file at `path` holds, or None when there is no file."""
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ConfigError(f"{path} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must hold a mapping at the top level")
    return raw


def overlay_path(path: Path) -> Path:
    """The local overlay that sits beside the abk.yaml at `path`."""
    return path.with_name(OVERLAY_FILENAME)


def read_base(path: Path) -> dict[str, Any]:
    """The committed file alone, parsed, without the overlay."""
    raw = _read_mapping(path)
    if raw is None:
        raise ConfigError(f"cannot read {path}: no such file")
    return raw


def read_overlay(path: Path) -> dict[str, Any] | None:
    """The overlay beside the abk.yaml at `path`, or None when there is none."""
    return _read_mapping(overlay_path(path))


def _holds(document: object, location: tuple[int | str, ...]) -> bool:
    for key in location:
        if isinstance(document, dict) and key in document:
            document = document[key]
        elif isinstance(document, list) and isinstance(key, int) and key < len(document):
            document = document[key]
        else:
            return False
    return True


def _value_at(document: object, location: tuple[int | str, ...]) -> object:
    for key in location:
        document = document[key]  # type: ignore[index]
    return document


def _files_of(
    error: ValidationError, path: Path, base: dict[str, Any], local: dict[str, Any] | None
) -> list[Path]:
    """The files a failing key path comes from: the overlay alone when it replaced the value
    whole, else each that holds the path, else every file read."""
    named: list[Path] = []
    for found in error.errors():
        location = tuple(found["loc"])
        holders = [
            file
            for file, document in ((path, base), (overlay_path(path), local))
            if document is not None and _holds(document, location)
        ]
        if local is not None and overlay_path(path) in holders:
            if not isinstance(_value_at(local, location), dict):
                holders = [overlay_path(path)]
        for file in holders or [path, *([overlay_path(path)] if local is not None else [])]:
            if file not in named:
                named.append(file)
    return named


class _SettingBlock(Frozen):
    """A block of a document that holds test-kind settings."""

    # The keys that lead to the block from the root of the document.
    path: tuple[str, ...]
    block: dict[str, Any]
    # The model that reads the block.
    model: type[Frozen]

    @property
    def where(self) -> str:
        return ".".join(self.path)


def _setting_blocks(document: dict[str, Any]) -> list[_SettingBlock]:
    """The blocks of `document` that hold test-kind settings."""
    limits_key = "global_limits" if "global_limits" in document else DEPRECATED_ROOT_KEY
    found: list[tuple[tuple[str, ...], Any, type[Frozen]]] = [
        ((limits_key,), document.get(limits_key), LimitsConfig),
        (("tests",), document.get("tests"), RuntimeTestsConfig),
    ]
    repos = document.get("repos")
    for name, repo in repos.items() if isinstance(repos, dict) else ():
        if isinstance(repo, dict):
            found.append((("repos", name, "tests"), repo.get("tests"), TestsConfig))
    return [
        _SettingBlock(path=path, block=block, model=model)
        for path, block, model in found
        if isinstance(block, dict)
    ]


def _with_block(document: dict[str, Any], path: tuple[str, ...], block: dict[str, Any]) -> dict:
    """A copy of `document` with the mapping at `path` replaced by `block`."""
    if not path:
        return block
    return {**document, path[0]: _with_block(document[path[0]], path[1:], block)}


def _raw_files(path: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """The file at `path` and its overlay, each as it parses, for those that parse to a mapping."""
    for file in (path, overlay_path(path)):
        try:
            raw = yaml.safe_load(file.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(raw, dict):
            yield file, raw


def _old_setting_keys(block: dict[str, Any], model: type[Frozen]) -> list[str]:
    """The keys of `block` that are old spellings of a setting `model` has."""
    aliases = {field.alias for field in model.model_fields.values() if field.alias}
    return [
        key
        for key in block
        if isinstance(key, str)
        and is_old_spelling(Place.SETTING, key)
        and new_spelling(Place.SETTING, key) in aliases
    ]


def read_new_settings(document: dict[str, Any]) -> dict[str, Any]:
    """`document` with each old test-kind settings key renamed to the new one; a block that
    sets both spellings of one setting is refused."""
    renamed = document
    for found in _setting_blocks(document):
        old = _old_setting_keys(found.block, found.model)
        if not old:
            continue
        for key in old:
            new = new_spelling(Place.SETTING, key)
            if new in found.block:
                raise ValueError(
                    f"{found.where}: `{key}` and `{new}` are both set; "
                    f"`{key}` is the deprecated name of `{new}`, keep one"
                )
        fixed = {
            new_spelling(Place.SETTING, k) if k in old else k: v for k, v in found.block.items()
        }
        renamed = _with_block(renamed, found.path, fixed)
    return renamed


def old_setting_blocks(document: dict[str, Any]) -> list[tuple[str, tuple[str, ...], set[str]]]:
    """The test-kind settings blocks of `document` that hold old key names: where each is, its
    path and its old keys. A block that sets both spellings of one setting raises `ValueError`."""
    read_new_settings(document)
    return [
        (found.where, found.path, set(old))
        for found in _setting_blocks(document)
        if (old := _old_setting_keys(found.block, found.model))
    ]


def _refuse_moved_settings(document: dict[str, Any]) -> None:
    """Refuse a scheduling setting left in the limits block, naming where it lives now."""
    for key in ("global_limits", DEPRECATED_ROOT_KEY):
        block = document.get(key)
        if not isinstance(block, dict):
            continue
        for name in MOVED_TO_PROJECT_LIMITS:
            if name in block:
                raise ValueError(
                    f"{key}.{name}: moved to project_limits.{name}; `abk config --migrate` moves it"
                )
        # A project setting that never lived there: refused with where it belongs, and no
        # migration to offer.
        for name in ProjectLimitsConfig.model_fields.keys() - set(MOVED_TO_PROJECT_LIMITS):
            if name in block:
                raise ValueError(
                    f"{key}.{name}: a project setting, set it in project_limits.{name}"
                )


def _renamed(document: dict[str, Any] | None, file: Path) -> dict[str, Any] | None:
    """`document` with the deprecated root key and the old test-kind settings keys renamed, so
    two files that spell them differently still merge; one file that sets both spellings is
    refused."""
    if document is None:
        return None
    try:
        _refuse_moved_settings(document)
        renamed = read_new_settings(_alias_limits(document))
        if isinstance(renamed.get("builders"), dict):
            renamed = {**renamed, "builders": rename_builders_key(renamed["builders"])}
        return renamed
    except ValueError as error:
        raise ConfigError(f"{file}: {error}") from error


def load(path: Path) -> WorkspaceConfig:
    spelled = read_base(path), read_overlay(path)
    raw = _renamed(spelled[0], path)
    local = _renamed(spelled[1], overlay_path(path))
    assert raw is not None
    for key in _committed_config_dirs(raw):
        raise ConfigError(
            f"{path}: {key}: a machine path is never committed; "
            "set it in the machine-local overlay beside this file"
        )
    merged = raw if local is None else merge_local(raw, local)
    try:
        loaded = WorkspaceConfig.model_validate(merged)
    except ValidationError as error:
        message = str(error)
        if any(document and DEPRECATED_ROOT_KEY in document for document in spelled):
            # Name a setting as the file spells it.
            message = re.sub(r"(?m)^global_limits\b", DEPRECATED_ROOT_KEY, message)
        if any(DEPRECATED_BUILDERS_SETTING in deprecations_of(document) for document in spelled):
            message = re.sub(rf"\b{BUILDERS_KEY}\b", DEPRECATED_BUILDERS_KEY, message)
        for document in spelled:
            for found in _setting_blocks(document or {}):
                for old in _old_setting_keys(found.block, found.model):
                    message = re.sub(rf"\b{new_spelling(Place.SETTING, old)}\b", old, message)
        files = [str(file) for file in _files_of(error, path, raw, local)]
        verb = "does" if len(files) == 1 else "do"
        raise ConfigError(
            f"{' and '.join(files)} {verb} not match the schema:\n{message}"
        ) from error
    _check_runtime(loaded, path)
    _check_forges(loaded, path)
    _check_infra(loaded, path)
    _check_agent_commands(loaded, path)
    return loaded


def deprecations_of(*documents: dict[str, Any] | None) -> list[str]:
    """The deprecated keys the parsed `documents` set: the root `limits` key, `max_unit_lines`
    under `global_limits` or `limits`, and `builders.per_group_commits`; each once."""
    raws = [raw for raw in documents if raw]
    found = []
    if any(DEPRECATED_ROOT_KEY in raw for raw in raws):
        found.append(DEPRECATED_ROOT_KEY)
    blocks = [raw.get(name) for raw in raws for name in ("global_limits", DEPRECATED_ROOT_KEY)]
    if any(isinstance(block, dict) and "max_unit_lines" in block for block in blocks):
        found.append(DEPRECATED_MAX_UNIT_LINES)
    builders = [raw.get("builders") for raw in raws]
    if any(isinstance(block, dict) and DEPRECATED_BUILDERS_KEY in block for block in builders):
        found.append(DEPRECATED_BUILDERS_SETTING)
    return found


def deprecations(path: Path) -> list[str]:
    """The deprecated keys the file at `path`, or its overlay, sets; each once."""
    return deprecations_of(*(raw for _, raw in _raw_files(path)))


def _merged_raw(path: Path) -> dict[str, Any]:
    """The file at `path` with its overlay laid over it, as they parse (no validation)."""
    merged: dict[str, Any] = {}
    for _, raw in _raw_files(path):
        merged = merge_local(merged, raw)
    return merged


def runtime_for(path: Path) -> str:
    """The runtime in force for the file at `path`: this machine's `ABK_RUNTIME`, then the
    `runtime` of the file with its overlay laid over it, then the default runtime."""
    from agent_build_kit.settings import settings

    return settings.runtime or _merged_raw(path).get("runtime") or runtimes.DEFAULT


class ModelsNotice(Frozen):
    """A deprecation notice for a flat `models:` block, and what to do about it: the command when
    the block is in the abk.yaml `--migrate` edits, a hand edit when it is in the overlay."""

    text: str
    fix: str


def models_notices(path: Path) -> list[ModelsNotice]:
    """The notice for a flat top-level `models:` block in the file at `path` or its overlay: it
    names the runtime in force's block to move it to, and the roles that block also sets in the
    file with its overlay (the runtime's value is the one used). `abk config --migrate` edits
    the file alone, so a block in the overlay is to be moved by hand."""
    name = runtime_for(path)
    own = ((_merged_raw(path).get("runtimes") or {}).get(name) or {}).get("models") or {}
    notices: list[ModelsNotice] = []
    for file, raw in _raw_files(path):
        flat = raw.get("models")
        if not flat:
            continue
        if file == path:
            move, fix = "`abk config --migrate` moves it there", "run `abk config --migrate`"
        else:
            move = f"move it there by hand, in {file}"
            fix = "move it by hand in the file the warning names"
        notice = f"`models` is deprecated for `runtimes.{name}.models`; {move}"
        both = [role for role in flat if role in own]
        if both:
            notice += f"; {', '.join(both)} set in both, the runtime's value is used"
        notices.append(ModelsNotice(text=notice, fix=fix))
    return notices


def old_setting_notices(path: Path) -> list[str]:
    """One notice for each old test-kind settings key in the file at `path` or its overlay."""
    notices: list[str] = []
    for file, raw in _raw_files(path):
        for found in _setting_blocks(raw):
            notices += [
                notice(Place.SETTING, key, f"{file}: {found.where}")
                for key in _old_setting_keys(found.block, found.model)
            ]
    return notices


def _check_infra(config: WorkspaceConfig, path: Path) -> None:
    """An unknown infrastructure profile fails here, naming the registered ones."""
    for name, repo in config.repos.items():
        try:
            infra.get(repo.infra)
        except KeyError as error:
            raise ConfigError(f"{path}: repo {name!r}: {error.args[0]}") from None


def _check_agent_commands(config: WorkspaceConfig, path: Path) -> None:
    """An `agent_commands` list with a command the build allow-list refuses fails here,
    naming the repo, the position, the command and the list."""
    from agent_build_kit.pipeline import agent_commands

    for name, repo in config.repos.items():
        if repo.agent_commands is None:
            continue
        try:
            outside = agent_commands.refused(repo)
        except KeyError:
            continue  # an unknown profile is reported where the repo is, as without the key
        for index, line in outside:
            raise ConfigError(
                f"{path}: repo {name!r}: agent_commands[{index}] `{line}` is not allowed to a "
                f"build agent; the allow-list is {agent_commands.allow_list(repo)}"
            )


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


def _expanded(path: Path) -> Path:
    return path.expanduser()


_active_checkout: Callable[[Path], Path] = _expanded


def activate(
    config: WorkspaceConfig,
    root: Path | None = None,
    checkout: Callable[[Path], Path] = _expanded,
) -> None:
    """`checkout` turns a repo's configured path into its checkout (the installation's rule)."""
    global _active, _active_root, _active_checkout
    _active, _active_root, _active_checkout = config, root, checkout


def active_checkout(configured: Path) -> Path:
    """The checkout a repo's configured path names in the active workspace, for a caller that
    holds a repo's config but no installation."""
    return _active_checkout(configured)


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
