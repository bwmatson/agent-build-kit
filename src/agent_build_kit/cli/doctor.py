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
import tempfile
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import httpx
import yaml

from agent_build_kit import (
    __version__,
    claude_account,
    config,
    forges,
    openspec,
    profiles,
    runtimes,
    sandboxes,
    skills,
    timers,
)

# Reached through the module so a test can replace the table's `machine_settings`.
from agent_build_kit import machine_settings as machine_table
from agent_build_kit import settings as settings_module
from agent_build_kit.config import (
    OVERLAY_FILENAME,
    REVIEWER_READING_LIMIT,
    CommandProvider,
    ConfigError,
    EnvironmentConfig,
    NotificationProvider,
    PlanningPublish,
    PolicyMarker,
    RepoConfig,
    WorkspaceConfig,
    buffered,
    ceilings_in_effect,
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
from agent_build_kit.machine_files import CONFIG_LOCAL_FILES, MACHINE_FILES, holds, present
from agent_build_kit.model import E2E_LOCK_FILE, Frozen, TestTier
from agent_build_kit.notify.windows import (
    BURNTTOAST_VERSION,
    INSTALL_COMMAND,
    MODULE_CHECK_COMMAND,
)
from agent_build_kit.path_discovery import checkout_root, find_up
from agent_build_kit.path_patterns import matches, normalize
from agent_build_kit.pipeline import agent_commands, lock_probe, mounts
from agent_build_kit.pipeline.e2e import dimension_lines
from agent_build_kit.pipeline.e2e_holds import HELD_FILE, current_holds, hold_text
from agent_build_kit.pipeline.environment import matched_inputs
from agent_build_kit.pipeline.file_lock import try_file_lock
from agent_build_kit.pipeline.gate_holds import gate_standing, split_gates
from agent_build_kit.pipeline.install_record import STAGING
from agent_build_kit.pipeline.mounts import Mount
from agent_build_kit.pipeline.original_copy import COPY_PATTERN
from agent_build_kit.pipeline.pending import describe, pending_projects
from agent_build_kit.pipeline.planning_repo import (
    common_dir,
    is_worktree_of,
)
from agent_build_kit.pipeline.planning_sync import (
    in_repo_name,
    live_notice,
    live_pipeline_worktree,
    read_pipeline_marker,
    working_copy,
)
from agent_build_kit.pipeline.planning_view import (
    installation_state_inside_repo,
    working_copy_view,
)
from agent_build_kit.pipeline.shell import git, git_out, is_ignored, is_tracked, tracked_toplevel
from agent_build_kit.pipeline.usage_guard import gate_result
from agent_build_kit.pipeline.workspaces import worktree_entries, worktree_key
from agent_build_kit.profiles.base import ProfileUnsupported
from agent_build_kit.redaction import MIN_LENGTH
from agent_build_kit.redaction import active as active_redactor
from agent_build_kit.replay.review import directories, overdue, waiting
from agent_build_kit.runtimes import claude_code, policy_check, providers
from agent_build_kit.runtimes.base import AgentRuntime, Run, Which, account_report_of
from agent_build_kit.sandboxes import held
from agent_build_kit.sandboxes.base import system_folders
from agent_build_kit.sandboxes.policy import (
    builtin_reads,
    git_directory,
    git_parts,
    git_reads,
    policy_entries,
)
from agent_build_kit.settings import settings
from agent_build_kit.trackers.report import standing

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
        if checkout_root(path) != path.resolve():
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


def _unit_worktrees(inst: Installation) -> list[Check]:
    """The unit worktrees under the worktree root that sit in a folder other than their repo's
    key, and the registered ones whose directory is gone. Reads git, writes nothing."""
    name = "unit worktrees"
    # By repository, not checkout: two checkouts that are worktrees of one repository list the
    # same entries.
    keys: dict[Path, set[str]] = {}
    checkouts: dict[Path, Path] = {}
    for repo in inst.repos:
        path = inst.checkouts[repo]
        common = common_dir(path)
        if common is not None:
            checkouts.setdefault(common, path)
            keys.setdefault(common, set()).add(worktree_key(repo))
    root = inst.worktree_root.resolve()
    found = []
    for common, names in keys.items():
        folders = {root / key for key in names}
        checkout = checkouts[common]
        for entry in worktree_entries(checkout):
            if not entry.path.resolve().is_relative_to(root):
                continue
            if entry.prunable:
                found.append(
                    _warn(
                        name,
                        f"{entry.path} is registered for {checkout} but its directory is gone",
                        f"run `git worktree prune` in {checkout}",
                    )
                )
            elif entry.path.resolve().parent not in folders:
                found.append(
                    _info(
                        name,
                        f"{entry.path} is under a folder other than {' or '.join(sorted(names))}"
                        " and is adopted where it is",
                        f"in {checkout}, `git worktree move {entry.path} <new path>` "
                        "when its unit is idle",
                    )
                )
    return found or [_ok(name, f"every unit worktree is under {root}/<repo>/")]


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
    checks.append(_buffered_ceilings(inst))
    near = REVIEWER_READING_LIMIT * 4 // 5
    scopes = [("review.ceilings", None), *((f"repos.{n}", r) for n, r in inst.repos.items())]
    for label, scope in scopes:
        top = buffered(ceilings_in_effect(scope, inst.config).auto, review.ceiling_buffer)
        if top > near and (scope is None or scope.review.ceilings.auto is not None):
            checks.append(
                _warn(
                    f"review ceiling buffer of {label}",
                    f"the buffered auto ceiling of {top} is near the reviewer's limit of "
                    f"{REVIEWER_READING_LIMIT} lines",
                    "lower the auto ceiling or `review.ceiling_buffer`",
                )
            )
    if review.split_rounds == 0:
        checks.append(
            _warn(
                "review split_rounds",
                "`split_rounds` is 0, so every unit over its tier goes to a person",
                "set `review.split_rounds` to 1 or 2",
            )
        )
    return checks


def _buffered_ceilings(inst: Installation) -> Check:
    review = inst.config.review
    ceilings = ceilings_in_effect(None, inst.config)
    shown = ", ".join(
        f"{tier} {buffered(getattr(ceilings, tier), review.ceiling_buffer)}"
        for tier in ("auto", "light", "full")
    )
    return _ok("review ceilings", f"buffered by {review.ceiling_buffer}: {shown}")


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
    true. Once a class may land without a person, the pipeline merges and the
    same fact is a warning: the hook is then the only guard on that branch.
    """
    may_land = bool(inst.config.review.auto_land.classes)
    checks = []
    for name in sorted(inst.repos):
        branch = inst.repo(name).default_branch
        unguarded = _guard_of(inst, name, run)
        title = f"merge guard {name}"
        if unguarded:
            if may_land:
                checks.append(
                    _warn(
                        title,
                        unguarded,
                        "nothing server-side refuses a merge: the command policy hook is the "
                        "only guard, and it does nothing against the pipeline's own merge, so "
                        "add branch protection or empty `review.auto_land.classes`",
                    )
                )
            else:
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


# What the state directory held before the machine-local files moved to the local directory.
_LOCAL_LEFTOVERS = ("locks", "leases", E2E_LOCK_FILE, "environment.lock", "unit-graphs.sqlite")


def _local_dir(inst: Installation, mount_of: Callable[[Path], Mount]) -> list[Check]:
    """The local directory is on a local filesystem, and no machine-local file is left behind
    in the state directory."""
    local = inst.local_dir
    mount = mount_of(local)
    if not mount.local:
        return [
            _fail(
                "local dir",
                f"{local} is on {mount.fstype}, which is not a local filesystem: the checkpointer "
                "database and the host locks are unsafe there",
                "set planning.local_dir or ABK_LOCAL_DIR to a directory on a local disk",
            )
        ]
    checks = [_ok("local dir", f"{local} ({mount.fstype})")]
    if local.resolve() == inst.state_dir.resolve():
        return checks
    for name in _LOCAL_LEFTOVERS:
        old = inst.state_dir / name
        if old.exists():
            checks.append(
                _warn(
                    "local dir",
                    f"{old} is left in the state directory and no longer used",
                    f"delete {old}",
                )
            )
    return checks


def _state_locking(inst: Installation, mount_of: Callable[[Path], Mount]) -> list[Check]:
    """Where the durable state is mounted, and whether locks taken there exclude a second
    process. A local disk says nothing unless the probe fails."""
    mount = mount_of(inst.state_dir)
    checks: list[Check] = []
    if not mount.local:
        checks.append(
            _info(
                "state mount",
                f"durable state on {mount.fstype} {mount.source}: one pipeline host only",
            )
        )
        if "hard" in mount.options.split(","):
            checks.append(
                _warn(
                    "state mount",
                    f"{mount.fstype} {mount.source} is mounted `hard`: a share that stops "
                    "answering blocks the pipeline in the kernel, past any lock timeout",
                    "mount with `soft` and a `timeo`, or the `intr` equivalent for the share",
                )
            )
    result = lock_probe.probe_locking(inst.state_dir, mount=mount)
    if not result.passed:
        checks.append(_fail("state locking", result.detail, result.fix))
    elif not mount.local:
        checks.append(_ok("state locking", result.detail))
    return checks


def _machine_files(inst: Installation) -> list[Check]:
    """In a live pipeline worktree: each machine file the working copy has must be carried."""
    if in_repo_name(inst) is None:
        return []
    live = live_pipeline_worktree(inst)
    if live is None:
        return []
    source = working_copy(inst)
    if source is None:
        return []
    names = present(source)
    title = "machine files"
    if not names:
        return [
            _warn(
                title,
                f"{source} holds none of {', '.join(MACHINE_FILES)}, so ticks run on defaults",
                "create abk.local.yaml (paths, worktree root, limits), .env (copy .env.example) "
                "and scrub.local in the working copy, then `abk install-timers`",
            )
        ]
    bad = []
    for name in names:
        path = live / name
        if path.is_symlink() and not path.exists():
            bad.append(f"{name} (dangling link)")
        elif not path.exists():
            bad.append(f"{name} (missing)")
        elif not holds(path, source / name):
            bad.append(f"{name} (differs)")
    if bad:
        return [_fail(title, f"not carried into {live}: {', '.join(bad)}", "abk install-timers")]
    return [_ok(title, f"{', '.join(names)} carried into {live}")]


def _state_ignores(inst: Installation) -> list[Check]:
    """In an in-repo installation: the root's `.gitignore` must ignore the state files."""
    if in_repo_name(inst) is None or not inst.state_dir.is_relative_to(inst.root):
        return []
    ignore = inst.root / ".gitignore"
    text = ignore.read_text() if ignore.is_file() else ""
    missing = missing_state_ignores(text, inst.shown(inst.state_dir))
    if not missing:
        return [_ok("state ignores", str(ignore))]
    return [
        _warn(
            "state ignores",
            f"{ignore} lacks: {', '.join(missing)}",
            "abk init (adds the lines in a marked block)",
        )
    ]


CHANGE_LOCKS = "change locks"


def _change_locks(inst: Installation, fix: bool) -> list[Check]:
    """Lock files an earlier release left beside a change's files. With `fix`, the untracked
    ones nobody holds are deleted; a held one is reported as in use and a tracked one is named
    for `git rm`."""
    stray = sorted(inst.changes_dir.rglob("*.md.lock")) if inst.changes_dir.is_dir() else []
    shown = {path: str(path.relative_to(inst.root)) for path in stray}
    kept: list[Path] = []
    in_use: list[Path] = []
    tracked: list[Path] = []
    for path in stray:
        if is_tracked(inst.root, shown[path]):
            tracked.append(path)
        elif not fix:
            kept.append(path)
        else:
            with try_file_lock(path) as taken:
                if taken:
                    path.unlink()
                else:
                    in_use.append(path)
    checks = []
    if kept:
        checks.append(
            _warn(
                CHANGE_LOCKS,
                f"{len(kept)} stray lock file(s) under {inst.changes_dir}",
                "abk doctor --fix",
            )
        )
    if in_use:
        checks.append(
            _warn(
                CHANGE_LOCKS,
                f"in use, kept: {', '.join(shown[p] for p in in_use)}",
                "run `abk doctor --fix` again when nothing is running",
            )
        )
    if tracked:
        names = " ".join(shown[p] for p in tracked)
        checks.append(
            _warn(
                CHANGE_LOCKS,
                f"git tracks {len(tracked)} lock file(s): {names}",
                f"git rm {names}",
            )
        )
    return checks


def _legacy_state(inst: Installation) -> list[Check]:
    """In an in-repo installation whose state is outside the root: files git still tracks under
    the legacy `runs/` mean the state has not been moved."""
    if in_repo_name(inst) is None or inst.state_dir.is_relative_to(inst.root):
        return []
    tracked = [name for name in git_out(inst.root, "ls-files", "runs").splitlines() if name]
    if not tracked:
        return []
    return [
        _warn(
            "legacy state",
            f"git tracks {len(tracked)} file(s) under runs/; the state of this installation has "
            f"not been moved out of the repository (it is read from {inst.state_dir})",
            "follow docs/runbooks/move-state-out-of-the-repo.md",
        )
    ]


def _planning_view(inst: Installation) -> list[Check]:
    """In an in-repo installation: the working copy's `.planning` link must lead to the state."""
    view = working_copy_view(inst)
    if view is None:
        return []
    if view.problem is None:
        return [_ok("planning view", f"{view.link} -> {inst.state_dir}")]
    return [_warn("planning view", f"{view.link} is {view.problem}", "abk init (makes the link)")]


def _state_location(inst: Installation) -> list[Check]:
    """In an in-repo installation: the state directory must not be inside the repository."""
    inside = installation_state_inside_repo(inst)
    if inside is None:
        return []
    return [
        _warn(
            "state location",
            f"the state directory resolves to {inside}, inside the repository: it dirties the "
            "pipeline worktree and stops its fast-forward sync",
            "set planning.state_dir / ABK_STATE_DIR outside the repository, or drop the setting",
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


def _sandbox_lists(inst: Installation) -> list[Check]:
    """Each repo's assembled read, write and host lists with the source of each entry, so a
    missing path is found before a unit fails on it; nothing while the sandbox is off, which
    `sandbox_check` reports in its one line."""
    if not inst.config.sandbox.enabled:
        return []
    runtime = runtimes.get(config.runtime_name(inst.config))
    checks = []
    for name, repo in inst.repos.items():
        try:
            entries, e2e_entries = (
                policy_entries(
                    inst,
                    name,
                    repo.path,
                    runtime=runtime,
                    profile=profiles.get(repo.profile),
                    account=claude_account.for_repo(inst.config, name),
                    tier=tier,
                )
                for tier in (TestTier.UNIT_TEST, TestTier.E2E_TEST)
            )
        except KeyError:
            continue  # an unknown profile is reported where the repo is
        lines = [f"{e.kind} {e.value} ({e.source})" for e in entries]
        checks.append(_ok(f"policy lists {name}", "\n".join(lines) or "no entries"))
        # What an e2e-test step is granted beyond the above, from `tests.e2e_sandbox`.
        extra = [f"{e.kind} {e.value} ({e.source})" for e in e2e_entries if e not in entries]
        if extra:
            checks.append(_ok(f"policy lists {name} (e2e)", "\n".join(extra)))
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


def _trackers(inst: Installation) -> list[Check]:
    """Each repo that names a tracker: its target and who the credential acts as. A repo with
    no section adds nothing."""
    checks = []
    for name in inst.repos:
        found = standing(name, ask=True)
        title = f"tracker {name}"
        if found is None:
            continue
        match found.state:
            case "ok":
                checks.append(_ok(title, found.text))
            case "refused":
                credential = (
                    f"check the token in {found.token_env}"
                    if found.token_env
                    else "no token_env is set, so the forge's credential for that host is in use: "
                    "check that login or token"
                )
                detail = f"the host did not accept the identity check: {found.text}"
                checks.append(_warn(title, detail, credential))
            case "unsupported":
                checks.append(
                    _warn(
                        title,
                        found.text,
                        f"the installed kit does not implement tracker kind {found.kind!r}: "
                        f"upgrade the kit, or set `kind: none` in repos.{name}.tracker",
                    )
                )
            case "invalid":
                checks.append(_fail(title, found.text, f"fix repos.{name}.tracker in abk.yaml"))
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


def _committed_facts(inst: Installation, toplevel: Path) -> list[Check]:
    """What the tracked abk.yaml's own text says that a public repository must
    not: read straight from the file, offline."""
    document = yaml.safe_load((inst.root / "abk.yaml").read_text()) or {}
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
        if machine_table.holds_home_path(value):
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
    for local in CONFIG_LOCAL_FILES:
        if not (root / local).exists():
            continue
        if is_tracked(root, local):
            checks.append(
                _warn(
                    PUBLIC_CONTENT,
                    f"{local} is tracked",
                    f"git rm --cached {local}, and add `{local}` to .gitignore",
                )
            )
        elif not is_ignored(root, local):
            checks.append(
                _warn(PUBLIC_CONTENT, f"{local} is not ignored", f"add `{local}` to .gitignore")
            )
    found = {*root.glob(COPY_PATTERN), *inst.state_dir.rglob(COPY_PATTERN)}
    # A copy outside the repository cannot be committed to it.
    for copy in sorted(c for c in found if c.resolve().is_relative_to(toplevel)):
        name = copy.resolve().relative_to(toplevel).as_posix()
        if is_tracked(toplevel, name):
            checks.append(
                _warn(
                    PUBLIC_CONTENT,
                    f"{name} is tracked",
                    f"git rm --cached {name}, and add `{COPY_PATTERN}` to .gitignore",
                )
            )
        elif not is_ignored(toplevel, name):
            checks.append(
                _warn(
                    PUBLIC_CONTENT, f"{name} is not ignored", f"add `{COPY_PATTERN}` to .gitignore"
                )
            )
    return checks


def _public_content(inst: Installation) -> list[Check]:
    """Facts that must not reach a public repository, found without a network
    call: the committed abk.yaml's own text, and files that must stay ignored."""
    toplevel = checkout_root(inst.root)
    if toplevel is None:
        return [_ok(PUBLIC_CONTENT, "not a git repository")]
    checks = []
    tracked = is_tracked(inst.root, "abk.yaml")
    if tracked:
        checks += _committed_facts(inst, toplevel)
    checks += _local_files(inst, toplevel)
    if checks:
        return checks
    return [_ok(PUBLIC_CONTENT, "nothing found" if tracked else "abk.yaml is not tracked")]


def _deprecation_fix(key: str) -> str:
    """What to do about a deprecated key: the migration moves the renamed ones, and a key that is
    ignored is deleted by hand."""
    if key == config.REMOVED_REVIEW_ENABLED:
        return "delete `enabled` from the `review` section of abk.yaml (or abk.local.yaml)"
    return "run `abk config --migrate`"


MACHINE_KEYS = "machine keys"
_MACHINE_FIX = f"move it to {OVERLAY_FILENAME} with `abk config --migrate`"
_DEFAULT_FIX = (
    f"fine to commit; move it to {OVERLAY_FILENAME} to differ "
    "(`abk config --migrate --include-defaults` moves it)"
)


def _machine_keys(inst: Installation) -> list[Check]:
    """Settings in the committed abk.yaml that belong to a machine or a person: a warning
    for a machine choice, a note for a default a team may commit."""
    root = inst.root
    top = tracked_toplevel(root, "abk.yaml")
    if top is None:
        return []
    document = read_base(root / "abk.yaml")
    found = machine_table.machine_settings(document, top, root)
    checks = []
    for setting in found:
        key = ".".join(setting.path)
        if setting.kind == "machine":
            detail = f"{key} in abk.yaml {setting.reason}: a machine choice"
            checks.append(_warn(MACHINE_KEYS, detail, _MACHINE_FIX))
        else:
            checks.append(_info(MACHINE_KEYS, f"{key} in abk.yaml: {setting.reason}", _DEFAULT_FIX))
    return checks


def _missing_inputs(environment: EnvironmentConfig, root: Path) -> list[str]:
    return [pattern for pattern, names in matched_inputs(environment, root).items() if not names]


def _tracked_artifacts(environment: EnvironmentConfig, root: Path) -> list[str]:
    """The artifact patterns that cover a file the repository tracks."""
    if not environment.artifacts or checkout_root(root) != root.resolve():
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
        folders = [path, *(path / project.path for project in inst.config.repos[name].projects)]
        seen = set()
        for folder in folders:
            manifest = find_up(["pyproject.toml"], folder, stop=path)
            hooks_file = find_up([".pre-commit-config.yaml"], folder, stop=path)
            if manifest is None or hooks_file is None or (manifest, hooks_file) in seen:
                continue
            seen.add((manifest, hooks_file))
            checks += _python_tools_in(name, path, manifest, hooks_file)
    return checks


def _python_tools_in(name: str, root: Path, manifest: Path, hooks_file: Path) -> list[Check]:
    """The `_python_tools` checks of one repo's manifest and the hook file that goes with it."""
    try:
        hook_repos = (yaml.safe_load(hooks_file.read_text()) or {}).get("repos") or []
    except (OSError, yaml.YAMLError):
        return []
    hooks_name = hooks_file.relative_to(root).as_posix()
    manifest_name = manifest.relative_to(root).as_posix()
    # A manifest below the checkout root names its folder, so two projects' checks differ.
    label = name if manifest.parent == root else f"{name} {manifest.parent.relative_to(root)}"
    locked, others = _pyproject_tools(manifest)
    pinned: set[str] = set()
    orphaned: set[str] = set()
    for hook_repo in hook_repos:
        if not isinstance(hook_repo, dict):
            continue
        hook_list = hook_repo.get("hooks")
        hooks = [h for h in hook_list if isinstance(h, dict)] if isinstance(hook_list, list) else []
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
    checks = []
    for tool in sorted(pinned):
        checks.append(
            _warn(
                f"{label} {tool} version",
                f"{tool} is pinned in {manifest_name}'s dependency group and by a hook "
                f"`rev` in {hooks_name}, so two versions can disagree",
                f"run {tool} from a `repo: local`, `language: system` hook "
                f"(`uv run --frozen {tool} ...`) and drop the hook's `rev`",
            )
        )
    for tool in sorted(orphaned):
        checks.append(
            _warn(
                f"{label} {tool} hook",
                f"a `language: system` hook in {hooks_name} runs `uv run {tool}`, "
                f"but {tool} is not in {manifest_name}'s dependency groups, so it fails",
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
        for line in claude_code.labelled_accounts_report(inst, run, settings_module.loaded_env_file)
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


def _spec_read_failure(
    backend: sandboxes.SandboxBackend, coverage: sandboxes.Coverage, inst: Installation
) -> str:
    """Why a confined step cannot read a file under the specs folder, naming it; empty when it
    can, or when there is no change to read."""
    live = (p for p in sorted(inst.changes_dir.glob("*")) if p.is_dir() and p.name != "archive")
    folder = next(live, None)
    if folder is None:
        return ""
    file = folder / "tasks.md"
    if not file.is_file():
        file = next((p for p in sorted(folder.rglob("*")) if p.is_file()), file)
    policy = sandboxes.SandboxPolicy(
        write=(),
        read=(
            *(Path(f).resolve() for f in system_folders()),
            *builtin_reads(inst, [folder.name]),
        ),
        hosts=(),
        required=coverage,
    )
    return _confined_failure(backend, policy, f"cat {shlex.quote(str(file))}", f"read {file}")


def _confined_failure(
    backend: sandboxes.SandboxBackend,
    policy: sandboxes.SandboxPolicy,
    script: str,
    what: str,
    *,
    started: Callable[[subprocess.CompletedProcess[str]], bool] = lambda done: False,
    run: Callable[
        [sandboxes.SandboxBackend, sandboxes.SandboxPolicy, str],
        subprocess.CompletedProcess[str],
    ] = held.run,
) -> str:
    """Why `script` does not succeed in a confined step under `policy` (`what` says what it
    does), naming what the step printed; empty when it succeeds. A non-zero exit counts as
    success when `started` says the command ran as far as it was meant to."""
    try:
        done = run(backend, policy, script)
    except subprocess.TimeoutExpired:
        return f"a confined step trying to {what} did not finish in {held.TIMEOUT} seconds"
    except OSError as error:
        return f"a confined step could not {what}: {error}"
    if done.returncode != 0 and not started(done):
        return f"a confined step cannot {what}: {done.stderr.strip() or done.returncode}"
    return ""


def _git_read_failure(backend: sandboxes.SandboxBackend, coverage: sandboxes.Coverage) -> str:
    """Why a confined step cannot run `git status` and `git log -1` in a worktree, naming what
    git could not read; empty when it can. Run in a scratch linked worktree, where `packed-refs`
    is replaced by write-and-rename, as `git pack-refs` does, while the step waits, and `git log
    -1` runs again."""
    with tempfile.TemporaryDirectory(prefix="abk-probe-git-") as folder:
        main, tree = (Path(folder).resolve() / name for name in ("main", "wt"))
        # Independent of the person's own configuration: no signing, no hooks.
        quiet = ("-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null")
        identity = ("-c", "user.name=abk", "-c", "user.email=abk@example.invalid")
        try:
            git(main.parent, "init", "-q", "-b", "main", str(main))
            git(main, *quiet, *identity, "commit", "-q", "--allow-empty", "-m", "probe")
            git(main, "worktree", "add", "-q", str(tree), "-b", "probe")
            git(main, "pack-refs", "--all")
        except (subprocess.CalledProcessError, OSError) as error:
            detail = getattr(error, "stderr", None) or error
            return f"could not make a scratch worktree for the git probe: {str(detail).strip()}"
        policy = sandboxes.SandboxPolicy(
            write=(tree, *git_parts(tree)),
            read=(*(Path(f).resolve() for f in system_folders()), *git_reads(tree)),
            hosts=(),
            required=coverage,
            no_execute=git_directory(tree),
        )
        ready, replaced = tree / "packed-refs.ready", tree / "packed-refs.replaced"
        script = (
            f"cd {shlex.quote(str(tree))} && git status && git log -1 && : > {ready.name} && "
            f"until [ -e {replaced.name} ]; do sleep 0.02; done && git log -1"
        )

        def replace() -> None:
            packed = main / ".git" / "packed-refs"
            lock = packed.with_name("packed-refs.lock")
            lock.write_text(packed.read_text())
            lock.replace(packed)
            replaced.touch()

        return _confined_failure(
            backend,
            policy,
            script,
            "run git",
            run=lambda b, p, s: held.run_replacing(b, p, s, ready=ready, replace=replace),
        )


def _abk_exec_failure(
    backend: sandboxes.SandboxBackend, coverage: sandboxes.Coverage, inst: Installation
) -> str:
    """Why a confined step cannot start `abk install-config`, naming what the step printed;
    empty when it can. The command runs from a scratch repository on a staged file that does not
    exist, so it gets past loading the installation and stops at "not a regular file"; that
    refusal is the command having started."""
    entry = shutil.which("abk")
    if entry is None:
        # Not a sandbox denial: nothing here to start (abk may be run through a launcher).
        return ""
    with tempfile.TemporaryDirectory(prefix="abk-probe-abk-") as folder:
        scratch = Path(folder).resolve()
        git(scratch, "init", "-q", check=False)
        policy = sandboxes.SandboxPolicy(
            write=(),
            read=(
                *(Path(f).resolve() for f in system_folders()),
                *builtin_reads(inst),
                *git_reads(scratch),
                scratch,
            ),
            hosts=(),
            required=coverage,
            no_execute=git_directory(scratch),
        )
        pointed = shlex.quote(str(inst.root / config.CONFIG_FILENAME))
        script = (
            f"cd {shlex.quote(str(scratch))} && {config.CONFIG_ENV}={pointed} "
            f"{shlex.quote(entry)} install-config {STAGING}/none.yaml .pre-commit-config.yaml"
        )
        return _confined_failure(
            backend,
            policy,
            script,
            "run `abk install-config`",
            started=lambda done: "install-config: refused:" in done.stderr,
        )


def sandbox_check(loaded: WorkspaceConfig, inst: Installation | None = None) -> Check:
    """Whether the sandbox backend works here, found by running its probe, and with `inst`
    whether a confined step reads a file under its specs folder; `abk init` shows the same
    result."""
    if not loaded.sandbox.enabled:
        return _info("sandbox", "off (`sandbox.enabled` is false)")
    backend, found = sandboxes.probe(loaded.sandbox.backend)
    if found.ok and inst is not None and (why := _spec_read_failure(backend, found.coverage, inst)):
        return _fail(
            "sandbox",
            f"{backend.name}: {why}",
            "the backend did not apply the read rule for the specs folder; "
            "try another `sandbox.backend` or update this one",
        )
    if found.ok and (why := _git_read_failure(backend, found.coverage)):
        return _fail(
            "sandbox",
            f"{backend.name}: {why}",
            "the backend did not apply the read rules git needs; "
            "try another `sandbox.backend` or update this one",
        )
    if found.ok and inst is not None and (why := _abk_exec_failure(backend, found.coverage, inst)):
        return _fail(
            "sandbox",
            f"{backend.name}: {why}",
            "the backend did not apply the read rule for the running installation; "
            "try another `sandbox.backend` or update this one",
        )
    repos = ", ".join(loaded.repos)
    if found.ok:
        return _ok(
            "sandbox",
            f"{backend.name}: confines {found.coverage.value} of a step in {repos}",
        )
    if sandboxes.no_backend(backend):
        return _info("sandbox", f"{found.cause}: steps in {repos} run unconfined", found.fix)
    return _fail("sandbox", f"{backend.name}: {found.cause}", found.fix)


def run_doctor(
    config_path: Path | None,
    *,
    cwd: Path | None = None,
    run: Run | None = None,
    which: Which | None = None,
    units: Path | None = None,
    transport: httpx.BaseTransport | None = None,
    mount_of: Callable[[Path], Mount] | None = None,
    fix: bool = False,
) -> list[Check]:
    run = run or subprocess.run
    which = which or shutil.which
    mount_of = mount_of or mounts.mount_of
    try:
        path = config.locate(config_path, cwd=cwd)
        loaded: WorkspaceConfig = load_config(path)
    except ConfigError as error:
        return [_fail("config", str(error), "run `abk init`, or fix abk.yaml")]
    checks = [_ok("config", str(path))]
    checks += [
        _warn("config", config.deprecation_notice(key), _deprecation_fix(key))
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
    checks += _unit_worktrees(inst)
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
    checks += _machine_files(inst)
    checks += _state_ignores(inst)
    checks += _state_locking(inst, mount_of)
    checks += _legacy_state(inst)
    checks += _planning_view(inst)
    checks += _state_location(inst)
    checks += _change_locks(inst, fix)
    checks += _timers(inst, run, units, which)
    checks += _toolchain(inst, run, which)
    checks += _agent_commands(inst)
    checks += _sandbox_lists(inst)
    checks += _runtime(inst, which, run)
    checks.append(sandbox_check(inst.config, inst))
    if config.runtime_name(inst.config) == config.CLAUDE_CODE:
        checks += _labelled_accounts(inst, run)
    checks += _notifications(inst, run, which)
    checks += _ssh_keys(inst)
    checks += _trackers(inst)
    checks += _verify_env(inst, run)
    checks += _public_content(inst)
    checks += _machine_keys(inst)
    checks += _local_dir(inst, mount_of)
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
    checks = run_doctor(args.config, fix=args.fix)
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
    parser.add_argument(
        "--fix", action="store_true", help="delete the stray lock files a change's directory holds"
    )
    parser.set_defaults(func=cmd_doctor, needs_installation=False)
