"""The local Artifacts implementation: keys are files under the installation's state directory."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.orchestration.artifacts import ArtifactWriter


class LocalArtifacts:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation

    def put(self, key: str, value: str | bytes) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def list(self, prefix: str) -> list[str]:
        raise NotImplementedError

    def delete(self, prefix: str) -> None:
        raise NotImplementedError

    def writer(self, key: str) -> ArtifactWriter:
        raise NotImplementedError
