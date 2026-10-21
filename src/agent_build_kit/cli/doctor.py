"""`abk doctor`: is this installation in a state the pipeline can run in?

Each check prints `ok`, `warn` or `FAIL` with a one-line fix. A FAIL is
something a tick would trip over — a repo that is not there, an account
`gh` cannot act as, a CLI that does not run. A warn is drift: the rules in
`openspec/config.yaml` behind the framework's, an abk.yaml that no longer
matches the checkouts, a stale skill. Everything external is injectable, so
the checks are tested against recorded answers rather than this machine.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
import shutil
import socket
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import yaml

from agent_build_kit import (
    __version__,
    config,
    forges,
    openspec,
    profiles,
    runtimes,
    skills,
    timers,
)
from agent_build_kit import settings as settings_module
from agent_build_kit.config import (
    OVERLAY_FILENAME,
    CommandProvider,
    ConfigError,
    EnvironmentConfig,
    NotificationProvider,
    PlanningPublish,
    PolicyMarker,
    RepoConfig,
    WorkspaceConfig,
    read_base,
)
from agent_build_kit.forges.transport import (
    Transport,
    TransportError,
    credential_for,
    page_excerpt,
)
from agent_build_kit.init.detect import DEV_STACK_SCRIPT, detect_repo
from agent_build_kit.init.scaffold import (
    RULES_CHANGES,
    RULES_VERSION,
    merge_attribute,
    missing_state_ignores,
    rules_version,
)
from agent_build_kit.installation import Installation, _resolve, load_config
from agent_build_kit.model import Frozen
from agent_build_kit.notify.windows import (
    BURNTTOAST_VERSION,
    INSTALL_COMMAND,
    MODULE_CHECK_COMMAND,
)
from agent_build_kit.path_patterns import matches, normalize
from agent_build_kit.pipeline import agent_commands
from agent_build_kit.pipeline.e2e import dimension_lines
from agent_build_kit.pipeline.e2e_holds import HELD_FILE, current_holds, hold_text
from agent_build_kit.pipeline.environment import matched_inputs
from agent_build_kit.pipeline.gate_holds import gate_standing, split_gates
from agent_build_kit.pipeline.original_copy import COPY_PATTERN
from agent_build_kit.pipeline.pending import describe, pending_projects
from agent_build_kit.pipeline.planning_repo import common_dir, is_worktree_of
from agent_build_kit.pipeline.planning_sync import (
    in_repo_name,
    live_notice,
    read_pipeline_marker,
)
from agent_build_kit.pipeline.shell import git, git_out
from agent_build_kit.pipeline.usage_guard import gate_result
from agent_build_kit.profiles.base import ProfileUnsupported
from agent_build_kit.redaction import MIN_LENGTH
from agent_build_kit.redaction import active as active_redactor
from agent_build_kit.replay.review import directories, overdue, waiting
from agent_build_kit.runtimes import claude_code, policy_check, providers
from agent_build_kit.runtimes.base import AgentRuntime, Run, Which, account_report_of
from agent_build_kit.scrub_terms import ROOT_HOME, TILDE_HOME
from agent_build_kit.settings import settings

Status = Literal["ok", "info", "warn", "FAIL"]


class Check(Frozen):
    name: str
    status: Status
    detail: str
    fix: str = ""


def _ok(name: str, detail: str) -> Check:
    return Check(name=name, status="ok", detail=detail)


def _info(name: str, detail: str, fix: str = "") -> Check:
    """Something worth knowing that is not a problem: it neither fails the run
    nor counts as a warning."""
    return Check(name=name, status="info", detail=detail, fix=fix)


def _warn(name: str, detail: str, fix: str) -> Check:
    return Check(name=name, status="warn", detail=detail, fix=fix)


def _fail(name: str, detail: str, fix: str) -> Check:
    return Check(name=name, status="FAIL", detail=detail, fix=fix)


# --- checks ------------------------------------------------------------------------


def _repos(inst: Installation, run: Run) -> list[Check]:
    checks = []
    for name in inst.repos:
        path = inst.checkouts[name]
        if not path.is_dir():
            checks.append(_fail(f"repo {name}", f"{path} does not exist", "fix `path` in abk.yaml"))
            continue
        if not (path / ".git").exists():
            checks.append(
                _fail(f"repo {name}", f"{path} is not a git checkout", "clone the repo there")
            )
            continue

        def identity(field: str, *, local: bool = False, at: Path = path) -> str:
            argv = ["git", "config", *(["--local"] if local else []), "--get", f"user.{field}"]
            answered = run(argv, cwd=at, capture_output=True, text=True, check=False)
            return "" if answered.returncode else answered.stdout.strip()

        email, who = identity("email"), identity("name")
        if not email or not who:
            missing = " and ".join(f"user.{f}" for f in ("email", "name") if not identity(f))
            checks.append(
                _fail(
                    f"repo {name}",
                    f"git has no {missing} for {path}, so a commit would be attributed to nobody",
                    f"git config --global user.email <email> (and user.name), or "
                    f"git -C {path} config user.email <email> for this repo alone",
                )
            )
            continue
        # Which scope it resolves through, so a workspace whose repos belong to
        # different accounts can see that one identity is signing for all of them.
        scope = "repo-local" if identity("email", local=True) else "this machine's global"
        checks.append(_ok(f"repo {name}", f"{path}, commits as {email} ({scope})"))
    return checks


def _pending_projects(inst: Installation) -> list[Check]:
    """Projects registered but not built yet: information, never a problem."""
    return [
        _info(f"project {name}/{project.path}", describe(project))
        for name, repo in inst.repos.items()
        if inst.checkouts[name].is_dir()  # a missing repo is already a failure
        for project in pending_projects(inst.checkouts[name], repo.projects)
    ]


def _cassettes(inst: Installation) -> list[Check]:
    """Recordings waiting for review, for each repo that records: a note, or a warning when
    one has waited through more runs than `review_after_runs`."""
    checks = []
    for name, (directory, replay) in directories(inst.repos, inst.checkouts).items():
        if not (held := len(waiting(directory))):
            continue
        limit = replay.review_after_runs
        detail = f"{held} cassette(s) waiting for review"
        fix = "run `abk replay review`"
        if late := overdue(directory, limit):
            detail += f", {len(late)} through more than {limit} runs"
            checks.append(_warn(f"replay cassettes {name}", detail, fix))
        else:
            checks.append(_info(f"replay cassettes {name}", detail, fix))
    return checks


def _files_of_checkouts(inst: Installation) -> list[str] | None:
    """Every file the repos' checkouts hold that git does not ignore, tracked or not; None when
    one cannot be listed, so nothing is said about what it holds."""
    files: list[str] = []
    for path in inst.checkouts.values():
        if not path.is_dir():
            continue
        try:
            listed = git_out(path, "ls-files", "--cached", "--others", "--exclude-standard")
        except (OSError, subprocess.CalledProcessError):
            return None
        files += listed.splitlines()
    return files


def _review(inst: Installation) -> list[Check]:
    """The `review` section: a glob that does not parse is a failure, since it would make the
    verdict wrong; a glob matching no file in any repo, and policy set while `enabled` is
    false, are warnings."""
    review = inst.config.review
    globs: list[tuple[str, str]] = [("protected path", g) for g in review.protected_paths]
    globs += [
        (f"protected path of {name}", g)
        for name, repo in inst.repos.items()
        for g in repo.review.protected_paths
    ]
    globs += [(f"class {name}", g) for name, listed in review.classes.items() for g in listed]
    checks: list[Check] = []
    parsed: list[tuple[str, str]] = []
    for label, glob in globs:
        try:
            normalize(glob)
        except ValueError as error:
            checks.append(
                _fail(
                    f"review {label}",
                    f"{glob!r} does not parse: {error}",
                    "fix the glob in the `review` section of abk.yaml",
                )
            )
        else:
            parsed.append((label, glob))
    files = _files_of_checkouts(inst)
    for label, glob in parsed:
        if files is not None and not any(matches(glob, file) for file in files):
            checks.append(
                _warn(
                    f"review {label}",
                    f"{glob!r} matches no file in any repo",
                    "check the glob for a typo in the `review` section of abk.yaml",
                )
            )
    policy_set = bool(
        globs or not review.protected_defaults or review.auto_land != type(review.auto_land)()
    )
    if policy_set and not review.enabled:
        checks.append(
            _warn(
                "review enabled",
                "the `review` section sets policy but `enabled` is false, so none of it applies",
                "set `review.enabled: true`, or remove the policy",
            )
        )
    return checks


def _changelogs(inst: Installation) -> list[Check]:
    """A repo that names a changelog its checkout does not have is warned about."""
    checks = []
    for name, repo in inst.repos.items():
        path = inst.checkouts[name]
        if repo.changelog is None or not path.is_dir():
            continue
        if (path / repo.changelog).is_file():
            checks.append(_ok(f"changelog {name}", repo.changelog))
            attributes = path / ".gitattributes"
            text = attributes.read_text(errors="replace") if attributes.is_file() else ""
            merge = merge_attribute(text, repo.changelog)
            if merge is None:
                checks.append(
                    _warn(
                        f"changelog union merge {name}",
                        f"{repo.changelog} has no `merge=union` rule in {attributes}, so "
                        "concurrent entries conflict",
                        f"run `abk init` to add it to {name}",
                    )
                )
            elif merge != "union":
                checks.append(
                    _warn(
                        f"changelog union merge {name}",
                        f"{repo.changelog}'s merge setting in {attributes} is `{merge}`, "
                        "not `merge=union`, so concurrent entries conflict",
                        f"change it to `merge=union` in {attributes} by hand",
                    )
                )
        else:
            checks.append(
                _warn(
                    f"changelog {name}",
                    f"{repo.changelog} is not in {path}",
                    f"add the file, set `changelog:` to where {name} keeps it, "
                    "or `changelog: null` to turn the convention off",
                )
            )
    return checks


def _github_account(repo: forges.RepoId, run: Run, transport: httpx.BaseTransport | None) -> str:
    """The account this repo's credential acts as, from the cheapest
    authenticated endpoint. Raises `TransportError` naming what failed."""
    credentials = credential_for(repo.forge, repo.account, run=run)
    try:
        with Transport(
            settings.github_api_url.rstrip("/"), credentials, transport=transport
        ) as host:
            answer = host.request("GET", "/user")
    except TransportError as error:
        raise TransportError(f"{error} (credential from {credentials.source})") from error
    login = answer.data.get("login") if isinstance(answer.data, dict) else None
    if not login:
        raise TransportError(
            f"GET /user: no login in the answer: {page_excerpt(answer.text)} "
            f"(credential from {credentials.source})"
        )
    return f"{login} via {credentials.source}"


def _forge_access(
    inst: Installation,
    run: Run,
    *,
    transport: httpx.BaseTransport | None = None,
) -> list[Check]:
    """Whether each repo's host will answer for it.

    Per repo rather than per account: "can we act here" is the question the
    pipeline actually asks, and it is the same question on every host, where
    "which accounts does this workspace touch" was a GitHub owner's shape.
    A GitHub repo is checked with its real credential, and the check names the
    account it acts as.
    """
    checks = []
    for name in sorted(inst.repos):
        forge, repo = inst.forge_of(name)
        title = f"forge {name}"
        if repo.forge == "github":
            try:
                checks.append(
                    _ok(
                        title,
                        f"github {forges.key(repo)} as {_github_account(repo, run, transport)}",
                    )
                )
            except TransportError as error:
                checks.append(_fail(title, str(error), forge.access_fix(repo)))
            continue
        try:
            problem = forge.check_access(repo, run=run)
        except TransportError as error:
            problem = f"cannot reach {forges.key(repo)}: {error}"
        if problem:
            checks.append(_fail(title, problem, forge.access_fix(repo)))
        else:
            checks.append(_ok(title, f"{forge.name} {forges.key(repo)}"))
    return checks


# How a forge begins a `merge_guard` answer when it could not ask the host (see `Forge`).
CANNOT_TELL = "cannot tell"


def _guard_of(inst: Installation, name: str, run: Run) -> str:
    """What the repo's forge says about its default branch: "" when protected, else why not."""
    forge, repo = inst.forge_of(name)
    branch = inst.repo(name).default_branch
    try:
        return forge.merge_guard(repo, branch=branch, run=run)
    except TransportError as error:
        return f"{CANNOT_TELL} what guards {branch}: {error}"


def _merge_guards(inst: Installation, run: Run) -> list[Check]:
    """What stops a merge on each repo's default branch.

    Reported rather than warned about: a free private repo cannot have branch
    protection and a project may have no policy, so a warning here would be
    permanent and unfixable, which is how a report teaches people to ignore
    it. But the command hook is then the only thing between an agent and
    merging its own PR, and that is worth reading rather than merely being
    true.
    """
    checks = []
    for name in sorted(inst.repos):
        branch = inst.repo(name).default_branch
        unguarded = _guard_of(inst, name, run)
        title = f"merge guard {name}"
        if unguarded:
            checks.append(
                _info(
                    title,
                    unguarded,
                    "nothing server-side refuses a merge: the command policy hook is the "
                    "only guard, so keep it installed",
                )
            )
        else:
            checks.append(_ok(title, f"{branch} is protected"))
    return checks


def _planning_publish(inst: Installation, run: Run) -> list[Check]:
    """In an in-repo installation: `direct` cannot push to a protected default branch."""
    name = in_repo_name(inst)
    if name is None:
        return []
    title = "planning publish"
    guard = _guard_of(inst, name, run)
    branch = inst.repo(name).default_branch
    if guard.startswith(CANNOT_TELL):
        return [_info(title, guard)]
    publish = inst.config.planning.publish
    if guard:
        return [_ok(title, f"{publish}; {guard}")]
    if publish == PlanningPublish.BRANCH:
        return [
            _ok(title, f"branch; {branch} is protected, so abk publishes through a pull request")
        ]
    return [
        _fail(
            title,
            f"{branch} is protected and planning.publish is direct, so abk's commits cannot land",
            "set `planning.publish: branch` in abk.yaml",
        )
    ]


def _pipeline_worktree(inst: Installation) -> list[Check]:
    """In an in-repo installation: the pipeline worktree the marker names."""
    if in_repo_name(inst) is None:
        return []
    named = read_pipeline_marker(inst.root)
    if named is None:
        return []
    common = common_dir(inst.root)
    if common is not None and is_worktree_of(named, common):
        return [_ok("pipeline worktree", str(named))]
    return [
        _warn(
            "pipeline worktree",
            f"the marker names {named}, which does not exist",
            "abk install-timers",
        )
    ]


def _state_ignores(inst: Installation) -> list[Check]:
    """In an in-repo installation: the root's `.gitignore` must ignore the state files."""
    if in_repo_name(inst) is None:
        return []
    ignore = inst.root / ".gitignore"
    text = ignore.read_text() if ignore.is_file() else ""
    missing = missing_state_ignores(text, inst.config.planning.state_dir)
    if not missing:
        return [_ok("state ignores", str(ignore))]
    return [
        _warn(
            "state ignores",
            f"{ignore} lacks: {', '.join(missing)}",
            "abk init (adds the lines in a marked block)",
        )
    ]


def _linger(run: Run) -> list[Check]:
    """A warning when the installed timers stop with the last login session."""
    user = timers.current_user()
    if timers.linger_state(user, run) != "off":
        return []
    return [
        _warn(
            "linger",
            "lingering is off, so the timers only run while a login session is open",
            timers.linger_advice(user),
        )
    ]


def _timers(inst: Installation, run: Run, units: Path | None, which: Which) -> list[Check]:
    """Whether the pipeline is actually scheduled on this machine.

    Installed-but-not-enabled is the failure that looks most like success: the
    units are there, `abk status` answers perfectly, and no tick has happened
    in a week. So this asks systemd, not just the filesystem.

    No units at all is only worth knowing: cron, a CI job or a person may be
    running `abk tick`. Anything half-installed is a warning, because it means
    somebody did try to schedule it and it is not working.
    """
    where = units or timers.user_unit_dir()
    state = timers.report(inst.root, dest=where, tool_dirs=timers.tool_dirs(inst, which=which))
    checks: list[Check] = []
    enabled = False

    if not state.installed:
        checks.append(
            _info(
                "timers",
                f"no systemd units installed for {inst.root}",
                "`abk install-timers` schedules the pipeline; skip it if something else "
                "runs `abk tick`",
            )
        )
    else:
        problems = [f"missing {name}" for name in state.missing]
        problems += [f"out of date: {path.name}" for path in state.drifted]
        problems += [f"outdated (no longer installed): {path.name}" for path in state.outdated]
        unasked = False
        not_enabled = False
        for name in timers.unit_names(inst.root):
            if not name.endswith(".timer") or name in state.missing:
                continue
            try:
                answer = run(
                    ["systemctl", "--user", "is-enabled", name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                unasked = True
                break
            if answer.returncode:
                problems.append(f"not enabled: {name}")
                not_enabled = True
        enabled = not unasked and not not_enabled
        if problems:
            checks.append(
                _warn(
                    "timers",
                    "\n".join(problems),
                    "`abk install-timers` rewrites what moved on, enables the timers, and "
                    "removes the outdated units"
                    if state.outdated
                    else "`abk install-timers` rewrites what moved on and enables the timers",
                )
            )
        elif unasked:
            checks.append(
                _info(
                    "timers",
                    "units are installed, but cannot ask systemd whether they are enabled "
                    "(no `systemctl` here)",
                )
            )
        else:
            count = len(timers.unit_names(inst.root))
            checks.append(_ok("timers", f"{count} units, enabled, pointing at {inst.root}"))

    if enabled:
        checks += _linger(run)

    # What the installed service can find. A person's terminal has `az` on its
    # PATH; the unit does not inherit it, so every command a person runs works
    # while the scheduled poll fails on each tick.
    for tool, reachable in timers.unreachable(inst, where, which=which):
        checks.append(
            _fail(
                "timer PATH",
                f"the tick service cannot find {tool}",
                "`abk install-timers` puts its directory on the unit's PATH"
                if reachable
                else f"install {tool}, then run `abk install-timers`",
            )
        )

    # Units of any installation whose directory is gone. Nobody is left to
    # remove them: the repo they served moved away, and `systemctl enable`
    # accepted them without complaint because a unit naming a directory that is
    # not there is still a valid unit. This installation's own are covered above.
    ours = set(timers.unit_names(inst.root))
    gone = [path for path in timers.dangling_units(where) if path.name not in ours]
    if gone:
        names = ", ".join(f"{path.name} (-> {timers.owner_of(path)})" for path in gone)
        stops = "; ".join(
            f"systemctl --user disable --now {path.with_suffix('.timer').name}" for path in gone
        )
        checks.append(
            _warn(
                "stale timer units",
                f"point at a directory that no longer exists: {names}",
                f"{stops}; then delete the files in {where}",
            )
        )
    return checks


def _toolchain(inst: Installation, run: Run, which: Which) -> list[Check]:
    checks = []
    missing = [tool for tool in ("node", "npx") if which(tool) is None]
    if missing:
        checks.append(
            _fail(
                "node",
                f"{', '.join(missing)} not on PATH",
                "install node (the OpenSpec CLI runs through npx)",
            )
        )
    else:
        checks.append(_ok("node", "node and npx on PATH"))
    result = openspec.run(["--version"], cwd=inst.root, run=run)
    if result.returncode:
        checks.append(
            _fail(
                "openspec",
                f"`{' '.join(openspec.command())} --version` failed: {result.stderr.strip()}",
                "check `openspec.command` in abk.yaml, or the node install",
            )
        )
    else:
        checks.append(_ok("openspec", result.stdout.strip() or "runs"))
    return checks


def _agent_commands(inst: Installation) -> list[Check]:
    """The commands each repo's build prompts name for an agent: all allowed by the build's
    tool list, none named, or some the prompt section has no room for. A profile's own
    command outside its tool list is a defect of the profile, so a report and not a load
    error."""
    checks = []
    for name, repo in inst.repos.items():
        title = f"agent commands {name}"
        try:
            commands = agent_commands.effective(repo)
            outside = agent_commands.refused(repo)
        except KeyError:
            continue  # an unknown profile is reported where the repo is
        toolchains = [repo.profile, *(p.profile for p in repo.projects)]
        fix = f"allow it in the profile, or set `repos.{name}.agent_commands` in abk.yaml"
        if outside:
            lines = ", ".join(f"`{line}`" for _, line in outside)
            owner = (
                f"profiles of repo {name} ({', '.join(dict.fromkeys(toolchains))})"
                if repo.projects
                else f"profile {repo.profile}"
            )
            checks.append(
                _fail(
                    title,
                    f"{owner}: {lines} not allowed by the build's tool list",
                    fix,
                )
            )
        elif not commands:
            checks.append(
                _info(
                    title,
                    "none named: the build prompts tell the agent no command to run",
                    f"set `repos.{name}.agent_commands` to name some",
                )
            )
        elif left := agent_commands.left_out(repo):
            limit = agent_commands.NOTE_LIMIT
            checks.append(
                _warn(
                    title,
                    f"{len(left)} of {len(commands)} commands do not fit the {limit}-character "
                    "section of the build prompts",
                    f"list fewer in `repos.{name}.agent_commands`",
                )
            )
        else:
            count = f"{len(commands)} command{'' if len(commands) == 1 else 's'}"
            checks.append(_ok(title, f"{count}, all allowed"))
    return checks


def _notifications(inst: Installation, run: Run, which: Which) -> list[Check]:
    """The prerequisites of the chosen notification provider; nothing while it is off."""
    notifications = inst.config.notifications
    match notifications.provider:
        case NotificationProvider.OFF:
            return []
        case NotificationProvider.WINDOWS:
            fix = " ".join(INSTALL_COMMAND)
            try:
                result = run(MODULE_CHECK_COMMAND, capture_output=True, text=True, check=False)
            except OSError as error:
                return [_fail("notifications", f"powershell.exe did not run: {error}", fix)]
            listed = re.search(
                rf"(?<![\w.]){re.escape(BURNTTOAST_VERSION)}(?![\w.])", result.stdout
            )
            if result.returncode or "BurntToast" not in result.stdout or not listed:
                return [
                    _fail(
                        "notifications",
                        f"the BurntToast module {BURNTTOAST_VERSION} is not installed",
                        fix,
                    )
                ]
            return [_ok("notifications", f"BurntToast module {BURNTTOAST_VERSION} installed")]
        case NotificationProvider.COMMAND:
            try:
                program = shlex.split(notifications.command.show)[0]
            except (ValueError, IndexError):
                return [
                    _fail(
                        "notifications", "no usable show template", "fix notifications.command.show"
                    )
                ]
            if which(program) is None:
                return [
                    _fail(
                        "notifications",
                        f"{program} is not on PATH",
                        f"install {program}, or change notifications.command.show",
                    )
                ]
            return [_ok("notifications", f"{program} on PATH")]


def _ssh_keys(inst: Installation) -> list[Check]:
    checks = []
    for name, repo in inst.repos.items():
        key = repo.deploy.ssh_key
        if key is None:
            continue
        if key.expanduser().is_file():
            checks.append(_ok(f"ssh key {name}", str(key)))
        else:
            checks.append(
                _fail(
                    f"ssh key {name}", f"{key} does not exist", "fix `deploy.ssh_key` in abk.yaml"
                )
            )
    return checks


def _weak_secrets() -> list[Check]:
    """The secret names the redaction set, built when the installation was activated,
    cannot protect: set to under `MIN_LENGTH` characters, or not set at all. Names only;
    a value is never printed."""
    held = active_redactor()
    short, unset = held.short, held.unset
    checks = []
    if short:
        checks.append(
            _warn(
                "secrets too short",
                f"{', '.join(short)}: under {MIN_LENGTH} characters, so never redacted",
                "use a longer value, or accept that it can appear in stored output",
            )
        )
    if unset:
        checks.append(
            _warn(
                "secrets not set",
                f"redact: {', '.join(unset)} not set, so nothing is redacted for it",
                "set the variable in the environment or the planning repo's .env",
            )
        )
    return checks


def _verify_env(inst: Installation, run: Run) -> list[Check]:
    checks = []
    for name, provider in inst.config.verify.env.items():
        try:
            if isinstance(provider, CommandProvider):
                result = run(provider.argv, capture_output=True, text=True, check=False)
                if result.returncode:
                    raise ConfigError(f"{' '.join(provider.argv)} exited {result.returncode}")
            else:
                _resolve(provider)
        except (ConfigError, OSError) as error:
            checks.append(
                _fail(f"verify.env {name}", str(error), f"fix the provider for {name} in abk.yaml")
            )
            continue
        checks.append(_ok(f"verify.env {name}", "resolves"))
    return checks


PUBLIC_CONTENT = "public content"
_HOME_PATH = re.compile(rf"{TILDE_HOME}|{ROOT_HOME}[A-Za-z]")
_PUBLIC_FIX = (
    "keep the value in the ignored .env (read through a `from: env-file` entry) or remove the "
    "entry; if this repository is private, ignore this"
)


def _strings(node: object, key: str = "") -> list[tuple[str, str]]:
    """Every string in a parsed document with its dotted key path."""
    if isinstance(node, str):
        return [(key, node)]
    if isinstance(node, dict):
        pairs = [(f"{key}.{name}" if key else str(name), value) for name, value in node.items()]
    elif isinstance(node, list):
        pairs = [(f"{key}[{index}]", value) for index, value in enumerate(node)]
    else:
        return []
    return [found for name, value in pairs for found in _strings(value, name)]


def _is_tracked(root: Path, name: str) -> bool:
    return git(root, "ls-files", "--error-unmatch", name, check=False).returncode == 0


def _is_ignored(root: Path, name: str) -> bool:
    return git(root, "check-ignore", "-q", name, check=False).returncode == 0


def _committed_facts(inst: Installation, toplevel: Path) -> list[Check]:
    """What the tracked abk.yaml's own text says that a public repository must
    not: read straight from the file, offline."""
    document = yaml.safe_load((inst.root / "abk.yaml").read_text()) or {}
    home = str(Path.home())
    under_home = re.compile(rf"(?<![\w/]){re.escape(home)}(?:/|$)") if home.rstrip("/") else None
    repos = document.get("repos") or {}
    checks = []
    for name, entry in repos.items():
        raw = entry.get("path") if isinstance(entry, dict) else None
        if raw is None:
            continue
        resolved = (inst.root / Path(str(raw)).expanduser()).resolve()
        if not resolved.is_relative_to(toplevel):
            checks.append(
                _warn(
                    PUBLIC_CONTENT,
                    f"repos.{name}.path leaves the checkout",
                    _PUBLIC_FIX,
                )
            )
    for key, value in _strings(document):
        if _HOME_PATH.search(value) or (under_home and under_home.search(value)):
            checks.append(_warn(PUBLIC_CONTENT, f"{key} holds a home-directory path", _PUBLIC_FIX))
    origin = git(inst.root, "remote", "get-url", "origin", check=False)
    named = forges.identify(origin.stdout.strip()) if origin.returncode == 0 else None
    if named is not None:
        for name, entry in repos.items():
            try:
                repo = RepoConfig.model_validate(entry)
                account = forges.get(repo.forge).identity(repo).account
            except (ValueError, KeyError):
                continue
            if str(repo.path) == ".":
                continue
            if account.lower() != named.account.lower():
                checks.append(
                    _warn(
                        PUBLIC_CONTENT,
                        f"repos.{name} is owned by another account than the origin",
                        _PUBLIC_FIX,
                    )
                )
    return checks


def _local_files(inst: Installation, toplevel: Path) -> list[Check]:
    """The local scrub list, the configuration overlay and the redaction copies: never committed."""
    root = inst.root
    checks = []
    for local in ("scrub.local", OVERLAY_FILENAME):
        if not (root / local).exists():
            continue
        if _is_tracked(root, local):
            checks.append(
                _warn(
                    PUBLIC_CONTENT,
                    f"{local} is tracked",
                    f"git rm --cached {local}, and add `{local}` to .gitignore",
                )
            )
        elif not _is_ignored(root, local):
            checks.append(
                _warn(PUBLIC_CONTENT, f"{local} is not ignored", f"add `{local}` to .gitignore")
            )
    found = {*root.glob(COPY_PATTERN), *inst.state_dir.rglob(COPY_PATTERN)}
    # A copy outside the repository cannot be committed to it.
    for copy in sorted(c for c in found if c.resolve().is_relative_to(toplevel)):
        name = copy.resolve().relative_to(toplevel).as_posix()
        if _is_tracked(toplevel, name):
            checks.append(
                _warn(
                    PUBLIC_CONTENT,
                    f"{name} is tracked",
                    f"git rm --cached {name}, and add `{COPY_PATTERN}` to .gitignore",
                )
            )
        elif not _is_ignored(toplevel, name):
            checks.append(
                _warn(
                    PUBLIC_CONTENT, f"{name} is not ignored", f"add `{COPY_PATTERN}` to .gitignore"
                )
            )
    return checks


def _public_content(inst: Installation) -> list[Check]:
    """Facts that must not reach a public repository, found without a network
    call: the committed abk.yaml's own text, and files that must stay ignored."""
    top = git(inst.root, "rev-parse", "--show-toplevel", check=False)
    if top.returncode:
        return [_ok(PUBLIC_CONTENT, "not a git repository")]
    toplevel = Path(top.stdout.strip()).resolve()
    checks = []
    tracked = _is_tracked(inst.root, "abk.yaml")
    if tracked:
        checks += _committed_facts(inst, toplevel)
    checks += _local_files(inst, toplevel)
    if checks:
        return checks
    return [_ok(PUBLIC_CONTENT, "nothing found" if tracked else "abk.yaml is not tracked")]


MACHINE_KEYS = "machine keys"


def _mapping(node: object, *path: str) -> dict:
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


def _machine_keys(inst: Installation) -> list[Check]:
    """Settings in the committed abk.yaml that belong to a machine or a person: a warning
    for a machine choice, a note for a default a team may commit."""
    root = inst.root
    if git(root, "rev-parse", "--show-toplevel", check=False).returncode:
        return []
    if not _is_tracked(root, "abk.yaml"):
        return []
    document = read_base(root / "abk.yaml")
    move = f"move it to {OVERLAY_FILENAME}"
    warned = []
    noted = []
    repos = _mapping(document, "repos")
    for name, entry in repos.items():
        if isinstance(entry, dict) and entry.get("account") is not None:
            warned.append((f"repos.{name}.account", "names the account this machine builds on"))
    if document.get("project_limits"):
        warned.append(("project_limits", "is the scheduling this machine runs at"))
    for name, entry in _mapping(document, "runtimes").items():
        if not isinstance(entry, dict):
            continue
        if entry.get("accounts"):
            warned.append((f"runtimes.{name}.accounts", "lists the accounts of this person"))
        for field in ("command", "policy_fix"):
            argv = entry.get(field)
            if isinstance(argv, list) and argv and str(argv[0]).startswith("/"):
                warned.append((f"runtimes.{name}.{field}", "starts with an absolute program path"))
        if entry.get("limits"):
            noted.append((f"runtimes.{name}.limits", "a plan's thresholds differ per person"))
    scopes = [("tests", _mapping(document, "tests"))]
    scopes += [(f"repos.{n}.tests", _mapping(e, "tests")) for n, e in repos.items()]
    for scope, tests in scopes:
        if tests.get("e2e_available"):
            warned.append((f"{scope}.e2e_available", "is what this machine has"))
        if str(tests.get("e2e_schedule")).lower() in ("off", "false"):
            noted.append(
                (f"{scope}.e2e_schedule", "a scheduled run switched off suits one machine")
            )
        for split, entry in _mapping(tests, "e2e_splits").items():
            if isinstance(entry, dict) and entry.get("hold") is not None:
                noted.append((f"{scope}.e2e_splits.{split}.hold", "a hold may suit one machine"))
    checks = [
        _warn(MACHINE_KEYS, f"{key} in abk.yaml {why}: a machine choice", move)
        for key, why in warned
    ]
    checks += [
        _info(MACHINE_KEYS, f"{key} in abk.yaml: {why}", f"fine to commit; {move} to differ")
        for key, why in noted
    ]
    return checks


def _missing_inputs(environment: EnvironmentConfig, root: Path) -> list[str]:
    return [pattern for pattern, names in matched_inputs(environment, root).items() if not names]


def _tracked_artifacts(environment: EnvironmentConfig, root: Path) -> list[str]:
    """The artifact patterns that cover a file the repository tracks."""
    if not environment.artifacts or not (root / ".git").exists():
        return []
    tracked = git_out(root, "ls-files", "-z").split("\0")
    return [
        pattern
        for pattern in environment.artifacts
        if any(name and matches(pattern, name) for name in tracked)
    ]


def _artifact_warnings(environment: EnvironmentConfig, root: Path, name: str) -> list[Check]:
    covering = _tracked_artifacts(environment, root)
    if not covering:
        return []
    return [
        _warn(
            name,
            f"covers tracked files, which are treated as ordinary work: {', '.join(covering)}",
            "narrow `artifacts` so it names only what the sync produces",
        )
    ]


def _environment(inst: Installation, run: Run) -> list[Check]:
    """Whether each environment is managed, its inputs exist, and the planning
    environment's `check` passes."""
    checks = []
    planning = inst.config.environment
    if planning is None:
        checks.append(
            _warn(
                "environment",
                "none is managed: the pipeline syncs and checks nothing",
                "run `abk init` to fill the `environment` section, or write it by hand",
            )
        )
    else:
        missing = _missing_inputs(planning, inst.root)
        if missing:
            checks.append(
                _warn(
                    "environment inputs",
                    f"listed but not found: {', '.join(missing)}",
                    "fix `environment.inputs` in abk.yaml",
                )
            )
        checks += _artifact_warnings(planning, inst.root, "environment artifacts")
        command = f"`{' '.join(planning.check)}`"
        fix = f"run `{' '.join(planning.sync)}`, or fix `environment.check`"
        try:
            result = run(planning.check, cwd=inst.root, capture_output=True, text=True, check=False)
        except OSError as error:
            checks.append(_fail("environment", f"{command} could not run: {error}", fix))
        else:
            if result.returncode:
                output = f"{result.stdout or ''}{result.stderr or ''}".strip()
                detail = f"{command} exited {result.returncode}: {output}"
                checks.append(_fail("environment", detail, fix))
            else:
                checks.append(_ok("environment", f"{command} passes"))
    for name, repo in inst.repos.items():
        if repo.environment is None:
            checks.append(
                _warn(
                    f"environment {name}",
                    f"{name} has no environment section, so nothing is synced or checked for it",
                    f"run `abk init` to fill repos.{name}.environment, or write it by hand",
                )
            )
            continue
        missing = _missing_inputs(repo.environment, inst.checkouts[name])
        if missing:
            checks.append(
                _warn(
                    f"environment {name} inputs",
                    f"listed but not found: {', '.join(missing)}",
                    f"fix repos.{name}.environment.inputs in abk.yaml",
                )
            )
        checks += _artifact_warnings(
            repo.environment, inst.checkouts[name], f"environment {name} artifacts"
        )
    return checks


def _rules_drift(inst: Installation) -> Check:
    """Whether this installation's authoring rules predate the framework's.

    Not a text comparison. The rules are prompt input and an installation is
    meant to reword them for its own repos, so comparing wording reported
    every deliberate rewrite as drift and said nothing about whether a rule
    was actually absent. The stamp at the top of the block is what can be
    known: which version of the framework's rules this file was written
    against.
    """
    path = inst.specs_dir / "config.yaml"
    if not path.is_file():
        return _warn("rules", f"{path} is missing", "run `abk init` again to write it")

    stamped = rules_version(path.read_text())
    if stamped is None:
        return _info(
            "rules",
            f"{path.name} carries no `# abk-rules:` stamp, so whether it predates the "
            f"framework's rules (v{RULES_VERSION}) cannot be told from here",
            f"compare it with the rules `abk init` would write, then add "
            f"`# abk-rules: v{RULES_VERSION}` as its first line",
        )
    if stamped == RULES_VERSION:
        return _ok("rules", f"at v{RULES_VERSION} (the wording is this installation's own)")
    if stamped > RULES_VERSION:
        return _warn(
            "rules",
            f"{path.name} is stamped v{stamped}, newer than this framework's v{RULES_VERSION}",
            "upgrade agent-build-kit",
        )

    added = [
        f"  v{version}: {change}"
        for version in range(stamped + 1, RULES_VERSION + 1)
        for change in RULES_CHANGES.get(version, [])
    ]
    return _warn(
        "rules",
        f"{path.name} is stamped v{stamped}; the framework is at v{RULES_VERSION}:\n"
        + "\n".join(added),
        "run `abk init --update-rules` to add what they added and restamp the file, "
        f"or fold them in yourself, in your own words, and stamp it v{RULES_VERSION}",
    )


def _gaps(inst: Installation, run: Run) -> list[Check]:
    checks = []
    for name, repo in inst.repos.items():
        path = inst.checkouts[name]
        if not path.is_dir():
            continue
        detection = detect_repo(path, run=run)
        prefixes = [rule.prefix for rule in repo.deploy.rules]
        profile = profiles.get(repo.profile)
        gaps: list[str] = []
        for service in detection.service_dirs:
            if any(
                prefix == f"{service}/" or prefix.startswith(f"{service}/") for prefix in prefixes
            ):
                continue
            # A library other members depend on needs no rule of its own: a
            # change in it redeploys its dependents (verify's convention).
            try:
                if profile.dependents(path, service):
                    continue
            except ProfileUnsupported:
                pass
            gaps.append(f"service dir {service}/ has no deploy rule")
        for prefix in prefixes:
            if not (path / prefix.rstrip("/")).exists():
                gaps.append(f"deploy rule prefix {prefix} no longer exists")
        if detection.dev_stack_script and repo.dev_stack is None:
            gaps.append(f"{DEV_STACK_SCRIPT} exists but `dev_stack` is not set")
        for written in repo.deploy.live_written:
            if not (path / written).is_dir():
                gaps.append(f"live_written path {written} is not a directory")
        if gaps:
            checks.append(
                _warn(f"abk.yaml {name}", "; ".join(gaps), "update the repo's entry in abk.yaml")
            )
        else:
            checks.append(_ok(f"abk.yaml {name}", "matches the checkout"))
    return checks


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_names(items: object) -> set[str]:
    """The package names in a list of requirement strings; anything else is empty."""
    if not isinstance(items, list):
        return set()
    return {
        _normalized(m.group(0))
        for item in items
        if isinstance(item, str) and (m := re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", item.strip()))
    }


def _pyproject_tools(pyproject: Path) -> tuple[set[str], set[str]]:
    """The package names the repo's dependency groups hold, and every command
    `uv run` can start there besides those: the project's own name and scripts,
    its dependencies and optional dependencies, and the interpreter."""
    try:
        data = tomllib.loads(pyproject.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return set(), set()
    groups = data.get("dependency-groups", {})
    project = data.get("project", {})
    locked: set[str] = set()
    for group in groups.values() if isinstance(groups, dict) else []:
        locked |= _requirement_names(group)
    if not isinstance(project, dict):
        return locked, set()
    others = _requirement_names(project.get("dependencies"))
    extras = project.get("optional-dependencies", {})
    for extra in extras.values() if isinstance(extras, dict) else []:
        others |= _requirement_names(extra)
    scripts = project.get("scripts", {})
    if isinstance(scripts, dict):
        others |= {_normalized(str(key)) for key in scripts}
    if isinstance(project.get("name"), str):
        others.add(_normalized(project["name"]))
    return locked, others


def _is_python(tool: str) -> bool:
    return re.fullmatch(r"python(3(\.\d+)?)?", tool) is not None


_UV_RUN_VALUE_FLAGS = frozenset(
    {
        "--package",
        "--group",
        "--only-group",
        "--python",
        "-p",
        "--with",
        "--with-requirements",
        "--with-editable",
        "--project",
        "--directory",
        "--extra",
        "--env-file",
        "--index",
        "--default-index",
        "--index-url",
        "--extra-index-url",
        "--config-file",
        "--cache-dir",
        "--no-install-package",
        "--no-group",
        "--no-extra",
        "--exclude-newer",
        "--resolution",
        "--prerelease",
        "--python-preference",
        "--link-mode",
        "--config-setting",
        "-C",
        "--upgrade-package",
        "-P",
        "--reinstall-package",
        "--refresh-package",
    }
)


def _hook_repo_tools(hook_repo: dict, hooks: list[dict]) -> set[str]:
    """The tool names a hook repository provides: its basename without a
    `-pre-commit` suffix or `mirrors-` prefix, and each hook id that is a tool
    name or `<tool>-check` / `<tool>-format`. Whole names, never substrings."""
    base = _normalized(str(hook_repo.get("repo", "")).rstrip("/").rsplit("/", 1)[-1])
    base = base.removeprefix("mirrors-").removesuffix("-pre-commit")
    names = {base}
    for hook in hooks:
        hook_id = _normalized(str(hook.get("id", "")))
        names.add(hook_id)
        names.add(hook_id.removesuffix("-check").removesuffix("-format"))
    return names


def _uv_run_tool(entry: str) -> str | None:
    """The command a `uv run ...` hook entry runs, or None for any other entry."""
    try:
        words = shlex.split(entry)
    except ValueError:
        return None
    if words[:2] != ["uv", "run"]:
        return None
    rest = words[2:]
    while rest and rest[0].startswith("-"):
        flag = rest.pop(0)
        if flag in _UV_RUN_VALUE_FLAGS and rest:
            rest.pop(0)
    return _normalized(rest[0]) if rest else None


def _python_tools(inst: Installation) -> list[Check]:
    """A Python tool's version has one owner, the lock: warn when a hook
    repository pins one the dependency group also holds, and when a system hook
    runs one the group does not hold."""
    checks = []
    for name in inst.repos:
        path = inst.checkouts[name]
        hooks_file = path / ".pre-commit-config.yaml"
        if not (path / "pyproject.toml").is_file() or not hooks_file.is_file():
            continue
        try:
            hook_repos = (yaml.safe_load(hooks_file.read_text()) or {}).get("repos") or []
        except (OSError, yaml.YAMLError):
            continue
        locked, others = _pyproject_tools(path / "pyproject.toml")
        pinned: set[str] = set()
        orphaned: set[str] = set()
        for hook_repo in hook_repos:
            if not isinstance(hook_repo, dict):
                continue
            hook_list = hook_repo.get("hooks")
            hooks = (
                [h for h in hook_list if isinstance(h, dict)] if isinstance(hook_list, list) else []
            )
            if hook_repo.get("repo") == "local":
                for hook in hooks:
                    tool = _uv_run_tool(str(hook.get("entry", "")))
                    runnable = locked | others
                    if (
                        hook.get("language") == "system"
                        and tool
                        and tool not in runnable
                        and not _is_python(tool)
                    ):
                        orphaned.add(tool)
            elif hook_repo.get("rev"):
                pinned |= locked & _hook_repo_tools(hook_repo, hooks)
        for tool in sorted(pinned):
            checks.append(
                _warn(
                    f"{name} {tool} version",
                    f"{tool} is pinned in pyproject.toml's dependency group and by a hook "
                    f"`rev` in .pre-commit-config.yaml, so two versions can disagree",
                    f"run {tool} from a `repo: local`, `language: system` hook "
                    f"(`uv run --frozen {tool} ...`) and drop the hook's `rev`",
                )
            )
        for tool in sorted(orphaned):
            checks.append(
                _warn(
                    f"{name} {tool} hook",
                    f"a `language: system` hook in .pre-commit-config.yaml runs `uv run {tool}`, "
                    f"but {tool} is not in pyproject.toml's dependency groups, so it fails",
                    f"add {tool} to the dev dependency group, or fix the hook's entry",
                )
            )
    return checks


def _probed(name: str, command: list[str], which: Which, run: Run) -> list[Check]:
    """What the probe `abk init` uses finds: the other runtimes usable on this machine,
    and a warning when the selected entry is only documented, not verified."""
    found = runtimes.candidates(which, run)
    selected = [c for c in found if c.runtime == name and list(c.command) == command]
    others = [c for c in found if c.usable and c not in selected]
    checks = []
    if others:
        listed = ", ".join(f"{c.label} ({shlex.join(c.command)})" for c in others)
        checks.append(_info("runtimes", f"other usable runtimes on this machine: {listed}"))
    for candidate in selected:
        if candidate.documented_only:
            checks.append(
                _warn(
                    "runtime verification",
                    f"{candidate.label} is documented only: {candidate.verified}",
                    "run `abk init --policy-only` to check what it refuses",
                )
            )
    return checks


def _account(runtime: AgentRuntime, run: Run) -> list[Check]:
    """What the runtime says of the account it runs on, as checks."""
    return [
        Check(name="runtime account", status=line.status, detail=line.detail, fix=line.fix)
        for line in account_report_of(runtime, run, settings_module.loaded_env_file)
    ]


def _labelled_accounts(inst: Installation, run: Run) -> list[Check]:
    """What the Claude accounts the repos name by label need on this machine."""
    return [
        Check(name="claude account", status=line.status, detail=line.detail, fix=line.fix)
        for line in claude_code.labelled_accounts_report(inst, run)
    ]


def _runtime(inst: Installation, which: Which, run: Run) -> list[Check]:
    """Which runtime the pipeline runs on, whether it can start, how much it
    interposes on, and whether it refuses what abk forbids."""
    name = config.runtime_name(inst.config)
    runtime = runtimes.get(name)
    entry = config.runtime_entry(inst.config)
    if not runtime.implemented:
        return [
            _fail(
                "runtime",
                f"{name} is not implemented yet",
                "set `runtime:` in abk.yaml (or ABK_RUNTIME) to an implemented one",
            )
        ]
    command = entry.command or list(runtime.agent_command)
    startable = not command or which(command[0]) is not None
    if startable:
        checks = [_ok("runtime", name + (f" ({' '.join(command)})" if command else ""))]
    else:
        checks = [
            _fail(
                "runtime",
                f"{name}: its agent command {command[0]} is not on PATH",
                f"install it, or set `runtimes.{name}.command` in abk.yaml",
            )
        ]

    checks += _account(runtime, run)
    checks += _probed(name, command, which, run)

    if runtime.policy_coverage == "all_calls":
        checks.append(_ok("runtime coverage", "all_calls: every tool call reaches the policy"))
    else:
        checks.append(
            _warn(
                "runtime coverage",
                f"{runtime.policy_coverage}: abk sees only some of what the agent does",
                "rely on the runtime's own configuration for what abk forbids",
            )
        )

    if not startable:
        # The agent cannot start, so what it would run under is not judged either; the
        # runtime check above says what to fix.
        checks.append(
            _warn(
                "runtime policy",
                f"not checked: the agent command {command[0]} does not resolve",
                "fix the runtime check above, then run `abk doctor` again",
            )
        )
        return checks
    if entry.policy == PolicyMarker.UNCHECKED:
        # Someone recorded the runtime as unchecked: it is not checked.
        checks.append(
            _warn(
                "runtime policy",
                "recorded as unchecked: nobody has confirmed the agent refuses what abk forbids",
                f"run `abk init --policy-only`, then remove `runtimes.{name}.policy` from abk.yaml "
                "once it passes",
            )
        )
        return checks
    try:
        report = policy_check.check_policy(runtime, entry, inst)
    except Exception as error:  # noqa: BLE001 - whatever the runtime raised is the finding
        checks.append(
            _fail(
                "runtime policy",
                f"could not be checked: {type(error).__name__}: {error}",
                "run `abk doctor` again once the runtime can answer",
            )
        )
        return checks
    if report.cannot_check == policy_check.NO_POLICY:
        checks.append(
            _warn(
                "runtime policy",
                report.cannot_check,
                policy_check.NO_POLICY_FIX,
            )
        )
    elif report.cannot_check:
        checks.append(
            _fail(
                "runtime policy",
                report.cannot_check,
                "install the agent, or point its home variable at its configuration",
            )
        )
    elif report.ok:
        said = policy_check.summary(report)
        refused = "every forbidden class is refused"
        checks.append(_ok("runtime policy", f"{refused}: {said}" if said else refused))
    else:
        checks.append(
            _fail(
                "runtime policy",
                f"not refused: {policy_check.describe(report)}"
                + (f" | {policy_check.summary(report)}" if report.source else ""),
                policy_check.fix_for(name, entry, report),
            )
        )
    return checks


def _skills(inst: Installation) -> list[Check]:
    checks = []
    targets: dict[str, Path] = {}
    for name, root in {"planning": inst.root, **inst.checkouts}.items():
        if root.resolve() not in {path.resolve() for path in targets.values()}:
            targets[name] = root
    for name, root in targets.items():
        stale = skills.stale(root / ".claude" / "skills")
        if stale:
            names = ", ".join(f"{s.name} ({s.version or 'unversioned'})" for s in stale)
            checks.append(
                _warn(
                    f"skills {name}",
                    f"older than {__version__}: {names}",
                    "abk install-skills" + ("" if name == "planning" else f" --repo {root}"),
                )
            )
    return checks


# --- the run ---------------------------------------------------------------------------


def _address(endpoint: str) -> tuple[str, int] | None:
    """The host and port an http(s) endpoint names, or None when it is not a
    valid http(s) URL (no host, another scheme, an unusable port)."""
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not host:
        return None
    return host, port or (443 if parsed.scheme == "https" else 80)


def _reachable(address: tuple[str, int]) -> bool:
    host, port = address
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _telemetry() -> list[Check]:
    """Telemetry is off by default; when it is on, a missing or unreachable
    endpoint is a warning, never a failure, since a tick runs regardless."""
    if not settings.otel_enabled:
        return []
    shared = settings.otel_exporter_otlp_endpoint
    endpoints = {
        "traces": settings.otel_exporter_otlp_traces_endpoint or shared,
        "metrics": settings.otel_exporter_otlp_metrics_endpoint or shared,
    }
    checks = []
    for signal, endpoint in endpoints.items():
        name = f"telemetry {signal}"
        if not endpoint:
            checks.append(
                _warn(
                    name,
                    "ABK_OTEL_ENABLED is set but no endpoint is",
                    f"set OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT "
                    "or OTEL_EXPORTER_OTLP_ENDPOINT",
                )
            )
        elif (address := _address(endpoint)) is None:
            checks.append(
                _warn(
                    name,
                    f"{endpoint} is not a valid http(s) URL",
                    "write it as http://host:port, with a port from 1 to 65535",
                )
            )
        elif not _reachable(address):
            checks.append(
                _warn(
                    name, f"{endpoint} does not answer", "start the collector, or fix the endpoint"
                )
            )
        else:
            checks.append(_ok(name, endpoint))
    return checks


def _grafana() -> list[Check]:
    """Which path `abk telemetry push-dashboard` takes; nothing when no Grafana is set."""
    if not settings.grafana_url:
        return []
    path = "token" if settings.grafana_token else "anonymous"
    return [_ok("grafana", f"{settings.grafana_url} ({path})")]


def _live_installation(inst: Installation) -> list[Check]:
    """In a working copy: which pipeline worktree the installation is live in."""
    notice = live_notice(inst, "doctor", explicit=False)
    if notice is None:
        return []
    return [_warn("live installation", notice.removeprefix("abk: "), "use that config instead")]


def _e2e_holds(inst: Installation) -> list[Check]:
    """The held e2e-test splits as information, and what is wrong with the file or its entries."""
    holds = current_holds(inst.config, inst.state_dir)
    if holds.unreadable:
        return [
            _fail(
                "e2e-test holds",
                f"{inst.state_dir / HELD_FILE} cannot be read, so it holds nothing",
                "fix the file, or remove it and hold again with `abk e2e-test hold`",
            )
        ]
    checks = [
        _info("e2e-test holds", f"{name} is held: {hold_text(hold)}")
        for name, hold in holds.held.items()
    ]
    checks += [
        _warn(
            "e2e-test holds",
            f"{name}: the file holds it but the configuration releases it (`hold: false`)",
            "the configuration wins; remove `hold: false`, or `abk e2e-test release` it",
        )
        for name in holds.overridden
    ]
    checks += [
        _warn(
            "e2e-test holds",
            f"{HELD_FILE} has an entry for `{name}`, which no repo declares",
            "`abk e2e-test release` it, or declare the split",
        )
        for name in holds.unknown
    ]
    return checks


def _e2e_dimensions(inst: Installation) -> list[Check]:
    """Each declared e2e-test dimension with its values and which this machine has."""
    return [_info("e2e-test dimensions", line) for line in dimension_lines(inst.config)]


def _gate_usage(inst: Installation, run: Run, which: Which) -> list[Check]:
    """For each split with a gate: the provider's library is importable, the budget is set, a
    reading can be taken (read afresh, never from the cache) and what it says. A hold that
    stands for a gate reading is information; an unknown result is a warning."""
    name = "gate usage"
    checks: list[Check] = []
    held = current_holds(inst.config, inst.state_dir).held
    for split, gate in split_gates(inst).items():
        if gate.provider is not None:
            row = providers.PROVIDERS[gate.provider.name]
            if importlib.util.find_spec(row.library) is None:
                checks.append(
                    _warn(
                        name,
                        f"{split}: no reading can be taken, {row.hint}",
                        f"run `uv sync --extra {row.library}` in the installation, or name "
                        f"`agent-build-kit[{row.library}]` in its dependency on the kit",
                    )
                )
                continue
            checks.append(
                _ok(
                    name,
                    f"{split}: budget {gate.provider.budget_usd:g} USD ({row.library} installed)",
                )
            )
        else:
            program = (gate.command or [""])[0]
            if which(program) is None:
                checks.append(
                    _warn(
                        name,
                        f"{split}: the gate command {program} was not found",
                        "install it, or fix `gate.command` for the split",
                    )
                )
                continue
        result = gate_result(
            split,
            gate,
            now=datetime.now(UTC),
            state_dir=inst.state_dir,
            root=inst.root,
            standing=gate_standing(held.get(split)),
            refresh=True,
            persist=False,
            run=run,
        )
        reason = active_redactor().redact(result.reason)
        detail = f"{split}: {result.state}, {reason}" if reason else f"{split}: {result.state}"
        if result.state == "unknown":
            checks.append(
                _warn(
                    name,
                    f"{split}: no reading can be taken: {reason}",
                    "fix the reason shown",
                )
            )
        elif result.state == "held":
            checks.append(_info(name, detail))
        else:
            checks.append(_ok(name, detail))
    return checks


def run_doctor(
    config_path: Path | None,
    *,
    cwd: Path | None = None,
    run: Run | None = None,
    which: Which | None = None,
    units: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[Check]:
    run = run or subprocess.run
    which = which or shutil.which
    try:
        path = config.locate(config_path, cwd=cwd)
        loaded: WorkspaceConfig = load_config(path)
    except ConfigError as error:
        return [_fail("config", str(error), "run `abk init`, or fix abk.yaml")]
    checks = [_ok("config", str(path))]
    checks += [
        _warn("config", config.deprecation_notice(key), "run `abk config --migrate`")
        for key in config.deprecations(path)
    ]
    checks += [_warn("config", notice.text, notice.fix) for notice in config.models_notices(path)]
    checks += [
        _warn("config", old, "rename it in the file the warning names")
        for old in config.old_setting_notices(path)
    ]

    try:
        inst = Installation(loaded, path.parent)
    except ConfigError as error:
        checks.append(_fail("worktree root", str(error), "set planning.worktree_root elsewhere"))
        return checks
    checks.append(_ok("worktree root", str(inst.worktree_root)))
    inst.activate()

    checks += _live_installation(inst)
    checks += _repos(inst, run)
    checks += _e2e_holds(inst)
    checks += _e2e_dimensions(inst)
    checks += _gate_usage(inst, run, which)
    checks += _pending_projects(inst)
    checks += _changelogs(inst)
    checks += _review(inst)
    checks += _cassettes(inst)
    checks += _forge_access(inst, run, transport=transport)
    checks += _merge_guards(inst, run)
    checks += _planning_publish(inst, run)
    checks += _pipeline_worktree(inst)
    checks += _state_ignores(inst)
    checks += _timers(inst, run, units, which)
    checks += _toolchain(inst, run, which)
    checks += _agent_commands(inst)
    checks += _runtime(inst, which, run)
    if config.runtime_name(inst.config) == config.CLAUDE_CODE:
        checks += _labelled_accounts(inst, run)
    checks += _notifications(inst, run, which)
    checks += _ssh_keys(inst)
    checks += _verify_env(inst, run)
    checks += _public_content(inst)
    checks += _machine_keys(inst)
    checks += _weak_secrets()
    checks += _environment(inst, run)
    checks.append(_rules_drift(inst))
    checks += _gaps(inst, run)
    checks += _python_tools(inst)
    checks += _skills(inst)
    checks += _telemetry()
    checks += _grafana()
    return checks


def cmd_doctor(args: argparse.Namespace, _inst: Installation | None) -> int:
    checks = run_doctor(args.config)
    for check in checks:
        print(f"{check.status:<5} {check.name}: {check.detail}")
        if check.fix:
            print(f"      fix: {check.fix}")
    failed = sum(check.status == "FAIL" for check in checks)
    warned = sum(check.status == "warn" for check in checks)
    noted = sum(check.status == "info" for check in checks)
    print(f"\n{len(checks)} check(s): {failed} failed, {warned} warning(s), {noted} note(s)")
    return 1 if failed else 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("doctor", help="check this installation is runnable")
    parser.set_defaults(func=cmd_doctor, needs_installation=False)
