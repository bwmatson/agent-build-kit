"""Containers: the live stack is whatever `docker ps` lists."""

from __future__ import annotations

from agent_build_kit.model import Frozen


class DockerProfile(Frozen):
    name: str = "docker"
    detect_markers: tuple[str, ...] = (
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
        "Dockerfile",
    )
    stack_versions_command: tuple[str, ...] | None = (
        "docker",
        "ps",
        "--format",
        "{{.Names}}\t{{.Image}}",
    )


PROFILE = DockerProfile()
