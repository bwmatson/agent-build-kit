"""What the code-host outage tests share: repos whose origin is on a named host, a probe that
answers as a test says and counts how often it was asked, and units parked for the code host.

Nothing here reaches a network: a remote is only a URL in a repo's config, and the probe is a
stand-in for `network_probe.code_host_healthy`."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import network_probe, pause
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import git, init_repo
from tests.tick_pass import stored

GITHUB = "github.com"
AZURE = "dev.azure.com"
GITHUB_URL = "git@github.com:example/app.git"
AZURE_URL = "https://dev.azure.com/example/project/_git/platform"
REFUSED = "git@github.com: Permission denied (publickey)."


def give_remote(inst: Installation, repo: str, url: str) -> Path:
    """The repo's checkout as a real git repository whose `origin` is `url`."""
    checkout = init_repo(inst.checkouts[repo])
    git(checkout, "remote", "add", "origin", url)
    return checkout


class Probe:
    """Stands in for `network_probe.code_host_healthy`: answers as `healthy` says, and records
    each checkout it was asked about."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, healthy: bool = False) -> None:
        self.healthy = healthy
        self.error = REFUSED
        self.calls: list[Path] = []
        monkeypatch.setattr(network_probe, "code_host_healthy", self)

    def __call__(self, checkout: Path, **kwargs: object) -> network_probe.HostProbe:
        self.calls.append(checkout)
        return network_probe.HostProbe(
            healthy=self.healthy, error="" if self.healthy else self.error
        )


def park(store: UnitStore, uid: str, *, attempts: int = 1, repo: str = "app") -> None:
    """The unit as a push the code host refused leaves it, `attempts` times in a row, now."""
    store.upsert([stored(uid, repo=repo)])
    for _ in range(attempts):
        store.record_step(uid, "push")
        store.set_state(
            uid,
            PLANNED,
            branch=f"spec/{uid}",
            note=f"git push: host unavailable after 1 attempts ({REFUSED})",
            cause=Cause.HOST_UNAVAILABLE,
        )


def mark(inst: Installation, host: str, *, repo: str, now: datetime, error: str = REFUSED) -> None:
    """The marker a unit parking for `host` writes."""
    pause.note_host_outage(inst.state_dir, host, repo=repo, error=error, now=now)
