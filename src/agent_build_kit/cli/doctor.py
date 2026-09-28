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
import difflib
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml

from agent_build_kit import __version__, config, openspec, skills
from agent_build_kit.config import CommandProvider, ConfigError, WorkspaceConfig
from agent_build_kit.init.detect import DEV_STACK_SCRIPT, detect_repo
from agent_build_kit.init.scaffold import render_rules, rules_of
from agent_build_kit.installation import Installation, _resolve
from agent_build_kit.model import Frozen

Run = Callable[..., subprocess.CompletedProcess]
Which = Callable[[str], str | None]

Status = Literal["ok", "warn", "FAIL"]


class Check(Frozen):
    name: str
    status: Status
    detail: str
    fix: str = ""


def _ok(name: str, detail: str) -> Check:
    return Check(name=name, status="ok", detail=detail)


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


def _owners(inst: Installation, run: Run) -> list[Check]:
    checks = []
    for owner in sorted(inst.owners()):
        result = run(
            ["gh", "auth", "token", "--user", owner], capture_output=True, text=True, check=False
        )
        if result.returncode or not result.stdout.strip():
            checks.append(
                _fail(f"gh {owner}", "no token for this account", f"gh auth login (as {owner})")
            )
        else:
            checks.append(_ok(f"gh {owner}", "token available"))
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
    path = inst.specs_dir / "config.yaml"
    if not path.is_file():
        return _warn("rules", f"{path} is missing", "run `abk init` again to write it")
    try:
        current = rules_of(path.read_text())
    except yaml.YAMLError as error:
        return _warn("rules", f"{path} is not valid YAML: {error}", "fix the file")
    expected = rules_of(render_rules(list(inst.repos)))

    missing: list[str] = []
    for artifact, rules in expected.get("rules", {}).items():
        present = current.get("rules", {}).get(artifact) or []
        missing += [f"{artifact}: {rule}" for rule in rules if rule not in present]
    expected_guidance = expected.get("operations", {}).get("apply", {}).get("guidance", [])
    present_guidance = current.get("operations", {}).get("apply", {}).get("guidance") or []
    missing += [f"apply guidance: {g}" for g in expected_guidance if g not in present_guidance]
    if not missing:
        return _ok("rules", "openspec/config.yaml carries the framework's rules")

    diff = "\n".join(
        difflib.unified_diff(
            yaml.safe_dump(expected, sort_keys=False).splitlines(),
            yaml.safe_dump(current, sort_keys=False).splitlines(),
            fromfile="framework rules",
            tofile=str(path.relative_to(inst.root)),
            lineterm="",
        )
    )
    return _warn(
        "rules",
        f"{len(missing)} framework rule(s) missing or changed in {path.name}:\n{diff}",
        "merge the missing rules back in (extra rules of your own are fine)",
    )


def _gaps(inst: Installation, run: Run) -> list[Check]:
    checks = []
    for name, repo in inst.repos.items():
        path = repo.path.expanduser()
        if not path.is_dir():
            continue
        detection = detect_repo(path, run=run)
        prefixes = [rule.prefix for rule in repo.deploy.rules]
        gaps: list[str] = []
        for service in detection.service_dirs:
            if not any(
                prefix == f"{service}/" or prefix.startswith(f"{service}/") for prefix in prefixes
            ):
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
        loaded: WorkspaceConfig = config.load(path)
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
    checks += _owners(inst, run)
    checks += _toolchain(inst, run, which)
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
    print(f"\n{len(checks)} check(s): {failed} failed, {warned} warning(s)")
    return 1 if failed else 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("doctor", help="check this installation is runnable")
    parser.set_defaults(func=cmd_doctor, needs_installation=False)
