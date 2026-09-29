"""One installation: a planning repo, its abk.yaml, and the repos it works on.

Everything the pipeline used to work out from where its own source file sat
— the state directory, the specs, the graph page, the worktree root, which
repos exist and where — comes from here instead, so the framework can be
installed anywhere and pointed at any planning repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from agent_build_kit import config as config_module
from agent_build_kit import forges
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


class Installation:
    def __init__(self, config: WorkspaceConfig, root: Path) -> None:
        self.config = config
        self.root = root.resolve()
        worktree_root = settings_module.settings.worktree_root or config.planning.worktree_root
        if worktree_root is None:
            worktree_root = Path.home() / ".local" / "share" / self.root.name / "worktrees"
        self.worktree_root = Path(worktree_root).expanduser().resolve()
        if self.worktree_root == self.root or self.worktree_root.is_relative_to(self.root):
            raise ConfigError(
                f"planning.worktree_root ({self.worktree_root}) must be outside the "
                f"planning repo ({self.root})"
            )

    # --- paths ----------------------------------------------------------------

    def _under_root(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        return candidate if candidate.is_absolute() else self.root / candidate

    @property
    def state_dir(self) -> Path:
        return self._under_root(self.config.planning.state_dir)

    @property
    def specs_dir(self) -> Path:
        return self._under_root(self.config.planning.specs_dir)

    @property
    def changes_dir(self) -> Path:
        return self.specs_dir / "changes"

    @property
    def graph_page(self) -> Path:
        return self._under_root(self.config.planning.graph_page)

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    def tasks_files(self) -> list[Path]:
        """Every active change's tasks.md, in name order."""
        return sorted(self.changes_dir.glob("*/tasks.md"))

    # --- repos ------------------------------------------------------------------

    @property
    def repos(self) -> dict[str, RepoConfig]:
        return self.config.repos

    @property
    def checkouts(self) -> dict[str, Path]:
        return {name: repo.path.expanduser() for name, repo in self.config.repos.items()}

    def repo(self, name: str) -> RepoConfig:
        try:
            return self.config.repos[name]
        except KeyError:
            raise KeyError(
                f"{name!r} is not a repo in abk.yaml (known: {', '.join(self.repos) or 'none'})"
            ) from None

    def slug(self, name: str) -> str:
        return self.repo(name).slug

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
        return self.config.limits.max_concurrent_stacks

    @property
    def stack_depth_cap(self) -> int:
        return self.config.limits.stack_depth_cap

    @property
    def max_plan_attempts(self) -> int:
        return self.config.limits.max_plan_attempts

    # --- verify env ---------------------------------------------------------------

    def verify_env(self) -> dict[str, str]:
        """The environment the live-stack tests get, each value resolved now."""
        return {name: _resolve(provider) for name, provider in self.config.verify.env.items()}

    # --- lifecycle ------------------------------------------------------------------

    def activate(self) -> None:
        """Make this the workspace the leaf modules see (config.active())."""
        settings_module.reload(self.env_file if self.env_file.exists() else None)
        config_module.activate(self.config, self.root)


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


def load_installation(config_path: Path | None = None, *, cwd: Path | None = None) -> Installation:
    """Locate, load and activate the installation for this process."""
    path = config_module.locate(config_path or settings_module.settings.config, cwd=cwd)
    installation = Installation(config_module.load(path), path.parent)
    installation.activate()
    return installation
