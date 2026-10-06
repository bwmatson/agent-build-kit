"""The gateway client behind the `UsageSource` seam (spec:
gateway-usage-attribution): `begin` mints a key for one run and hands back the
environment that carries it, `finish` reads that key's totals and revokes it.

The gateway is `tests/fake_gateway.py`, a real HTTP server speaking a gateway's
JSON, on a local port.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pytest

from agent_build_kit.pipeline.gateway_usage import (
    KEY_ENV,
    GatewayUsage,
    Spend,
    configured_source,
    forget_warnings,
)
from agent_build_kit.settings import settings
from tests.fake_gateway import MASTER, FakeGateway, serving, unreachable_url


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    with serving() as fake:
        yield fake


@pytest.fixture(autouse=True)
def fresh_warnings() -> None:
    forget_warnings()


def source(url: str, said: list[str]) -> GatewayUsage:
    return GatewayUsage(url, MASTER, said.append)


def test_begin_mints_a_key_aliased_with_the_place_and_hands_it_over_in_the_environment(
    gateway: FakeGateway,
) -> None:
    env, _ = source(gateway.url, []).begin("add-marker/1:review:2")

    (minted,) = gateway.minted
    assert env == {KEY_ENV: minted["key"]}
    assert minted["alias"].startswith("abk:add-marker/1:review:2:")
    assert minted["alias"] != "abk:add-marker/1:review:2:"


def test_finish_reads_the_totals_logged_for_the_key_and_revokes_it(
    gateway: FakeGateway,
) -> None:
    client = source(gateway.url, [])
    env, handle = client.begin("add-marker/1:implement:0")
    gateway.spend(env[KEY_ENV], prompt=1200, completion=300, cost=0.25)
    gateway.spend(env[KEY_ENV], prompt=800, completion=50, cost=0.125)

    spent = client.finish(handle)

    assert spent.usage is not None
    assert spent.usage.input_tokens == 2000
    assert spent.usage.output_tokens == 350
    assert spent.usage.cache_read_input_tokens is None
    assert spent.cost_usd == 0.375
    assert gateway.revoked == [env[KEY_ENV]]


def test_a_key_with_no_logged_traffic_reads_as_absent_and_is_still_revoked(
    gateway: FakeGateway,
) -> None:
    client = source(gateway.url, [])
    env, handle = client.begin("add-marker/1:implement:0")

    spent = client.finish(handle)

    assert spent == Spend()
    assert gateway.revoked == [env[KEY_ENV]]


def test_runs_going_at_once_get_different_keys_and_each_reads_only_its_own(
    gateway: FakeGateway,
) -> None:
    client = source(gateway.url, [])
    runs = 6
    everyone_has_a_key = threading.Barrier(runs)
    spent: dict[int, Spend] = {}
    keys: dict[int, str] = {}

    def one(n: int) -> None:
        env, handle = client.begin(f"add-marker/{n}:implement:0")
        keys[n] = env[KEY_ENV]
        everyone_has_a_key.wait(timeout=10)
        gateway.spend(env[KEY_ENV], prompt=1000 * (n + 1), completion=10 * (n + 1), cost=n + 1)
        everyone_has_a_key.wait(timeout=10)
        spent[n] = client.finish(handle)

    threads = [threading.Thread(target=one, args=(n,)) for n in range(runs)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(set(keys.values())) == runs
    assert len(set(gateway.aliases)) == runs
    for n in range(runs):
        usage = spent[n].usage
        assert usage is not None
        assert usage.input_tokens == 1000 * (n + 1)
        assert usage.output_tokens == 10 * (n + 1)
        assert spent[n].cost_usd == n + 1
    assert sorted(gateway.revoked) == sorted(keys.values())


@pytest.mark.parametrize("fault", ["refused", "unreachable"])
def test_a_key_that_cannot_be_minted_says_so_once_and_the_run_goes_on_without_one(
    fault: str, gateway: FakeGateway
) -> None:
    gateway.refuse_mint = fault == "refused"
    said: list[str] = []
    client = source(unreachable_url() if fault == "unreachable" else gateway.url, said)

    env, handle = client.begin("add-marker/1:implement:0")
    spent = client.finish(handle)

    assert env == {}
    assert spent == Spend()
    assert len(said) == 1
    assert gateway.revoked == []


def test_totals_that_cannot_be_read_say_so_once_and_the_key_is_revoked_all_the_same(
    gateway: FakeGateway,
) -> None:
    gateway.fail_reads = True
    said: list[str] = []
    client = source(gateway.url, said)

    env, handle = client.begin("add-marker/1:implement:0")
    spent = client.finish(handle)

    assert spent == Spend()
    assert len(said) == 1
    assert gateway.revoked == [env[KEY_ENV]]


def test_with_neither_setting_there_is_no_source_and_nothing_is_said(
    gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "gateway_url", "")
    monkeypatch.setattr(settings, "gateway_master_key", "")
    said: list[str] = []

    assert configured_source(said.append) is None

    assert said == []
    assert gateway.calls == []


def test_a_master_key_with_no_url_is_no_source_and_says_so_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "gateway_url", "")
    monkeypatch.setattr(settings, "gateway_master_key", MASTER)
    said: list[str] = []

    assert configured_source(said.append) is None

    assert len(said) == 1
    assert configured_source(said.append) is None
    assert len(said) == 1


def test_both_settings_make_a_source(gateway: FakeGateway, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gateway_url", gateway.url)
    monkeypatch.setattr(settings, "gateway_master_key", MASTER)

    client = configured_source([].append)

    assert client is not None
    env, handle = client.begin("add-marker/1:implement:0")
    client.finish(handle)
    assert env == {KEY_ENV: gateway.minted[0]["key"]}
