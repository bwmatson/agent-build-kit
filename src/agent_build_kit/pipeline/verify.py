"""Deploy a merged change and check it against the live stack, before archive.

A pipeline that stops at merge leaves deploys to whoever remembers them, and
nothing looks at the live system afterwards — a change once merged and
archived while its consumer could not see a single one of the tools it added.

So once every unit of a change has merged, this deploys what the change's PRs
touched — from each repo's own checkout, on its default branch, the way that
repo's `abk.yaml` says — and runs the live-stack tests those PRs added, with
the consumer's own credentials. Archive waits for it to pass. A failure is
recorded and left for a person: nothing here retries on its own, and a
checkout that isn't clean is not this step's to pull into.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.profiles.base import ToolchainProfile, is_doc_path

Run = Callable[..., subprocess.CompletedProcess]
Command = tuple[str, ...]


def deploy_commands(
    repo: RepoConfig,
    paths: Iterable[str],
    *,
    checkout: Path,
    profile: ToolchainProfile | None = None,
) -> list[Command]:
    """What deploys these changed paths, each command once, in first-needed order.

    Two conventions come before the repo's own rules: test and documentation
    paths deploy nothing, and a change inside a library member counts as a
    change in every member that depends on it. Then the first rule whose
    prefix matches decides; a path matching nothing deploys nothing.
    """
    profile = profile or profiles.get(repo.profile)
    commands: list[Command] = []

    def add(path: str) -> None:
        for rule in repo.deploy.rules:
            if path == rule.prefix or path.startswith(rule.prefix):
                commands.extend(tuple(c) for c in rule.run if tuple(c) not in commands)
                return

    for path in paths:
        if is_doc_path(path) or profile.is_test_path(path):
            continue
        add(path)
        member = profile.member_of(checkout, path)
        if member is not None:
            for dependent in profile.dependents(checkout, member):
                add(f"{dependent}/")
    return commands


_CREDENTIALS = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)=\((?P<names>[^)]*)\)", re.M)


def live_credentials(repo: RepoConfig, checkout: Path) -> dict[str, str]:
    """The credentials the repo's live-stack tests read — the names its
    `abk.yaml` points at (a shell array in its dev stack script), valued
    from its env file."""
    source = repo.deploy.credentials
    if source is None or source.names_from is None:
        return {}
    script = checkout / source.names_from.file
    names: list[str] = []
    if script.exists():
        for match in _CREDENTIALS.finditer(script.read_text()):
            if match["name"] == source.names_from.shell_array:
                names = match["names"].split()
                break
    values = _env_file(checkout / source.values_from)
    return {name: values[name] for name in names if values.get(name)}


def _env_file(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Verification(Frozen):
    change: str
    passed: bool
    detail: str = ""
    deployed: list[str] = []
    # The merged units this ran over, so a change that gains a fix later is
    # verified again rather than trusted on an old result.
    units: list[str] = []
    at: str = ""


def verify_change(
    change: str,
    units: list[StoredUnit],
    *,
    installation: Installation,
    pr_files: Callable[[str, int], list[str]],
    run: Run,
    env: dict[str, str] | None = None,
) -> Verification:
    """`env` is what the live tests get on top of the process environment and
    each repo's own credentials — the consumer's key, resolved by the caller
    (`Installation.verify_env`)."""
    mine = [u for u in units if u.change == change and u.state == "merged" and u.pr]
    ids = sorted(u.id for u in mine)
    files: dict[str, list[str]] = {}
    for unit in mine:
        assert unit.pr is not None  # `mine` holds only units with a PR
        files.setdefault(unit.repo, [])
        files[unit.repo] += [f for f in pr_files(unit.repo, unit.pr) if f not in files[unit.repo]]

    def result(passed: bool, detail: str = "", deployed: list[str] | None = None) -> Verification:
        return Verification(
            change=change,
            passed=passed,
            detail=detail,
            deployed=deployed or [],
            units=ids,
            at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    checkouts = installation.checkouts
    repos = installation.deploy_order(list(files))
    plans: dict[str, list[Command]] = {}
    tests: dict[str, list[list[str]]] = {}
    for name in repos:
        repo = installation.repo(name)
        profile = profiles.get(repo.profile)
        plans[name] = deploy_commands(repo, files[name], checkout=checkouts[name], profile=profile)
        tests[name] = profile.acceptance_commands(
            checkouts[name],
            files[name],
            marker=repo.tests.tier2_marker,
            exclude_marker=repo.tests.dev_stack_marker,
            root_extras=repo.tests.root_extras,
        )

    for name in repos:
        if not (plans[name] or tests[name]):
            continue
        repo = installation.repo(name)
        refused = _clean_default_branch(checkouts[name], run, repo)
        if refused:
            return result(False, f"{checkouts[name]}: {refused} — left for a person to sort out")
        pulled = run(["git", "pull", "--ff-only", "-q"], cwd=checkouts[name])
        if pulled.returncode:
            return result(False, f"{checkouts[name]}: git pull failed\n{_output(pulled)}")

    deployed: list[str] = []
    for name in repos:
        repo = installation.repo(name)
        for command in plans[name]:
            full = list(command)
            if repo.deploy.needs_ssh_agent and command[0] in repo.deploy.agent_for:
                # The image builds fetch a dependency over SSH; without an
                # agent holding the key they fail with SSH_AUTH_SOCK unset.
                key = repo.deploy.ssh_key
                if key is None:
                    return result(
                        False,
                        f"{name}: deploy.needs_ssh_agent is set but deploy.ssh_key is not",
                        deployed,
                    )
                full = [
                    "ssh-agent",
                    "sh",
                    "-c",
                    'ssh-add -q "$0" && exec "$@"',
                    str(key.expanduser()),
                    *command,
                ]
            done = run(full, cwd=checkouts[name])
            label = f"{name}: {' '.join(command)}"
            if done.returncode:
                return result(False, f"deploy failed — {label}\n{_output(done)}", deployed)
            deployed.append(label)

    base_env = {**os.environ, **(env or {})} if any(tests.values()) else {}
    for name in repos:
        repo = installation.repo(name)
        profile = profiles.get(repo.profile)
        repo_env = {**base_env, **live_credentials(repo, checkouts[name])}
        for command in tests[name]:
            done = run(command, cwd=checkouts[name], env=repo_env)
            # "nothing selected" is not a failure: the change's live tests
            # may all be ones this step deliberately leaves out.
            if done.returncode not in (0, profile.no_tests_collected_exit):
                return result(
                    False,
                    f"live tests failed — {name}: {' '.join(command)}\n{_output(done)}",
                    deployed,
                )

    return result(True, deployed=deployed)


def _clean_default_branch(checkout: Path, run: Run, repo: RepoConfig) -> str:
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=checkout).stdout.strip()
    if branch != repo.default_branch:
        return f"not on {repo.default_branch} (on {branch or 'a detached HEAD'})"
    # Paths the running system itself writes into the checkout say nothing
    # about work in progress, so they are left out of the check.
    ignored = [f":(exclude){path}" for path in repo.deploy.live_written]
    status = ["git", "status", "--porcelain", "--untracked-files=no", "--", ".", *ignored]
    changes = run(status, cwd=checkout).stdout
    if changes.strip():
        return f"has uncommitted changes:\n{changes.rstrip()}"
    return ""


def _output(done: subprocess.CompletedProcess) -> str:
    return f"{done.stdout or ''}{done.stderr or ''}"[-3000:]


class VerifyRecord:
    """The last verification of each change, in the state directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def get(self, change: str) -> Verification | None:
        raw = self._read().get(change)
        return Verification.model_validate(raw) if raw else None

    def put(self, verification: Verification) -> None:
        recorded = self._read()
        recorded[verification.change] = verification.model_dump()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(recorded, indent=2) + "\n")
