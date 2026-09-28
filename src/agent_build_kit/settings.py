"""Machine-level settings, from the environment and the planning repo's `.env`.

What lives here is what differs per machine or must not be committed: a
GitHub token, where the config file is, overrides for a model or the worktree
root, and the framework's own pins. What describes the workspace — repos,
owners, deploy rules, limits — is `abk.yaml` (config.py), which is committed
and reviewed.

`.env` is read from the planning root once an installation is loaded
(`reload`), not from wherever the process happens to start; the module-level
`settings` object is updated in place so every importer sees the same values.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ABK_", env_file=".env", extra="ignore")

    # The abk.yaml to use, when it is not the nearest one above the working
    # directory (config.locate).
    config: Path | None = None

    # One token for every `gh` call, overriding the per-owner lookup in
    # shell.gh_env. Left empty by default: relying on one account's access to
    # another's repo fails in the worst way if that grant is withdrawn, since
    # GitHub reports an inaccessible private repo as nonexistent.
    #
    # Read from `.env` rather than the ambient environment, because
    # pydantic-settings does not export to os.environ: a bare GH_TOKEN= line
    # there would never reach a subprocess otherwise.
    gh_token: str = Field("", validation_alias=AliasChoices("GH_TOKEN", "ABK_GH_TOKEN"))

    # Overrides abk.yaml's `planning.worktree_root` on this machine.
    worktree_root: Path | None = None

    # The OpenSpec CLI version run through npx (openspec.py). A pin, so an
    # upgrade is a deliberate change here rather than whatever npx fetched.
    openspec_version: str = "1.13.1"

    # Per-machine overrides of abk.yaml's `models`. None = use the file's.
    implement_model: str | None = None
    rework_model: str | None = None
    review_model: str | None = None
    rework_review_model: str | None = None


settings = Settings()


def reload(env_file: Path | None) -> Settings:
    """Re-read the settings with `env_file` (the planning root's .env) and
    update the shared object in place."""
    fresh = Settings(_env_file=env_file) if env_file else Settings(_env_file=None)
    for name, value in fresh.model_dump().items():
        setattr(settings, name, value)
    return settings
