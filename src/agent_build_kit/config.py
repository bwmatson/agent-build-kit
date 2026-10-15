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
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, ValidationError, ValidationInfo, field_validator, model_validator

from agent_build_kit import forges, infra, path_patterns, runtimes
from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import DEFAULT_KEYED_HEADERS, UpstreamKind
from agent_build_kit.runtimes import known_agents

CONFIG_FILENAME = "abk.yaml"
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


class OpenSpecConfig(Frozen):
    # The command that runs the OpenSpec CLI, when it is not the default
    # `npx --yes @fission-ai/openspec@<settings.openspec_version>`.
    command: list[str] | None = None


class RetentionConfig(Frozen):
    """How long the files the pipeline writes for diagnosis are kept."""

    # The decision log's size, in megabytes; past it the oldest lines are dropped.
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


class UsageWindowConfig(Frozen):
    """How full one usage window may get before the pipeline stops starting
    units. The session and the week are both this, with the same names."""

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
    # Points of this window one unit may spend, counted for each unit that has spent since
    # the last reading or started on an estimate. `auto` (the default) calibrates it from the
    # recorded history and falls back to 10 for the session and 2 for the weekly: a unit costs
    # a larger share of the five-hour window than of the week. A number is the fallback and the
    # cap on the calibrated figure.
    usage_unit_allowance_pct: Annotated[int, Field(ge=0)] | Literal["auto"] = "auto"
    # The least a calibrated allowance of this window may be, in points per unit.
    usage_allowance_floor_pct: Annotated[int, Field(ge=0)] = 1

    @property
    def usage_ceiling_pct(self) -> int:
        """The ceiling as it applies: the pause percent when unset."""
        ceiling = self.usage_pause_ceiling_pct
        return self.usage_pause_pct if ceiling is None else ceiling

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

    @model_validator(mode="after")
    def _ceiling_not_below_pause(self) -> UsageWindowConfig:
        """A ceiling under the pause percent would make the threshold *fall* as
        a reset approaches, which is the opposite of what it is for."""
        if self.usage_ceiling_pct < self.usage_pause_pct:
            raise ValueError(
                f"usage_pause_ceiling_pct ({self.usage_ceiling_pct}) is below "
                f"usage_pause_pct ({self.usage_pause_pct})"
            )
        return self


class ClaudeLimitsConfig(Frozen):
    """The Claude subscription's two usage windows (`runtimes.claude_code.limits`).
    They fill independently, so each has its own section."""

    session: UsageWindowConfig = UsageWindowConfig()
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
        return self

    @model_validator(mode="before")
    @classmethod
    def _claude_cache_follows_cache(cls, data: object) -> object:
        """`usage_claude_cache_minutes` is `usage_cache_minutes` where it is not set."""
        if not isinstance(data, dict) or data.get("usage_claude_cache_minutes") is not None:
            return data
        default = cls.model_fields["usage_cache_minutes"].default
        return {**data, "usage_claude_cache_minutes": data.get("usage_cache_minutes", default)}


class RestackCheck(StrEnum):
    """How much of tier 1 a clean move of a unit's branch onto a moved base runs."""

    AFFECTED = "affected"
    FULL = "full"


class Tier2UnitScope(StrEnum):
    """How much of a repo's tier 2 marker a unit's tier 2 step runs."""

    OWN = "own"
    FULL = "full"


def tier2_unit_scope(repo: RepoConfig, limits: LimitsConfig) -> Tier2UnitScope:
    """The scope in effect for `repo`: its own `tests.tier2_unit_scope` when set, else the
    `global_limits` one."""
    return repo.tests.tier2_unit_scope or limits.tier2_unit_scope


class Tier2Schedule(StrEnum):
    """How often a repo's whole tier 2 suite is due to run on its own."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    OFF = "off"


def tier2_schedule(repo: RepoConfig, limits: LimitsConfig) -> Tier2Schedule:
    """The schedule in effect for `repo`: its own `tests.tier2_schedule` when set, else the
    `limits` one."""
    return repo.tests.tier2_schedule or limits.tier2_schedule


def tier2_variants(repo: RepoConfig, config: WorkspaceConfig) -> tuple[str, ...]:
    """The groups a scheduled tier 2 run covers for `repo`: `base`, then the repo's own
    `tests.tier2_runtimes` when set, else the top-level `tests.tier2_runtimes`."""
    own = repo.tests.tier2_runtimes
    return (BASE_GROUP, *(config.tests.tier2_runtimes if own is None else own))


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


class ContextConfig(Frozen):
    """How a call's context window use is read (`context`)."""

    # A fall in the fill between two requests larger than this share of the window
    # is a compaction, for a runtime with no marker of its own.
    compaction_drop_share: float = 0.3
    # A step ending above this share of the window logs a warning.
    warn_share: float = 0.8


class LimitsConfig(Frozen):
    # Longest chain of in-review PRs from main to a branch that a unit may
    # start building on.
    stack_depth_build_cap: int = 3
    # Deepest a dependent may sit when a merge restacks it; one beyond it is
    # held until a later merge brings it within. Unset: the build cap's value.
    stack_depth_rebase_cap: int | None = None
    # How many units are implemented at once, across all repos.
    max_concurrent_stacks: int = 4
    # How many restacks (moving a unit's branch onto a changed base) run at once, across
    # all repos, in a lane apart from the build workers: a restack takes no build slot.
    max_concurrent_restacks: Annotated[int, Field(ge=1)] = 2
    # Most tests that may fail a run's first pass and pass the serial rerun before the run
    # is recorded as one flake storm (a disturbed host), with no fix change per test.
    max_flakes_per_run: Annotated[int, Field(ge=1)] = 5
    # Seconds after a push in which a pull request with no checks yet still reads
    # `checking`: CI may not have registered.
    checks_register_seconds: int = 120
    # How many units may be started and not finished at once, across all repos.
    # At it no unit that has never started does; what drains the queue
    # (finishing, rework, resuming, a further review round) still runs.
    max_units_in_progress: Annotated[int, Field(ge=1)] = 5
    # How many pull requests of finished units a round (each tick and each refresh of a
    # pass) takes their stale state label off, so a backlog does not spend the code
    # host's rate limit at once.
    label_sweep_per_tick: Annotated[int, Field(ge=1)] = 20
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
    # Longest a tier 1 command may run before it is asked to abort, in seconds.
    tier1_command_seconds: Annotated[float, Field(gt=0)] = 3600
    # How long an aborted tier 1 command has to exit before it is ended, in seconds.
    tier1_abort_grace_seconds: Annotated[float, Field(gt=0)] = 10
    # How many times the tests a unit added or changed are run again, under the same
    # load, after tier 1 passes; 0 turns the check off.
    tier1_repeat_runs: Annotated[int, Field(ge=0)] = 3
    # What tier 1 runs after a clean move onto a moved base: `affected` scopes it by the
    # files the move brought in, `full` runs the whole suite as before.
    restack_check: RestackCheck = RestackCheck.AFFECTED
    # Whether the untouched tests that fail tier 2 are run once on the base, to tell a
    # failure the unit caused from one already there; 0 turns the run off. A switch, not a
    # count: one run answers the question.
    tier2_base_runs: Annotated[int, Field(ge=0, le=1)] = 1
    # How much of a repo's tier 2 marker a unit's tier 2 step runs: `own` the tests its branch
    # added or changed, `full` the whole marker. A repo's `tests.tier2_unit_scope` wins.
    tier2_unit_scope: Tier2UnitScope = Tier2UnitScope.OWN
    # How often a repo's whole tier 2 suite is due to run on its own; a repo's
    # `tests.tier2_schedule` wins.
    tier2_schedule: Tier2Schedule = Tier2Schedule.WEEKLY
    tier2_schedule_off = field_validator("tier2_schedule", mode="before")(_unquoted_off)
    # Longest a unit waits for the tier 2 lock before its tier 2 step fails as busy, in seconds.
    tier2_lock_wait_seconds: Annotated[int, Field(gt=0)] = 5400
    # How many of a tier 2 run's slowest test entries the posted result lists; 0 lists every one.
    tier2_durations_shown: Annotated[int, Field(ge=0)] = 15
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
    def _ceiling_above_floor(self) -> LimitsConfig:
        """A floor at or above the ceiling is a unit size no plan can meet."""
        if self.max_unit_lines <= self.min_unit_lines:
            raise ValueError(
                f"max_unit_lines ({self.max_unit_lines}) must exceed "
                f"min_unit_lines ({self.min_unit_lines})"
            )
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


class TestsConfig(Frozen):
    # Extra packages the repo-root tests (outside every workspace member) need.
    root_extras: list[str] = []
    # The pytest marker on tests that need the real local stack (tier 2).
    tier2_marker: str = "local_stack"
    # This repo's tier 2 scope; None follows `global_limits.tier2_unit_scope`.
    tier2_unit_scope: Tier2UnitScope | None = None
    # This repo's schedule; None follows `limits.tier2_schedule`.
    tier2_schedule: Tier2Schedule | None = None
    tier2_schedule_off = field_validator("tier2_schedule", mode="before")(_unquoted_off)
    # The marker on tier-2 tests only the dev stack can run (left out of live checks).
    dev_stack_marker: str = "dev_stack"
    # Record and replay of the calls tier-2 tests make outside the stack; None: none.
    replay: ReplayConfig | None = None
    # The runtimes this repo's scheduled tier 2 runs besides the base group; None follows
    # the top-level `tests.tier2_runtimes`.
    tier2_runtimes: list[str] | None = None


# The group of tier 2 tests that carry no runtime tag; reserved, so no runtime has this name.
BASE_GROUP = "base"


class RuntimeTestsConfig(Frozen):
    """The installation-wide `tests` block: which runtimes' tests are left out, kept in, and
    run by the schedule."""

    runtimes_blocked: list[str] = []
    runtimes_allowed: list[str] = []
    tier2_runtimes: list[str] = []


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
    dev_stack: DevStackConfig | None = None
    deploy: DeployConfig = DeployConfig()
    # Where the repo keeps its changelog; None switches the changelog convention
    # and check off for this repo.
    changelog: str | None = "CHANGELOG.md"
    # How this repo's environment is kept current in a unit's worktree.
    environment: EnvironmentConfig | None = None


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


def deprecation_notice(key: str) -> str:
    """What `abk config` and `abk doctor` say of a deprecated root key."""
    return (
        f"`{key}` is deprecated for `global_limits`; "
        "`abk config --migrate` moves it to the new names"
    )


class BuildersConfig(Frozen):
    """What a builder run may do beyond writing files (`builders`)."""

    # Base names `abk install-config` may install, besides `.pre-commit-config.yaml`.
    installable_files: list[str] = []

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

    @model_validator(mode="before")
    @classmethod
    def _limits_alias(cls, data: object) -> object:
        """`limits` at the root is the deprecated spelling of `global_limits`."""
        if not isinstance(data, dict) or DEPRECATED_ROOT_KEY not in data:
            return data
        if "global_limits" in data:
            raise ValueError(
                f"`{DEPRECATED_ROOT_KEY}` and `global_limits` are both set; "
                f"`{DEPRECATED_ROOT_KEY}` is the deprecated name of `global_limits`, keep one"
            )
        renamed = dict(data)
        renamed["global_limits"] = renamed.pop(DEPRECATED_ROOT_KEY)
        return renamed

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

    @model_validator(mode="after")
    def _tier2_runtime_lists(self) -> WorkspaceConfig:
        """Each list names known runtimes once, and no runtime is blocked and allowed."""
        lists = {
            f"tests.{name}": getattr(self.tests, name)
            for name in ("runtimes_blocked", "runtimes_allowed", "tier2_runtimes")
        }
        for key, repo in self.repos.items():
            if repo.tests.tier2_runtimes is not None:
                lists[f"repos.{key}.tests.tier2_runtimes"] = repo.tests.tier2_runtimes
        if not any(lists.values()):
            # Nothing to check, and the default config is built while this module loads,
            # before the runtime registry can be imported.
            return self
        known = sorted(known_runtime_names(self.runtimes))
        for setting, names in lists.items():
            for name in names:
                if name not in known:
                    raise ValueError(
                        f"{setting}: {name!r} is not a runtime; the runtimes are {', '.join(known)}"
                    )
            if len(set(names)) != len(names):
                raise ValueError(
                    f"{setting}: a runtime is named twice; the runtimes are {', '.join(known)}"
                )
        both = set(self.tests.runtimes_blocked) & set(self.tests.runtimes_allowed)
        if both:
            raise ValueError(
                f"{', '.join(sorted(both))} is in both tests.runtimes_blocked and "
                "tests.runtimes_allowed; keep it in one"
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


def merge_local(base: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def read_base(path: Path) -> dict[str, Any]:
    raise NotImplementedError


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
        message = str(error)
        if DEPRECATED_ROOT_KEY in raw and "global_limits" not in raw:
            # Name a setting as the file spells it.
            message = re.sub(r"(?m)^global_limits\b", DEPRECATED_ROOT_KEY, message)
        raise ConfigError(f"{path} does not match the schema:\n{message}") from error
    _check_runtime(loaded, path)
    _check_forges(loaded, path)
    _check_infra(loaded, path)
    return loaded


def deprecations(path: Path) -> list[str]:
    """The root keys of the file at `path` that are deprecated spellings."""
    try:
        raw = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return []
    return [DEPRECATED_ROOT_KEY] if isinstance(raw, dict) and DEPRECATED_ROOT_KEY in raw else []


def _check_infra(config: WorkspaceConfig, path: Path) -> None:
    """An unknown infrastructure profile fails here, naming the registered ones."""
    for name, repo in config.repos.items():
        try:
            infra.get(repo.infra)
        except KeyError as error:
            raise ConfigError(f"{path}: repo {name!r}: {error.args[0]}") from None


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
