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
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from agent_build_kit import __version__, config, forges, openspec, profiles, runtimes, skills
from agent_build_kit.config import CommandProvider, ConfigError, WorkspaceConfig
from agent_build_kit.init.detect import DEV_STACK_SCRIPT, detect_repo
from agent_build_kit.init.scaffold import RULES_CHANGES, RULES_VERSION, rules_version
from agent_build_kit.installation import Installation, _resolve, load_config
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes import policy_check

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
        result = run(
            ["git", "config", "--local", "--get", "user.email"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            checks.append(
                _fail(
                    f"repo {name}",
                    f"{path} has no repo-local user.email",
                    f"git -C {path} config user.email <email> (and user.name)",
                )
            )
            continue
        checks.append(_ok(f"repo {name}", f"{path}, commits as {result.stdout.strip()}"))
    return checks


def _forge_access(inst: Installation, run: Run) -> list[Check]:
    """Whether each repo's host will answer for it.

    Per repo rather than per account: "can we act here" is the question the
    pipeline actually asks, and it is the same question on every host, where
    "which accounts does this workspace touch" was a GitHub owner's shape.
    """
    checks = []
    for name in sorted(inst.repos):
        forge, repo = inst.forge_of(name)
        problem = forge.check_access(repo, run=run)
        title = f"forge {name}"
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
        f"fold in what you want of these, in your own words, then stamp it v{RULES_VERSION}",
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


def run_doctor(
    config_path: Path | None,
    *,
    cwd: Path | None = None,
    run: Run | None = None,
    which: Which | None = None,
) -> list[Check]:
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
    checks += _forge_access(inst, run)
    checks += _merge_guards(inst, run)
    checks += _toolchain(inst, run, which)
    checks += _runtime(inst, which)
    checks += _ssh_keys(inst)
    checks += _verify_env(inst, run)
    checks.append(_rules_drift(inst))
    checks += _gaps(inst, run)
    checks += _skills(inst)
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
