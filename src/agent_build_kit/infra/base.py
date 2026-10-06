"""What the pipeline needs to know about a repo's infrastructure.

Independent of the toolchain: which container tooling a repo runs on is not
decided by its language. A repo names its profile in abk.yaml (`infra:`).
"""

from __future__ import annotations

from typing import Protocol


class InfraProfile(Protocol):
    # Read-only members: the shipped profiles are frozen values.
    @property
    def name(self) -> str: ...

    # Files whose presence in a repo root suggest this profile (init's detection).
    @property
    def detect_markers(self) -> tuple[str, ...]: ...

    # What lists the live stack beside a tier 2 result; None for no such stack.
    @property
    def stack_versions_command(self) -> tuple[str, ...] | None: ...
