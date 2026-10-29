"""The policy a confined step runs under, assembled from every place that grants."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import agent_build_kit
from agent_build_kit import config as config_module
from agent_build_kit import profiles
from agent_build_kit.config import (
    E2eSandboxConfig,
    ProjectConfig,
    ProjectSandboxConfig,
    RepoSandboxConfig,
)
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen, TestTier
from agent_build_kit.profiles.base import SandboxPaths
from agent_build_kit.sandboxes.base import (
    SandboxPathsProfile,
    SandboxPathsRuntime,
    SandboxPolicy,
    system_folders,
)
from agent_build_kit.sandboxes.proxy import LOCALHOST
from agent_build_kit.settings import Settings

# The parts of a repository's git directory a commit writes. Landlock rules only add access,
# so they are granted one at a time and never `hooks` or `config`.
GIT_PARTS = ("objects", "refs", "logs", "packed-refs", "HEAD", "FETCH_HEAD")


BUILT_IN = "built-in"

# The person's own git configuration file, beside their home; held apart from the home shorthand.
PERSONAL_GIT_CONFIG = ".gitconfig"
# What git opens in its folder under the configuration home, and nothing else of it.
PERSONAL_GIT_FILES = ("config", "ignore", "attributes")


def change_reads(installation: Installation, changes: Iterable[str]) -> list[Path]:
    """What a step of `changes` reads of the planning repo, and no more: each change's folder and
    the capability specs beside them, resolved as every read entry is."""
    folders = [installation.changes_dir / change for change in changes]
    return [path.resolve() for path in (*folders, installation.specs_dir / "specs")]


def own_installation() -> list[Path]:
    """What a step reads and executes of the installation that started it: the interpreter's
    prefix and base prefix, the folders of the interpreter and of the `abk` entry point and, for
    a checkout install, the package's source root; only those that exist."""
    prefix = Path(sys.prefix).resolve()
    found = [prefix, Path(sys.base_prefix), Path(sys.executable).resolve().parent]
    if entry := shutil.which("abk"):
        found.append(Path(entry).parent)
    package = Path(agent_build_kit.__file__).resolve().parent
    if not package.is_relative_to(prefix):
        found.append(package.parent)
    return list(_unique(path.resolve() for path in found if path.exists()))


def loaded_files(installation: Installation) -> list[Path]:
    """The files `abk` reads to load `installation` (its `abk.yaml` and the overlay), only those
    that exist. They are granted one by one, never the planning root's folder. The `.env` is never
    among them: it holds the credentials a confined step's environment is stripped of, and an
    installation loads without it."""
    names = (
        installation.root / config_module.CONFIG_FILENAME,
        installation.root / config_module.OVERLAY_FILENAME,
    )
    return [path.resolve() for path in names if path.is_file()]


def builtin_reads(installation: Installation, changes: Iterable[str] = ()) -> list[Path]:
    """What every confined step reads whatever its repo: the running installation, the files
    that load `installation` and, for a step of `changes`, those changes and the capability
    specs. The doctor's probes take their read list from here too."""
    reads = [*own_installation(), *loaded_files(installation)]
    if changes := tuple(changes):
        reads += change_reads(installation, changes)
    return reads


class PolicyRefused(ValueError):
    """A grant that would let a step write what a person owns; the message says which and why."""


def build_policy(
    installation: Installation,
    repo: str,
    worktree: Path,
    *,
    runtime: object,
    profile: object,
    account: object = None,
    tier: TestTier = TestTier.UNIT_TEST,
    changes: tuple[str, ...] = (),
) -> SandboxPolicy:
    """The policy for a step in `worktree` of `repo`: built-ins, then the runtime's and the
    profile's optional `sandbox_paths`, then `repos.<name>.sandbox` and each project's from
    abk.yaml, then the same keys from abk.local.yaml. The two files are read apart: the loaded
    configuration holds the overlay laid over the committed file, which replaces a list whole.
    An e2e-test step also takes `repos.<name>.tests.e2e_sandbox` from both files; any other tier
    never gets a service port."""
    entries = policy_entries(
        installation,
        repo,
        worktree,
        runtime=runtime,
        profile=profile,
        account=account,
        tier=tier,
        changes=changes,
    )

    def listed(key: str) -> list[str]:
        return [e.value for e in entries if e.kind == key]

    write = _resolved(listed("write"), worktree)
    _refuse_owned(listed("write"), write, installation)
    return SandboxPolicy(
        write=_unique([worktree.resolve(), *git_parts(worktree), *write]),
        read=_unique(_resolved([*system_folders(), *listed("read")], worktree)),
        hosts=_unique(listed("hosts")),
        ports=_unique(int(port) for port in listed("ports")),
        required=installation.config.repos[repo].sandbox.required,
        no_execute=git_directory(worktree),
    )


class PolicyEntry(Frozen):
    """One line of a policy: the list it is in (`read`, `write`, `hosts` or `ports`), the entry as
    listed and where it came from (`runtime`, a profile name, `abk.yaml` or `abk.local.yaml`)."""

    kind: str
    value: str
    source: str


def policy_entries(
    installation: Installation,
    repo: str,
    worktree: Path,
    *,
    runtime: object,
    profile: object,
    account: object = None,
    tier: TestTier = TestTier.UNIT_TEST,
    changes: tuple[str, ...] = (),
) -> list[PolicyEntry]:
    """The entries `build_policy` assembles, each with its source, in the order it takes them:
    the runtime's, the repo's profile's and each project's profile's, then the files'. For an
    e2e-test step each file's `tests.e2e_sandbox` follows its sandbox blocks. A step of a
    unit's `changes` also reads them and the capability specs, as a built-in entry."""
    layers: list[tuple[str, ProjectSandboxConfig | E2eSandboxConfig]] = []
    if git := git_reads(worktree):
        layers.append((BUILT_IN, ProjectSandboxConfig(read=[str(path) for path in git])))
    reads = [str(path) for path in builtin_reads(installation, changes)]
    layers.append((BUILT_IN, ProjectSandboxConfig(read=reads)))
    if isinstance(runtime, SandboxPathsRuntime):
        # An account is passed only when the step runs as one; a runtime without accounts
        # takes none.
        given = runtime.sandbox_paths() if account is None else runtime.sandbox_paths(account)
        layers.append(("runtime", ProjectSandboxConfig.model_validate(given)))
    seen: set[str] = set()
    toolchains = [profile] + [
        profiles.get(project.profile) for project in installation.config.repos[repo].projects
    ]
    for toolchain in toolchains:
        name = getattr(toolchain, "name", type(toolchain).__name__)
        if name in seen or not isinstance(toolchain, SandboxPathsProfile):
            continue
        seen.add(name)
        layers.append((name, _layer(toolchain.sandbox_paths(worktree))))
    path = installation.root / config_module.CONFIG_FILENAME
    for source, document in (
        (config_module.CONFIG_FILENAME, config_module.read_base(path)),
        (config_module.OVERLAY_FILENAME, config_module.read_overlay(path)),
    ):
        layers.extend((source, block) for block in _blocks(document or {}, repo))
        if tier is TestTier.E2E_TEST:
            layers.append((source, _e2e_block(document or {}, repo)))
    found = [
        PolicyEntry(kind=kind, value=str(value), source=source)
        for kind in ("write", "read", "hosts", "ports")
        for source, layer in layers
        for value in getattr(layer, kind, [])
    ]
    projects = installation.config.repos[repo].projects
    scopes = [(project, profiles.get(project.profile)) for project in projects] or [(None, profile)]
    for project, toolchain in scopes:
        found += caches_for(installation, repo, project, toolchain, worktree)
    return found


def caches_for(
    installation: Installation,
    repo: str,
    project: ProjectConfig | None,
    toolchain: object,
    worktree: Path,
) -> list[PolicyEntry]:
    """The cache folders a step of `project` (None: the repo as a whole) may write, as `write`
    entries with their source: the project's `caches` when set, else the repo's, else the
    toolchain's defaults. At each level the overlay's list replaces the committed file's."""
    path = installation.root / config_module.CONFIG_FILENAME
    documents = (
        (config_module.CONFIG_FILENAME, config_module.read_base(path) or {}),
        (config_module.OVERLAY_FILENAME, config_module.read_overlay(path) or {}),
    )
    levels: list[tuple[str, list[str]] | None] = []
    for scope in (project, None) if project else (None,):
        chosen: tuple[str, list[str]] | None = None
        for source, document in documents:
            entry = (document.get("repos") or {}).get(repo) or {}
            if scope is None:
                block = entry.get("sandbox") or {}
            else:
                same = [p for p in entry.get("projects") or [] if p.get("path") == scope.path]
                block = (same[0].get("sandbox") or {}) if same else {}
            if block.get("caches") is not None:
                chosen = (source, list(block["caches"]))
        levels.append(chosen)
    if given := next((level for level in levels if level is not None), None):
        source, folders = given
        return [PolicyEntry(kind="write", value=folder, source=source) for folder in folders]
    name = getattr(toolchain, "name", type(toolchain).__name__)
    paths = (
        toolchain.sandbox_paths(worktree) if isinstance(toolchain, SandboxPathsProfile) else None
    )
    defaults = paths.caches if isinstance(paths, SandboxPaths) else ()
    return [PolicyEntry(kind="write", value=f, source=f"default ({name})") for f in defaults]


def _layer(given: SandboxPaths | dict[str, list[str]]) -> ProjectSandboxConfig:
    """A profile's answer as a block: the model, or the dict an older profile returns."""
    if isinstance(given, SandboxPaths):
        return ProjectSandboxConfig(
            read=list(given.read), write=list(given.write), hosts=list(given.hosts)
        )
    return ProjectSandboxConfig.model_validate(given)


def proxy_environment(port: int) -> dict[str, str]:
    """The environment that points a step's HTTP clients at the proxy on `port`, and empties
    `NO_PROXY` so no host is reached around it."""
    url = f"http://{LOCALHOST}:{port}"
    pointed = {name: url for key in ("HTTPS_PROXY", "HTTP_PROXY") for name in (key, key.lower())}
    return pointed | {"NO_PROXY": "", "no_proxy": ""}


def _blocks(document: dict[str, Any], repo: str) -> list[ProjectSandboxConfig]:
    """The repo's sandbox block in one file and then each of its projects', validated."""
    entry = (document.get("repos") or {}).get(repo) or {}
    blocks: list[ProjectSandboxConfig] = [
        RepoSandboxConfig.model_validate(entry.get("sandbox") or {})
    ]
    for project in entry.get("projects") or []:
        blocks.append(ProjectSandboxConfig.model_validate(project.get("sandbox") or {}))
    return blocks


def _e2e_block(document: dict[str, Any], repo: str) -> E2eSandboxConfig:
    """The repo's `tests.e2e_sandbox` in one file, validated."""
    entry = (document.get("repos") or {}).get(repo) or {}
    return E2eSandboxConfig.model_validate((entry.get("tests") or {}).get("e2e_sandbox") or {})


def git_parts(worktree: Path) -> list[Path]:
    """The git paths a commit in `worktree` writes, derived from its `.git` pointer when it is
    a linked worktree; only those that exist."""
    found = _git_dirs(worktree)
    if found is None:
        return []
    common, own = found
    paths = [common / part for part in GIT_PARTS] + ([own] if own else [])
    return [path.resolve() for path in paths if path.exists()]


def git_reads(worktree: Path) -> list[Path]:
    """The paths `git` opens to run in `worktree`, read and never written: the repository's
    common git directory as a directory (so a file git replaces by rename stays covered), a
    linked worktree's own entry and `.git` file, and the person's git configuration files; only
    those that exist."""
    found = _git_dirs(worktree)
    if found is None:
        return []
    common, own = found
    # Only the files git opens there: the folder also holds the credential store.
    personal = Settings().config_folder() / "git"
    paths = [
        common,
        *([own, worktree / ".git"] if own else []),
        Path.home() / PERSONAL_GIT_CONFIG,
        *(personal / name for name in PERSONAL_GIT_FILES),
    ]
    return [path.resolve() for path in paths if path.exists()]


def git_directory(worktree: Path) -> tuple[Path, ...]:
    """The common git directory of `worktree`: the policy's `no_execute` list, since a step reads
    it and never runs anything in it. Every caller that builds a policy for a step that runs
    `git` takes it from here. Empty when `worktree` is no git checkout, and when the directory
    lies inside `worktree` (the main checkout): the worktree is writable, which includes running
    what is in it, so there the directory is not held back."""
    found = _git_dirs(worktree)
    if found is None or found[0].resolve().is_relative_to(worktree.resolve()):
        return ()
    return (found[0].resolve(),)


def _git_dirs(worktree: Path) -> tuple[Path, Path | None] | None:
    """The common git directory of `worktree` and, for a linked one, its own entry under it;
    None when it is no git checkout."""
    dot_git = worktree / ".git"
    if dot_git.is_dir():
        return dot_git, None
    if not dot_git.is_file():
        return None
    own = _pointed_at(dot_git, worktree)
    pointer = own / "commondir"
    return ((own / pointer.read_text().strip()) if pointer.exists() else own.parent.parent), own


def _pointed_at(dot_git: Path, worktree: Path) -> Path:
    text = dot_git.read_text().strip()
    target = text.removeprefix("gitdir:").strip()
    return (worktree / target).resolve()


def _resolved(items: Iterable[str], worktree: Path) -> list[Path]:
    """Each path as one absolute path: `~` expanded, a relative one taken from the worktree,
    `..` and symlinks followed."""
    return [(worktree / Path(item).expanduser()).resolve() for item in items]


def _unique[T](items: Iterable[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(items))


def _refuse_owned(given: list[str], resolved: list[Path], installation: Installation) -> None:
    """Refuse a write grant of what a person owns: the file itself, a parent that would
    include it, and anything inside the specs folder."""
    specs = installation.specs_dir.resolve()
    owned = [
        installation.root / config_module.CONFIG_FILENAME,
        installation.root / config_module.OVERLAY_FILENAME,
        specs,
    ]
    for item, path in zip(given, resolved, strict=True):
        reached = [p for p in owned if p.resolve().is_relative_to(path)]
        if path.is_relative_to(specs):
            reached.append(specs)
        if reached:
            raise PolicyRefused(
                f"{item}: refused, it would let a step write {reached[0]}, which a person "
                "owns in the planning repo"
            )
