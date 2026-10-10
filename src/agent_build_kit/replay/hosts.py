"""The hosts that are part of the stack, which a replay never stands in front of."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from urllib.parse import urlparse

from agent_build_kit import forges
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.model import Frozen
from agent_build_kit.settings import Settings

# The machine settings that name an endpoint of the stack.
_STACK_SETTINGS = (
    "gateway_url",
    "prometheus_url",
    "tempo_url",
    "grafana_url",
    "otel_exporter_otlp_endpoint",
    "otel_exporter_otlp_traces_endpoint",
    "otel_exporter_otlp_metrics_endpoint",
)


class InStackHosts(Frozen):
    named: dict[str, str] = {}

    def why(self, host: str) -> str | None:
        """The key that puts `host` in the set (such as `verify.env.NAME`), or None."""
        host = host.lower().strip("[]")
        if host in self.named:
            return self.named[host]
        if host in ("localhost", "host.docker.internal"):
            return f"built-in: {host}"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return "built-in: single-label name" if "." not in host else None
        return "built-in: loopback or private address" if address.is_private else None


def _host_of(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return parsed.hostname.lower()


def in_stack_hosts(
    workspace: WorkspaceConfig, verify_env: Mapping[str, str], machine: Settings
) -> InStackHosts:
    """The set built from `verify.env` URL values, each repository's code host, the
    machine settings naming stack endpoints, and the always-in-stack names."""
    named: dict[str, str] = {}

    def add(url: str, key: str) -> None:
        if (host := _host_of(url)) is not None:
            named.setdefault(host, key)

    for name, value in verify_env.items():
        add(value, f"verify.env.{name}")
    for name, repo in workspace.repos.items():
        if url := forges.get(repo.forge).api_url(machine):
            add(url, f"repos.{name}.forge")
    for setting in _STACK_SETTINGS:
        add(getattr(machine, setting), setting)
    return InStackHosts(named=named)
