"""One installation: a planning repo, its abk.yaml, and the repos it works on.

Everything the pipeline used to work out from where its own source file sat
— the state directory, the specs, the graph page, the worktree root, which
repos exist and where — comes from here instead, so the framework can be
installed anywhere and pointed at any planning repo.
"""

from __future__ import annotations

import subprocess
from functools import cached_property
from pathlib import Path

import yaml

from agent_build_kit import config as config_module
from agent_build_kit import forges, redaction
from agent_build_kit import settings as settings_module
from agent_build_kit.config import (
    CommandProvider,
    ConfigError,
    EnvFileProvider,
    LiteralProvider,
    RepoConfig,
    WorkspaceConfig,
    YamlProvider,
)
from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.model import E2E_LOCK_FILE
from agent_build_kit.pipeline.lease import lease_dir
from agent_build_kit.pipeline.planning_repo import (
    common_dir,
    is_worktree_of,
    main_working_tree,
    repo_sharing,
    repository_name,
)
from agent_build_kit.pipeline.planning_sync import is_pipeline_worktree


def changes_dir_under(root: Path, specs_dir: str) -> Path:
    """Where the changes of a store live, for a caller that holds a root and the
    name of a specs directory but no installation."""
    return root / Path(specs_dir).expanduser() / "changes"


def data_home() -> Path:
    """Where an installation keeps what lives outside its planning root: the unit worktrees and
    the pipeline worktree."""
    return Path.home() / ".local" / "share"


def env_file_for(root: Path) -> Path:
    """The `.env` a planning root reads: its own, or the main working tree's when the root is the
    pipeline worktree (a fresh checkout, which never has one) and has none."""
    own = root / ".env"
    if not own.exists() and is_pipeline_worktree(root):
        main = main_working_tree(root)
        if main is not None:
            return main / ".env"
    return own


class Installation:
    def __init__(self, config: WorkspaceConfig, root: Path) -> None:
        self.config = config
        self.root = root.resolve()
        self.in_pipeline_worktree = is_pipeline_worktree(self.root)
        self._common = common_dir(self.root) if self.in_pipeline_worktree else None
        # Every pipeline worktree is called the same, so it is named for its repository.
        name = repository_name(self.root).name if self.in_pipeline_worktree else self.root.name
        configured_home = settings_module.settings.planning_home or config.planning.home
        if configured_home is not None:
            self._configured_home: Path | None = Path(configured_home).expanduser()
            if self._inside_root(self._configured_home):
                raise ConfigError(
                    f"planning.home ({self._configured_home}) must be outside the "
                    f"planning repo ({self.root})"
                )
        else:
            self._configured_home = None
        worktree_root = settings_module.settings.worktree_root or config.planning.worktree_root
        if worktree_root is None:
            worktree_root = data_home() / name / "worktrees"
        self.worktree_root = Path(worktree_root).expanduser().resolve()
        if self._inside_root(self.worktree_root):
            raise ConfigError(
                f"planning.worktree_root ({self.worktree_root}) must be outside the "
                f"planning repo ({self.root})"
            )
        configured_local = settings_module.settings.local_dir or config.planning.local_dir
        if configured_local is not None and not Path(configured_local).expanduser().is_absolute():
            raise ConfigError(
                f"planning.local_dir ({configured_local}) must be an absolute path or start with ~"
            )
        configured_reports = config.planning.reports_dir
        if configured_reports is not None and not self._inside_root(
            self._under_root(configured_reports)
        ):
            raise ConfigError(
                f"planning.reports_dir {configured_reports} is outside the planning repository "
                f"{self.root}; the reports are committed there"
            )

    # --- paths ----------------------------------------------------------------

    def _inside_root(self, path: Path) -> bool:
        resolved = path.resolve()
        return resolved == self.root or resolved.is_relative_to(self.root)

    def _under_root(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        return candidate if candidate.is_absolute() else self.root / candidate

    @cached_property
    def in_repo(self) -> bool:
        """Whether the planning root's repository holds a listed repo."""
        return repo_sharing(self.checkouts, self.root) is not None

    @property
    def planning_home(self) -> Path:
        """Where an in-repo installation keeps its state and its pipeline worktree."""
        # The repository's name, so the working copy and the pipeline worktree agree.
        return self._configured_home or data_home() / repository_name(self.root).name / "planning"

    @property
    def worktree_path(self) -> Path:
        return self.planning_home / "worktree"

    @property
    def state_dir(self) -> Path:
        configured = settings_module.settings.state_dir or self.config.planning.state_dir
        if configured is not None:
            return self._under_root(str(configured))
        return self.planning_home / "state" if self.in_repo else self.root / "runs"

    @property
    def local_dir(self) -> Path:
        """Where the files tied to this machine's processes live: `planning.local_dir`, else
        `<planning home>/local` in an in-repo installation, else the state directory."""
        configured = settings_module.settings.local_dir or self.config.planning.local_dir
        if configured is not None:
            return Path(configured).expanduser()
        return self.planning_home / "local" if self.in_repo else self.state_dir

    @property
    def locks_dir(self) -> Path:
        return self.local_dir / "locks"

    @property
    def leases_dir(self) -> Path:
        return lease_dir(self.local_dir)

    @property
    def environment_lock(self) -> Path:
        return self.local_dir / "environment.lock"

    @property
    def reports_dir(self) -> Path:
        """Where the tracks keep their run logs and tracker: always literally under the root."""
        configured = self.config.planning.reports_dir
        path = self._under_root(configured) if configured is not None else self.state_dir
        if configured is None and not self._inside_root(path):
            return self.root / "docs" / "reports"
        # Through a link to the root the path is resolved, so it reads as under `self.root`.
        return self.root / path.resolve().relative_to(self.root)

    def _page(self, configured: str | None, name: str) -> Path:
        if configured is not None:
            return self._under_root(configured)
        state = self.state_dir
        if self._inside_root(state):
            return self.root / "docs" / name
        return state / "pages" / name

    @property
    def specs_dir(self) -> Path:
        return self._under_root(self.config.planning.specs_dir)

    @property
    def changes_dir(self) -> Path:
        return changes_dir_under(self.root, self.config.planning.specs_dir)

    @property
    def e2e_lock(self) -> Path:
        return self.local_dir / E2E_LOCK_FILE

    @property
    def graph_page(self) -> Path:
        return self._page(self.config.planning.graph_page, "unit_graph.md")

    @property
    def usage_page(self) -> Path:
        return self._page(self.config.planning.usage_page, "unit_cost.md")

    @property
    def planning_paths(self) -> tuple[str, ...]:
        """The specs directory, the state directory, the graph page, the usage page and the
        configuration file, relative to the root (a path outside it stays absolute)."""
        paths = (self.specs_dir, self.state_dir, self.graph_page, self.usage_page)
        return (*(self.shown(p) for p in paths), config_module.CONFIG_FILENAME)

    def shown(self, path: Path) -> str:
        """A path as planning paths are named: relative to the root (POSIX form) when it is under
        it, else as given."""
        return (
            path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else str(path)
        )

    @property
    def env_file(self) -> Path:
        return env_file_for(self.root)

    def tasks_files(self) -> list[Path]:
        """Every active change's tasks.md, in name order."""
        return sorted(self.changes_dir.glob("*/tasks.md"))

    # --- repos ------------------------------------------------------------------

    @property
    def repos(self) -> dict[str, RepoConfig]:
        return self.config.repos

    def checkout_of(self, configured: Path) -> Path:
        """A repo's configured path as a checkout: a relative path is under the root, and a path
        that is a worktree of the root's own repository is the root when the root is the pipeline
        worktree."""
        path = self._under_root(str(configured))
        if self._common is not None and is_worktree_of(path, self._common):
            return self.root
        return path

    @cached_property
    def checkouts(self) -> dict[str, Path]:
        return {name: self.checkout_of(repo.path) for name, repo in self.config.repos.items()}

    def repo(self, name: str) -> RepoConfig:
        try:
            return self.config.repos[name]
        except KeyError:
            raise KeyError(
                f"{name!r} is not a repo in abk.yaml (known: {', '.join(self.repos) or 'none'})"
            ) from None

    def forge_of(self, name: str) -> tuple[Forge, RepoId]:
        """The code host a repo is on, and its identity there.

        Replaces `owners()`, which answered "every account this workspace
        touches" - a question only the doctor asked, and one that assumed a
        two-segment slug. Asking per repo is both narrower and host-agnostic.
        """
        repo = self.repo(name)
        forge = forges.get(repo.forge)
        return forge, forge.identity(repo)

    def deploy_order(self, names: list[str]) -> list[str]:
        """`names` with every repo after the ones it consumes."""
        ordered: list[str] = []

        def visit(name: str) -> None:
            if name in ordered:
                return
            for consumed in self.repos[name].consumes if name in self.repos else ():
                if consumed in names:
                    visit(consumed)
            ordered.append(name)

        for name in names:
            visit(name)
        return ordered

    def dev_stack_base(self, name: str) -> str | None:
        """The repo this one's dev stack comes up on top of: the first repo
        it consumes that has a dev stack of its own."""
        for consumed in self.repo(name).consumes:
            if consumed in self.repos and self.repos[consumed].dev_stack is not None:
                return consumed
        return None

    # --- limits -----------------------------------------------------------------

    @property
    def max_concurrent_stacks(self) -> int:
        """Build workers of one project (`project_limits`), not of the workspace."""
        return self.config.project_limits.max_concurrent_stacks

    @property
    def max_concurrent_restacks(self) -> int:
        """Restack workers in the lane of one project (`project_limits`)."""
        return self.config.project_limits.max_concurrent_restacks

    @property
    def max_units_in_progress(self) -> int:
        """Units started and not finished in one project (`project_limits`)."""
        return self.config.project_limits.max_units_in_progress

    @property
    def emergency_extra(self) -> int:
        """Priority-0 units that may start past the normal limits at once in one project
        (`project_limits`); 0 is off."""
        return self.config.project_limits.emergency_extra

    @property
    def stack_depth_build_cap(self) -> int:
        return self.config.global_limits.stack_depth_build_cap

    @property
    def stack_depth_rebase_cap(self) -> int:
        rebase = self.config.global_limits.stack_depth_rebase_cap
        return self.stack_depth_build_cap if rebase is None else rebase

    @property
    def max_plan_attempts(self) -> int:
        return self.config.global_limits.max_plan_attempts

    # --- verify env ---------------------------------------------------------------

    def verify_env(self) -> dict[str, str]:
        """The environment the live-stack tests get, each value resolved now."""
        return {name: _resolve(provider) for name, provider in self.config.verify.env.items()}

    # --- lifecycle ------------------------------------------------------------------

    def activate(self) -> None:
        """Make this the workspace the leaf modules see (config.active())."""
        settings_module.reload(settings_module.readable(self.env_file))
        config_module.activate(
            self.config, self.root, self.checkout_of, lambda: self.state_dir, lambda: self.local_dir
        )
        redaction.activate(redaction.gather(self))


def _resolve(provider: object) -> str:
    if isinstance(provider, LiteralProvider):
        return provider.value
    if isinstance(provider, EnvFileProvider):
        for line in provider.file.expanduser().read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == provider.key:
                return value.strip().strip('"').strip("'")
        raise ConfigError(f"{provider.file} has no {provider.key}=")
    if isinstance(provider, CommandProvider):
        result = subprocess.run(provider.argv, capture_output=True, text=True, check=False)
        if result.returncode:
            raise ConfigError(f"{' '.join(provider.argv)} failed: {result.stderr.strip()}")
        return result.stdout.strip()
    if isinstance(provider, YamlProvider):
        value: object = yaml.safe_load(provider.file.expanduser().read_text())
        for key in provider.path.split("."):
            if not isinstance(value, dict) or key not in value:
                raise ConfigError(f"{provider.file} has no {provider.path}")
            value = value[key]
        text = str(value)
        if provider.strip_prefix and text.startswith(provider.strip_prefix):
            text = text[len(provider.strip_prefix) :]
        if provider.take == "last-word":
            text = text.split()[-1] if text.split() else ""
        return text
    raise ConfigError(f"unknown provider {provider!r}")


def load_config(path: Path) -> WorkspaceConfig:
    """The abk.yaml at `path`, loaded once its planning root's `.env` has been
    read: a runtime selected there (`ABK_RUNTIME`) is the one `config.load`
    checks, not whatever the process started with."""
    settings_module.reload(settings_module.readable(env_file_for(path.parent.resolve())))
    return config_module.load(path)


def load_installation(config_path: Path | None = None, *, cwd: Path | None = None) -> Installation:
    """Locate, load and activate the installation for this process."""
    path = config_module.locate(config_path or settings_module.settings.config, cwd=cwd)
    installation = Installation(load_config(path), path.parent)
    installation.activate()
    return installation
