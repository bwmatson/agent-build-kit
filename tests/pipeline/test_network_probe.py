"""What the connectivity probe reports, and what that makes of a failed run.

The probe looks up and connects to the host a run called and to a control group, with the
resolver and the connect injected, so nothing here touches a network. A probe that cannot
answer counts as the host being reachable: a bug in it never parks a unit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline import network_probe as network_probe_module
from agent_build_kit.pipeline.network_probe import (
    Reachability,
    classify_reachability,
    control_group,
    control_reachable,
    probe_reachability,
)
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.settings import settings
from tests.conftest import make_installation

API = "api.example.test"
FORGE = "forge.example.test"
RESOLVERS = ("one.example.test", "two.example.test")


class Network:
    """Which names resolve and which hosts connect, and what was asked."""

    def __init__(self, *, resolves: set[str], connects: set[str]) -> None:
        self.resolves = resolves
        self.connects = connects
        self.timeouts: list[float] = []
        self.ports: dict[str, int] = {}

    def resolve(self, host: str) -> object:
        if host not in self.resolves:
            raise OSError(f"cannot resolve {host}")
        return host

    def connect(self, host: str, port: int, timeout: float) -> object:
        self.timeouts.append(timeout)
        self.ports[host] = port
        if host not in self.connects:
            raise TimeoutError(f"{host} did not answer")
        return host


def probe(network: Network, control: tuple[str, ...] = (FORGE, *RESOLVERS)) -> Reachability:
    return probe_reachability(
        API, control, timeout=3, resolve=network.resolve, connect=network.connect
    )


def test_a_host_that_resolves_and_connects_is_reached() -> None:
    everything = {API, FORGE, *RESOLVERS}

    assert probe(Network(resolves=everything, connects=everything)) == Reachability(
        api=True, control=True
    )


def test_the_api_host_is_connected_to_on_the_port_the_run_called() -> None:
    network = Network(resolves={API, FORGE}, connects={API, FORGE})

    probe_reachability(
        API,
        (FORGE,),
        timeout=3,
        api_port=8443,
        resolve=network.resolve,
        connect=network.connect,
    )

    assert network.ports == {API: 8443, FORGE: 443}


def test_each_connect_is_bounded_by_the_timeout() -> None:
    network = Network(resolves={API}, connects={API})

    probe(network)

    assert network.timeouts
    assert set(network.timeouts) == {3}


def test_a_host_whose_name_does_not_resolve_is_not_reached() -> None:
    network = Network(resolves={FORGE}, connects={API, FORGE})

    reached = probe(network)

    assert reached == Reachability(api=False, control=True)


def test_the_control_group_is_reached_when_any_one_host_connects() -> None:
    network = Network(resolves={API, RESOLVERS[1]}, connects={API, RESOLVERS[1]})

    assert probe(network).control is True


def test_the_control_group_is_not_reached_when_no_host_connects() -> None:
    network = Network(resolves={RESOLVERS[0]}, connects=set())

    assert probe(network) == Reachability(api=False, control=False)


def test_an_empty_control_group_reports_the_api_host_reachable() -> None:
    network = Network(resolves=set(), connects=set())

    assert probe(network, control=()).api is True


def test_a_probe_that_raises_reports_the_api_host_reachable() -> None:
    def broken(host: str) -> object:
        raise RuntimeError("the resolver library is broken")

    reached = probe_reachability(API, (FORGE,), timeout=3, resolve=broken)

    assert reached.api is True


def reports(api: bool, control: bool):
    return lambda *args, **kwargs: Reachability(api=api, control=control)


@pytest.mark.parametrize(
    ("api", "control", "outage"),
    [
        (False, False, Cause.NETWORK_UNAVAILABLE),
        (False, True, Cause.SERVICE_UNAVAILABLE),
        (True, True, None),
        (True, False, None),
    ],
)
def test_the_two_groups_sort_a_failure_into_an_outage_or_an_ordinary_failure(
    api: bool, control: bool, outage: Cause | None
) -> None:
    sorted_as = classify_reachability(API, (FORGE,), timeout=3, probe=reports(api, control))

    assert sorted_as == outage


def test_a_forge_host_alone_is_enough_to_call_it_the_service() -> None:
    network = Network(resolves={FORGE}, connects={FORGE})

    sorted_as = classify_reachability(
        API,
        (FORGE, *RESOLVERS),
        timeout=3,
        probe=lambda host, group, *, timeout, api_port: probe_reachability(
            host,
            group,
            timeout=timeout,
            api_port=api_port,
            resolve=network.resolve,
            connect=network.connect,
        ),
    )

    assert sorted_as is Cause.SERVICE_UNAVAILABLE


def test_a_probe_that_errors_is_an_ordinary_failure() -> None:
    def errors(*args: object, **kwargs: object) -> Reachability:
        raise RuntimeError("the probe broke")

    assert classify_reachability(API, (FORGE,), timeout=3, probe=errors) is None


def test_the_control_group_is_the_forge_hosts_then_the_configured_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path, limits={"network_control_hosts": ["ping.example.test"]})
    # After the installation, which reloads the settings.
    monkeypatch.setattr(settings, "github_api_url", "https://ghe.example.test/api/v3")

    assert control_group(inst) == ("ghe.example.test", "ping.example.test")


def test_the_control_group_is_reachable_when_a_host_connects_and_not_when_none_does(
    tmp_path: Path,
) -> None:
    inst = make_installation(tmp_path, limits={"network_control_hosts": ["ping.example.test"]})
    group = set(control_group(inst))
    up = Network(resolves=group, connects={"ping.example.test"})
    down = Network(resolves=group, connects=set())

    assert control_reachable(inst, resolve=up.resolve, connect=up.connect) is True
    assert control_reachable(inst, resolve=down.resolve, connect=down.connect) is False


def test_a_probe_that_raises_something_else_counts_as_reachable(tmp_path: Path) -> None:
    inst = make_installation(tmp_path, limits={"network_control_hosts": ["ping.example.test"]})

    def breaks(host: str) -> object:
        raise ValueError("label too long")

    assert control_reachable(inst, resolve=breaks) is True


def test_no_control_group_counts_as_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path)
    monkeypatch.setattr(network_probe_module, "control_group", lambda installation: ())

    assert control_reachable(inst) is True
