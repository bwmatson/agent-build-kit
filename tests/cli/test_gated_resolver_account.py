"""A conflict resolver is asked of the usage guard on its unit's own account (spec: claude-accounts,
usage and slots are per account).

The move is built the way `abk tick` builds it; the move itself is replaced by one that hands back
the resolver it was given, so the guard's own reading, cache and decision run for real over the
faked endpoint (`tests/usage_host.py`).
"""

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRateLimited
from tests.conftest import make_installation
from tests.usage_host import Host, pause_at, payload


def installation(tmp_path: Path, *, default: int, kit: int) -> Installation:
    """`app` on the default account with its weekly pause at `default`% and `platform` on `kit`
    with its pause at `kit`%."""
    directory = tmp_path / "second-claude"
    directory.mkdir()
    return make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {
                "path": str(tmp_path / "platform"),
                "slug": "example/platform",
                "account": "kit",
            },
        },
        runtimes={
            "claude_code": {
                "limits": pause_at(default),
                "accounts": {"kit": {"config_dir": str(directory), "limits": pause_at(kit)}},
            }
        },
    )


def resolver_of(
    inst: Installation, repo: str, monkeypatch: pytest.MonkeyPatch, refused: list[str]
) -> Any:
    """The conflict resolver `abk tick`'s move gives a unit moved in `repo`'s checkout."""
    given: list[Any] = []
    monkeypatch.setattr(cli, "resolved_move", lambda path, *args, **kwargs: given.append(kwargs))

    def hears(unit: str, resets_at: datetime | None) -> None:
        refused.append(unit)

    cli.build_turned_move(inst, gated=True, refused=hears)(
        inst.checkouts[repo], moving_unit="feature/1"
    )
    return given[0]["resolve"]


def test_a_unit_on_a_full_account_is_refused_by_its_own_accounts_limits_and_the_refusal_names_it(
    tmp_path: Path, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, default=92, kit=50)
    host.answers = [payload(weekly=60.0)]
    refused: list[str] = []
    resolve = resolver_of(inst, "platform", monkeypatch, refused)

    with pytest.raises(AgentRateLimited, match="account kit"):
        resolve("resolve", cwd=tmp_path)

    assert refused == ["feature/1"]


def test_a_unit_on_the_default_account_is_refused_on_its_own_windows_not_the_others(
    tmp_path: Path, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, default=50, kit=92)
    host.answers = [payload(weekly=60.0)]
    refused: list[str] = []
    resolve = resolver_of(inst, "app", monkeypatch, refused)

    with pytest.raises(AgentRateLimited) as error:
        resolve("resolve", cwd=tmp_path)

    assert "kit" not in str(error.value)
    assert refused == ["feature/1"]
