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
from agent_build_kit.budget import cut_tail
from agent_build_kit.config import (
    CONFIG_FILENAME,
    RepoConfig,
    Tier2Split,
    by_project,
    owning_project,
    tier2_splits,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.planning_sync import (
    PlanningMode,
    SyncOutcome,
    default_tip_ref,
    in_repo_name,
    planning_mode,
    sync_planning,
)
from agent_build_kit.pipeline.tier2 import (
    Tier2Selection,
    build_selection,
    listing_runner,
    selection_unavailable,
)
from agent_build_kit.pipeline.tier2_holds import repo_holds
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.profiles.base import AppliesTier2Selection, ToolchainProfile, is_doc_path

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
    change in every member that depends on it. Both are decided by the profile
    of the project a path belongs to (`profile`, else the repo's, where it
    belongs to none). Then the first rule whose prefix matches decides; a path
    matching nothing deploys nothing.
    """
    fallback = profile or profiles.get(repo.profile)
    commands: list[Command] = []

    def add(path: str) -> None:
        for rule in repo.deploy.rules:
            if path == rule.prefix or path.startswith(rule.prefix):
                commands.extend(tuple(c) for c in rule.run if tuple(c) not in commands)
                return

    for path in paths:
        project = owning_project(repo.projects, path)
        profile = profiles.for_project(project, fallback)
        prefix = project.prefix if project else ""
        if is_doc_path(path) or profile.is_test_path(path):
            continue
        add(path)
        # Members are named relative to the project's own directory.
        root = checkout / prefix
        member = profile.member_of(root, path.removeprefix(prefix))
        if member is not None:
            for dependent in profile.dependents(root, member):
                add(f"{prefix}{dependent}/")
    return commands


class SplitHeld(Exception):
    """A held tier 2 split holds a live test among the change's files: the verification
    waits for the split to be released, as it does for a busy stack."""

    def __init__(self, splits: list[str]) -> None:
        super().__init__(f"tier 2 split {', '.join(splits)} is held")
        self.splits = splits


def _live_selection(
    repo: RepoConfig,
    splits: tuple[Tier2Split, ...],
    *,
    held: tuple[str, ...] = (),
    only: str | None = None,
) -> Tier2Selection:
    """The selection of a repo's live tests over its `splits`, less the `held` ones (or only
    `only`) and less the tests only the dev stack runs; the profile renders it."""
    selection = build_selection(repo.tests.tier2_marker, splits, held=held, only=only)
    if (exclude := repo.tests.dev_stack_marker) and not selection.empty:
        selection = selection.model_copy(update={"none_of": (exclude, *selection.none_of)})
    return selection


def _acceptance_runs(
    repo: RepoConfig,
    paths: list[str],
    checkout: Path,
    fallback: ToolchainProfile,
    *,
    splits: tuple[Tier2Split, ...] = (),
    held: tuple[str, ...] = (),
) -> list[tuple[ToolchainProfile, Path, list[str]]]:
    """The live tests of the changed `paths`, as (profile, directory to run in, command):
    each project's own profile is asked about the paths under it, from its directory; the
    repo's profile about the rest, from the checkout root. The `held` splits of `splits` are
    left out when the profile can apply a selection."""
    runs = []
    for project, group in by_project(repo.projects, paths):
        profile = profiles.for_project(project, fallback)
        directory = checkout / project.prefix if project else checkout
        marker, exclude = repo.tests.tier2_marker, repo.tests.dev_stack_marker
        if (
            held
            and isinstance(profile, AppliesTier2Selection)
            and not selection_unavailable(profile, dev_stack_script=False, splits=splits)
        ):
            selection = _live_selection(repo, splits, held=held)
            if selection.empty:
                continue
            marker, exclude = profile.expression(selection.marker, selection), ""
        commands = profile.acceptance_commands(
            directory,
            group,
            marker=marker,
            exclude_marker=exclude,
            root_extras=repo.tests.root_extras,
        )
        runs += [(profile, directory, command) for command in commands]
    return runs


def _held_live_tests(
    repo: RepoConfig,
    runs: list[tuple[ToolchainProfile, Path, list[str]]],
    splits: tuple[Tier2Split, ...],
    held: tuple[str, ...],
    *,
    run: Run,
    env: dict[str, str],
) -> list[str]:
    """The `held` splits that hold a live test among the `runs` (the commands as they run
    with nothing left out). A listing that fails says nothing about the split, so the split
    is taken to hold a test: the verification waits rather than passing without it."""
    found: list[str] = []
    for profile, directory, command in runs:
        if not isinstance(profile, AppliesTier2Selection):
            continue
        lister = listing_runner(run, directory, env)
        for name in held:
            listed = profile.list_tests(
                command, _live_selection(repo, splits, only=name), run=lister
            )
            if name not in found and (listed is None or listed):
                found.append(name)
    return found


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
    mine = [u for u in units if u.carries(change) and u.state == "merged" and u.pr]
    ids = sorted(u.id for u in mine)
    files: dict[str, list[str]] = {}
    for unit in mine:
        assert unit.pr is not None  # `mine` holds only units with a PR
        files.setdefault(unit.repo, [])
        files[unit.repo] += [f for f in pr_files(unit.repo, unit.pr) if f not in files[unit.repo]]

    notes: list[str] = []  # what the planning sync said, kept in whatever detail results

    def result(passed: bool, detail: str = "", deployed: list[str] | None = None) -> Verification:
        return Verification(
            change=change,
            passed=passed,
            detail="\n".join([*notes, detail] if detail else notes),
            deployed=deployed or [],
            units=ids,
            at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    checkouts = installation.checkouts
    repos = installation.deploy_order(list(files))
    plans: dict[str, list[Command]] = {}
    tests: dict[str, list[tuple[ToolchainProfile, Path, list[str]]]] = {}
    waiting: list[str] = []
    for name in repos:
        repo = installation.repo(name)
        profile = profiles.get(repo.profile)
        splits = tier2_splits(repo, installation.config)
        holds = repo_holds(installation.config, repo, installation.state_dir).held
        held = tuple(split.name for split in splits if split.name in holds)
        plans[name] = deploy_commands(repo, files[name], checkout=checkouts[name], profile=profile)
        tests[name] = _acceptance_runs(
            repo, files[name], checkouts[name], profile, splits=splits, held=held
        )
        if held:
            waiting += _held_live_tests(
                repo,
                _acceptance_runs(repo, files[name], checkouts[name], profile),
                splits,
                held,
                run=run,
                env={**os.environ, **(env or {}), **live_credentials(repo, checkouts[name])},
            )
    # Before anything is pulled or deployed: the verification is tried again once released.
    if waiting:
        raise SplitHeld(sorted(set(waiting)))

    for name in repos:
        if not (plans[name] or tests[name]):
            continue
        repo = installation.repo(name)
        planning_root = (
            planning_mode(installation) == PlanningMode.PIPELINE_WORKTREE
            and in_repo_name(installation) == name
        )
        # A path outside the root cannot be dirty in this tree, and git refuses it as a pathspec.
        exempt = [
            p
            for p in installation.planning_paths
            if p != CONFIG_FILENAME and not Path(p).is_absolute()
        ]
        refused = _clean_default_branch(
            checkouts[name], run, repo, exempt if planning_root else [], detached_ok=planning_root
        )
        if refused:
            return result(False, f"{checkouts[name]}: {refused} — left for a person to sort out")
        if planning_root:
            synced = sync_planning(installation, notes.append)
            if synced.outcome == SyncOutcome.STOPPED:
                return result(False, f"{checkouts[name]}: planning sync stopped: {synced.reason}")
            continue
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
        repo_env = {**base_env, **live_credentials(repo, checkouts[name])}
        for profile, directory, command in tests[name]:
            done = run(command, cwd=directory, env=repo_env)
            # "nothing selected" is not a failure: the change's live tests
            # may all be ones this step deliberately leaves out.
            if done.returncode not in (0, profile.no_tests_collected_exit):
                return result(
                    False,
                    f"live tests failed — {name}: {' '.join(command)}\n{_output(done)}",
                    deployed,
                )

    return result(True, deployed=deployed)


def _clean_default_branch(
    checkout: Path,
    run: Run,
    repo: RepoConfig,
    exempt: Iterable[str] = (),
    *,
    detached_ok: bool = False,
) -> str:
    """Why this checkout is not a clean default branch, or "". `exempt` paths are left out of the
    dirty check; `detached_ok` accepts a HEAD detached at the default branch's tip."""
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=checkout).stdout.strip()
    if detached_ok and branch == "HEAD":
        lacks = _lacked_commits(checkout, run, repo.default_branch)
        if lacks:
            return f"behind {repo.default_branch}, lacking:\n{lacks}"
    elif branch != repo.default_branch:
        return f"not on {repo.default_branch} (on {branch or 'a detached HEAD'})"
    # Paths the running system itself writes into the checkout say nothing
    # about work in progress, so they are left out of the check.
    ignored = [f":(exclude){path}" for path in [*repo.deploy.live_written, *exempt]]
    status = ["git", "status", "--porcelain", "--untracked-files=no", "--", ".", *ignored]
    checked = run(status, cwd=checkout)
    if checked.returncode:
        return f"git status failed:\n{_output(checked)}"
    if checked.stdout.strip():
        return f"has uncommitted changes:\n{checked.stdout.rstrip()}"
    return ""


def _lacked_commits(checkout: Path, run: Run, default: str) -> str:
    """The commits of the default branch's tip that a detached HEAD lacks, one per line."""
    tip = default_tip_ref(checkout, default)
    return run(["git", "log", "--oneline", f"HEAD..{tip}"], cwd=checkout).stdout.strip()


def _output(done: subprocess.CompletedProcess) -> str:
    return cut_tail(f"{done.stdout or ''}{done.stderr or ''}", 3000)


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
