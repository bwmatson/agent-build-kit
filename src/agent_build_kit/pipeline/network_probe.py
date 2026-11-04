"""A bounded look at whether the model's host and a control group can be reached.

Evidence for an agent run that ended on a failure to connect, never a model call: a DNS
lookup then a TCP connect, sending nothing, so it spends nothing and needs no key. The
host the run called is the one asked about; the control group (the code hosts and
`global_limits.network_control_hosts`) says whether the network as a whole is up. A probe that
cannot answer counts as the host being reachable, so a bug in it never parks a unit.
"""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.parse import urlparse

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import restack, shell
from agent_build_kit.pipeline.git_output import transport_failure, untranslated_env
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.settings import settings

Resolve = Callable[[str], object]
Connect = Callable[[str, int, float], object]

PORT = 443

Run = Callable[..., subprocess.CompletedProcess[str]]

# A read over ssh or https costs a handshake and a round trip beyond a bare connect, so the probe
# waits this many times `global_limits.network_probe_timeout_seconds`.
CODE_HOST_TIMEOUT_FACTOR = 6


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
    """The forge hosts of the installation's repos, then `global_limits.network_control_hosts`."""
    hosts: dict[str, None] = {}
    for name in installation.repos:
        forge, _ = installation.forge_of(name)
        if (url := forge.api_url(settings)) and (host := urlparse(url).hostname):
            hosts[host] = None
    for host in installation.config.global_limits.network_control_hosts:
        hosts[host] = None
    return tuple(hosts)


def host_connects(
    host: str, port: int, *, timeout: float, resolve: Resolve, connect: Connect
) -> bool:
    """A lookup then a TCP connect; False only for the failures a down network produces."""
    try:
        resolve(host)
        connect(host, port, timeout)
    except OSError:
        return False
    return True


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
        return host_connects(host, port, timeout=timeout, resolve=resolve, connect=connect)

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


def control_reachable(
    installation: Installation,
    *,
    resolve: Resolve | None = None,
    connect: Connect | None = None,
) -> bool:
    """Whether any host of the control group connects: the network as a whole is up.

    True when there is no group to ask and when the probing raises anything but a failure
    to connect, so a pause that only this ends is never held by a probe that cannot answer.
    """
    hosts = control_group(installation)
    if not hosts:
        return True
    timeout = installation.config.global_limits.network_probe_timeout_seconds
    try:
        return any(
            host_connects(
                host,
                PORT,
                timeout=timeout,
                resolve=resolve or resolve_name,
                connect=connect or connect_tcp,
            )
            for host in hosts
        )
    except Exception:  # noqa: BLE001
        return True


class HostProbe(Frozen):
    """Whether the code host answered a read as a push would meet it, and what git said when it
    did not."""

    healthy: bool
    error: str = ""


def _batch_ssh(checkout: Path) -> str:
    """The ssh command a push of `checkout` runs, told never to ask a question: the one in the
    environment, else the repo's configured one, else plain `ssh`."""
    configured = shell.git(checkout, "config", "--get", "core.sshCommand", check=False)
    command = os.environ.get("GIT_SSH_COMMAND") or configured.stdout.strip() or "ssh"
    return f"{command} -o BatchMode=yes"


def code_host_healthy(checkout: Path, *, timeout: float, run: Run | None = None) -> HostProbe:
    """Whether the code host `checkout` pushes to answers `git ls-remote <remote> HEAD`.

    Unlike a connect it reads from the host over the transport a push uses, with the same
    credentials and agent, so a refused key or an HTTP refusal fails it. It never prompts. Only
    the host's own words for an outage count against it (`transport_failure`): a failure to run
    git, a repo with no remote or a refusal that names the repository or the person is not
    held against the host, so a bug in the probe never holds work.
    """
    runner = run or subprocess.run
    try:
        if not checkout.is_dir() or not shell.has_origin(checkout):
            return HostProbe(healthy=True)
        remote = restack.push_target(checkout)
        env = {
            **untranslated_env(),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_SSH_COMMAND": _batch_ssh(checkout),
        }
        limit = timeout * CODE_HOST_TIMEOUT_FACTOR
        try:
            result = runner(
                ["git", "ls-remote", remote, "HEAD"],
                cwd=checkout,
                capture_output=True,
                text=True,
                timeout=limit,
                env=env,
                start_new_session=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return HostProbe(healthy=False, error=f"git ls-remote timed out after {limit:g}s")
        if result.returncode == 0:
            return HostProbe(healthy=True)
        said = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
        failure = transport_failure(said)
        return (
            HostProbe(healthy=False, error=failure.message) if failure else HostProbe(healthy=True)
        )
    except Exception:  # noqa: BLE001 — a probe that breaks must not hold work.
        return HostProbe(healthy=True)
