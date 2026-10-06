"""Which command records the live stack beside a tier 2 result: the config's
when it says, the repo's infrastructure profile's when it does not, nothing
when told so."""

from pathlib import Path

import pytest

from agent_build_kit import infra
from agent_build_kit.config import (
    ConfigError,
    VerifyConfig,
    WorkspaceConfig,
    load,
    stack_versions_for,
)

CONTAINER_LISTING = ["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"]
REPO = "repos:\n  app:\n    path: /tmp/app\n    slug: example/app\n"


def _load(tmp_path: Path, repo_lines: str = "", verify_lines: str = "") -> WorkspaceConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(REPO + repo_lines + verify_lines)
    return load(path)


def test_an_absent_key_uses_the_repos_infrastructure_command() -> None:
    assert stack_versions_for(VerifyConfig(), infra.get("docker")) == CONTAINER_LISTING


def test_a_list_in_config_overrides_the_infrastructure_profile() -> None:
    verify = VerifyConfig(stack_versions_command=["kubectl", "get", "pods"])

    assert stack_versions_for(verify, infra.get("docker")) == ["kubectl", "get", "pods"]


def test_an_explicit_null_records_nothing() -> None:
    verify = VerifyConfig(stack_versions_command=None)

    assert stack_versions_for(verify, infra.get("docker")) is None


def test_the_none_profile_records_nothing_by_default() -> None:
    assert stack_versions_for(VerifyConfig(), infra.get("none")) is None


def test_a_config_with_the_key_absent_listed_or_null_loads_three_distinct_values(
    tmp_path: Path,
) -> None:
    absent = _load(tmp_path).verify
    listed = _load(
        tmp_path, verify_lines="verify:\n  stack_versions_command: [docker, ps]\n"
    ).verify
    null = _load(tmp_path, verify_lines="verify:\n  stack_versions_command: null\n").verify

    assert listed.stack_versions_command == ["docker", "ps"]
    assert null.stack_versions_command is None
    assert absent.stack_versions_command not in (None, ["docker", "ps"])
    docker = infra.get("docker")
    assert stack_versions_for(absent, docker) == CONTAINER_LISTING
    assert stack_versions_for(listed, docker) == ["docker", "ps"]
    assert stack_versions_for(null, docker) is None


def test_a_repo_that_names_no_infrastructure_gets_none(tmp_path: Path) -> None:
    config = _load(tmp_path)

    repo = config.repos["app"]
    assert repo.infra == "none"
    assert stack_versions_for(config.verify, infra.get(repo.infra)) is None


def test_a_repo_naming_docker_records_the_container_listing(tmp_path: Path) -> None:
    config = _load(tmp_path, repo_lines="    infra: docker\n")

    repo = config.repos["app"]
    assert stack_versions_for(config.verify, infra.get(repo.infra)) == CONTAINER_LISTING


def test_an_unknown_infrastructure_name_fails_at_load_naming_the_registered_ones(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError) as refused:
        _load(tmp_path, repo_lines="    infra: nosuch\n")

    message = str(refused.value)
    assert "'app'" in message and "docker" in message and "none" in message
