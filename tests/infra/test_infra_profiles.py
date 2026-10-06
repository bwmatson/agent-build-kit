"""The infrastructure profiles a repo can name: what ships, and what stays out
of the toolchain profiles."""

import pytest

from agent_build_kit import infra, profiles

CONTAINER_LISTING = ("docker", "ps", "--format", "{{.Names}}\t{{.Image}}")


def test_the_shipped_profiles_are_docker_and_none() -> None:
    assert {"docker", "none"} <= set(infra.names())


def test_docker_lists_containers_and_is_detected_by_a_compose_file_or_dockerfile() -> None:
    docker = infra.get("docker")

    assert docker.stack_versions_command == CONTAINER_LISTING
    assert {"compose.yaml", "docker-compose.yml", "Dockerfile"} <= set(docker.detect_markers)


def test_none_has_no_command_and_no_markers() -> None:
    none = infra.get("none")

    assert none.stack_versions_command is None
    assert none.detect_markers == ()


def test_an_unknown_profile_is_refused_naming_the_known_ones() -> None:
    with pytest.raises(KeyError, match="nosuch.*docker.*none"):
        infra.get("nosuch")


@pytest.mark.parametrize("name", ["python-uv", "node-npm"])
def test_the_toolchain_profiles_carry_no_stack_versions_command(name: str) -> None:
    assert not hasattr(profiles.get(name), "stack_versions_command")
