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
import re
import shlex
import shutil
import socket
import subprocess
import tomllib
from collections.abc import Callable
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
from agent_build_kit.config import CommandProvider, ConfigError, WorkspaceConfig
from agent_build_kit.forges.transport import Transport, TransportError, credential_for
from agent_build_kit.init.detect import DEV_STACK_SCRIPT, detect_repo
from agent_build_kit.init.scaffold import RULES_CHANGES, RULES_VERSION, rules_version
from agent_build_kit.installation import Installation, _resolve, load_config
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes import policy_check
from agent_build_kit.settings import settings

Run = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], str | None]

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
    for name, repo in inst.repos.items():
        path = repo.path.expanduser()
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


GITHUB_API = "https://api.github.com"


def _github_account(repo: forges.RepoId, run: Run, transport: httpx.BaseTransport | None) -> str:
    """The account this repo's credential acts as, from the cheapest
    authenticated endpoint. Raises `TransportError` naming what failed."""
    credentials = credential_for(repo.forge, repo.account, run=run)
    try:
        answer = Transport(GITHUB_API, credentials, transport=transport).request("GET", "/user")
    except TransportError as error:
        raise type(error)(f"{error} (credential from {credentials.source})") from error
    return f"{answer.data['login']} via {credentials.source}"


def _forge_access(
    inst: Installation,
    run: Run,
    *,
    transport: httpx.BaseTransport | None = None,
    live: bool = False,
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
        if live and repo.forge == "github":
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
        problem = forge.check_access(repo, run=run)
        if problem:
            checks.append(_fail(title, problem, forge.access_fix(repo)))
        else:
            checks.append(_ok(title, f"{forge.name} {forges.key(repo)}"))
    return checks


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
        forge, repo = inst.forge_of(name)
        branch = inst.repo(name).default_branch
        unguarded = forge.merge_guard(repo, branch=branch, run=run)
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
        path = repo.path.expanduser()
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
            except NotImplementedError:
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
    for name, repo in inst.repos.items():
        path = repo.path.expanduser()
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


def _runtime(inst: Installation, which: Which) -> list[Check]:
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
        # A probe would spawn the very command that does not resolve.
        checks.append(
            _warn(
                "runtime policy",
                f"not checked: the agent command {command[0]} does not resolve",
                "fix the runtime check above, then run `abk doctor` again",
            )
        )
        return checks
    try:
        report = policy_check.checked(runtime, inst.root, cache=policy_check.cache_path(inst))
    except Exception as error:  # noqa: BLE001 - whatever the runtime raised is the finding
        checks.append(
            _fail(
                "runtime policy",
                f"could not be checked: {type(error).__name__}: {error}",
                "run `abk doctor` again once the runtime can answer",
            )
        )
        return checks
    if report.ok:
        checks.append(_ok("runtime policy", "every forbidden class is refused"))
    else:
        checks.append(
            _fail(
                "runtime policy",
                f"not refused: {', '.join(report.unenforced)}",
                policy_check.fix_for(name, entry, report),
            )
        )
    return checks


def _skills(inst: Installation) -> list[Check]:
    checks = []
    targets = {"planning": inst.root, **inst.checkouts}
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


def run_doctor(
    config_path: Path | None,
    *,
    cwd: Path | None = None,
    run: Run | None = None,
    which: Which | None = None,
    units: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[Check]:
    # A stand-in `run` without a stand-in transport is a test of something else:
    # it must not reach a real host.
    live = transport is not None or run is None
    run = run or subprocess.run
    which = which or shutil.which
    try:
        path = config.locate(config_path, cwd=cwd)
        loaded: WorkspaceConfig = load_config(path)
    except ConfigError as error:
        return [_fail("config", str(error), "run `abk init`, or fix abk.yaml")]
    checks = [_ok("config", str(path))]

    try:
        inst = Installation(loaded, path.parent)
    except ConfigError as error:
        checks.append(_fail("worktree root", str(error), "set planning.worktree_root elsewhere"))
        return checks
    checks.append(_ok("worktree root", str(inst.worktree_root)))
    inst.activate()

    checks += _repos(inst, run)
    checks += _forge_access(inst, run, transport=transport, live=live)
    checks += _merge_guards(inst, run)
    checks += _timers(inst, run, units, which)
    checks += _toolchain(inst, run, which)
    checks += _runtime(inst, which)
    checks += _ssh_keys(inst)
    checks += _verify_env(inst, run)
    checks.append(_rules_drift(inst))
    checks += _gaps(inst, run)
    checks += _python_tools(inst)
    checks += _skills(inst)
    checks += _telemetry()
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
