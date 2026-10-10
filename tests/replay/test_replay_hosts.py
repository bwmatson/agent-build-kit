"""The hosts that are part of the stack, and the refusal to stand in front of one."""

from pathlib import Path

import pytest

from agent_build_kit.config import (
    AzureDevOpsConfig,
    DevStackConfig,
    RepoConfig,
    RuntimeConfig,
    WorkspaceConfig,
)
from agent_build_kit.replay.hosts import in_stack_hosts
from agent_build_kit.replay.models import ReplayMode
from agent_build_kit.settings import Settings
from tests.replay.fake_upstream import FakeUpstream
from tests.replay.proxy import InStackUpstream, ReplayProxy
from tests.replay.support import UPSTREAM, config_for

GITHUB = "api.github.com"


def workspace(**repos: RepoConfig) -> WorkspaceConfig:
    return WorkspaceConfig(repos=repos)


def repo(**fields) -> RepoConfig:
    return RepoConfig(path=Path("/work/app"), slug="example/app", **fields)


def machine(**fields: str) -> Settings:
    return Settings(_env_file=None, **fields)


def test_verify_env_urls_are_in_the_stack_and_other_values_are_not() -> None:
    hosts = in_stack_hosts(
        workspace(),
        {
            "SVC_A_URL": "https://api.svc-a.example.com/v1",
            "TOKEN": "abc123",
            "BARE": "bare.example.org",
        },
        machine(),
    )
    assert hosts.why("api.svc-a.example.com") == "verify.env.SVC_A_URL"
    assert hosts.why("bare.example.org") is None


def test_a_repository_s_code_host_is_in_the_stack() -> None:
    github = in_stack_hosts(workspace(app=repo()), {}, machine(github_api_url=f"https://{GITHUB}"))
    assert github.why(GITHUB) == "repos.app.forge"

    azure = repo(
        forge="azure_devops", azure_devops=AzureDevOpsConfig(org="o", project="p", repo="r")
    )
    assert in_stack_hosts(workspace(app=azure), {}, machine()).why("dev.azure.com") == (
        "repos.app.forge"
    )

    assert in_stack_hosts(workspace(), {}, machine()).why(GITHUB) is None


@pytest.mark.parametrize(
    "setting",
    [
        "gateway_url",
        "prometheus_url",
        "tempo_url",
        "grafana_url",
        "otel_exporter_otlp_endpoint",
        "otel_exporter_otlp_traces_endpoint",
        "otel_exporter_otlp_metrics_endpoint",
    ],
)
def test_the_settings_naming_stack_endpoints_are_in_the_stack(setting: str) -> None:
    hosts = in_stack_hosts(workspace(), {}, machine(**{setting: "https://stack.example.com:4318"}))
    assert hosts.why("stack.example.com") == setting


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "127.9.9.9",
        "::1",
        "host.docker.internal",
        "10.1.2.3",
        "192.168.0.4",
        "172.16.5.5",
        "container-net",
    ],
)
def test_loopback_private_ranges_and_single_label_names_are_always_in_the_stack(host: str) -> None:
    assert in_stack_hosts(workspace(), {}, machine()).why(host)


def test_nothing_else_contributes() -> None:
    elsewhere = repo(dev_stack=DevStackConfig(script="https://hidden.example.com/up.sh"))
    config = WorkspaceConfig(
        repos={"app": elsewhere},
        runtimes={
            "acp": RuntimeConfig(command=["agent", "--endpoint", "https://model.example.com"])
        },
    )
    hosts = in_stack_hosts(config, {}, machine())
    assert hosts.why("hidden.example.com") is None
    assert hosts.why("model.example.com") is None


def test_an_upstream_in_the_stack_fails_at_startup_naming_it_and_the_key(
    upstream: FakeUpstream, tmp_path: Path
) -> None:
    stack = in_stack_hosts(workspace(), {"SVC_A_URL": upstream.url}, machine())
    config = config_for(upstream.url, tmp_path / "cassettes")

    with pytest.raises(InStackUpstream, match=f"{UPSTREAM}.*verify.env.SVC_A_URL"):
        with ReplayProxy(config, ReplayMode.record, staging=tmp_path / "s", in_stack=stack):
            pytest.fail("a listener was started for an upstream inside the stack")
