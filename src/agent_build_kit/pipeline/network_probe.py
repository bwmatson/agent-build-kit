"""A bounded look at whether the model's host and a control group can be reached.

Evidence for an agent run that ended on a failure to connect, never a model call: a DNS
lookup then a TCP connect, sending nothing, so it spends nothing and needs no key. The
host the run called is the one asked about; the control group (the code hosts and
`limits.network_control_hosts`) says whether the network as a whole is up. A probe that
cannot answer counts as the host being reachable, so a bug in it never parks a unit.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.settings import settings

Resolve = Callable[[str], object]
Connect = Callable[[str, int, float], object]

PORT = 443


class Reachability(Frozen):
    """Whether the host a run called connected, and whether any control host did."""

    api: bool
    control: bool


def resolve_name(host: str) -> object:
    """Both address families, so a host with only IPv6 records still resolves."""
    return socket.getaddrinfo(host, None)


def connect_tcp(host: str, port: int, timeout: float) -> object:
    with socket.create_connection((host, port), timeout=timeout) as connection:
        return connection.getpeername()


def control_group(installation: Installation) -> tuple[str, ...]:
    """The forge hosts of the installation's repos, then `limits.network_control_hosts`."""
    hosts: dict[str, None] = {}
    for name in installation.repos:
        forge, _ = installation.forge_of(name)
        if (url := forge.api_url(settings)) and (host := urlparse(url).hostname):
            hosts[host] = None
    for host in installation.config.limits.network_control_hosts:
        hosts[host] = None
    return tuple(hosts)


def probe_reachability(
    api_host: str,
    control_hosts: Sequence[str],
    *,
    timeout: float,
    api_port: int = PORT,
    resolve: Resolve = resolve_name,
    connect: Connect = connect_tcp,
) -> Reachability:
    """A lookup then a TCP connect for the API host, on the port the run called, and for each
    control host, on 443."""

    def reached(host: str, port: int) -> bool:
        try:
            resolve(host)
            connect(host, port, timeout)
        except OSError:
            return False
        return True

    if not control_hosts:
        return Reachability(api=True, control=False)
    try:
        api = reached(api_host, api_port)
        control = any(reached(host, PORT) for host in control_hosts)
    except Exception:  # noqa: BLE001 — a probe that breaks must not park a unit.
        return Reachability(api=True, control=False)
    return Reachability(api=api, control=control)


def classify_reachability(
    api_host: str,
    control_hosts: Sequence[str],
    *,
    timeout: float,
    api_port: int = PORT,
    probe: Callable[..., Reachability] | None = None,
) -> Cause | None:
    """The cause an outage parks a unit with, or None for an ordinary failure: the API host
    connecting, no host to ask about, or a probe that errored."""
    if not api_host:
        return None
    try:
        reached = (probe or probe_reachability)(
            api_host, control_hosts, timeout=timeout, api_port=api_port
        )
    except Exception:  # noqa: BLE001
        return None
    if reached.api:
        return None
    return Cause.SERVICE_UNAVAILABLE if reached.control else Cause.NETWORK_UNAVAILABLE
