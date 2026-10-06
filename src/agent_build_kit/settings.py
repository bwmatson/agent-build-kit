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

    # The personal access token Azure DevOps calls are made with. The
    # extension's own variable comes first, so a machine already set up for
    # `az repos` needs nothing new here; unset, calls fall back to the `az`
    # sign-in session, which is the other supported way to be authenticated.
    ado_pat: str = Field("", validation_alias=AliasChoices("AZURE_DEVOPS_EXT_PAT", "ABK_ADO_PAT"))

    # Overrides abk.yaml's `planning.worktree_root` on this machine.
    worktree_root: Path | None = None

    # Where the user manager reads units from (timers.py). systemd honours
    # XDG_CONFIG_HOME, so installing the units has to read it the same way, or
    # they land where nothing looks for them. `~/.config` when unset.
    config_home: Path | None = Field(
        None, validation_alias=AliasChoices("XDG_CONFIG_HOME", "ABK_CONFIG_HOME")
    )

    # The OpenSpec CLI version run through npx (openspec.py). A pin, so an
    # upgrade is a deliberate change here rather than whatever npx fetched.
    openspec_version: str = "1.13.1"

    # Overrides abk.yaml's `runtime` on this machine (ABK_RUNTIME). None = the file's.
    runtime: str | None = None

    # Per-machine overrides of abk.yaml's `models`. None = use the file's.
    implement_model: str | None = None
    rework_model: str | None = None
    review_model: str | None = None
    rework_review_model: str | None = None

    # The gateway in front of the model, and the master key that may mint keys
    # on it (pipeline/gateway_usage.py). Neither set: no key is minted.
    gateway_url: str = ""
    gateway_master_key: str = ""
    # How long after a call ends its spend rows are waited for: a gateway writes
    # its logs in periodic batches, so they land after the request does.
    gateway_settle_seconds: float = 30.0

    # Telemetry (telemetry.py): off unless this is set. The endpoint and
    # resource settings keep their standard OpenTelemetry names, so any
    # collector setup works unchanged; the per-signal endpoints override the
    # shared one.
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = Field(
        "", validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_ENDPOINT")
    )
    otel_exporter_otlp_traces_endpoint: str = Field(
        "", validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )
    otel_exporter_otlp_metrics_endpoint: str = Field(
        "", validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    )
    otel_service_name: str = Field(
        "agent-build-kit", validation_alias=AliasChoices("OTEL_SERVICE_NAME")
    )
    otel_resource_attributes: str = Field(
        "", validation_alias=AliasChoices("OTEL_RESOURCE_ATTRIBUTES")
    )

    # The Grafana `abk telemetry push-dashboard` pushes the pipeline's dashboard
    # to: its URL, a service-account token, and the folder it goes into.
    grafana_url: str = ""
    grafana_token: str = ""
    grafana_folder: str = "agent-build-kit"


settings = Settings()


def reload(env_file: Path | None) -> Settings:
    """Re-read the settings with `env_file` (the planning root's .env) and
    update the shared object in place."""
    fresh = Settings(_env_file=env_file) if env_file else Settings(_env_file=None)
    for name, value in fresh.model_dump().items():
        setattr(settings, name, value)
    return settings
