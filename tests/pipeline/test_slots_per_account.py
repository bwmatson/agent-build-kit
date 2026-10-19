"""Units in progress are counted per resolved account against that account's own limit, so one
account's stalled units never stop another's (spec: claude-accounts, usage and slots are per
account). Seen through `abk status`, which shows what the tick would start and which queues are
full."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED
from tests.conftest import ready_queue, status_lines
from tests.factories import new_unit

REPOS = ("app", "platform", "web")


def repos(root: Path, labels: dict[str, str]) -> dict:
    """Three repos; those in `labels` name an account."""
    return {
        name: {
            "path": str(root / "checkouts" / name),
            "slug": f"example/{name}",
            **({"account": labels[name]} if name in labels else {}),
        }
        for name in REPOS
    }


def stalled(repo: str, count: int, store: UnitStore) -> None:
    ids = [f"{repo}-failed{n}/1" for n in range(count)]
    store.upsert([new_unit(uid, repo=repo) for uid in ids])
    for uid in ids:
        store.set_state(uid, FAILED, note="broke", branch=f"spec/{uid}")


def status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    labels: dict[str, str],
    accounts: dict,
    stalled_on: dict[str, int],
    ready: tuple[str, ...],
    limit: int = 5,
) -> list[str]:
    def record(store: UnitStore) -> None:
        for repo, count in stalled_on.items():
            stalled(repo, count, store)

    return status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [new_unit(f"{repo}-ready/1", repo=repo) for repo in ready],
        limit=limit,
        repos=repos(tmp_path, labels),
        record=record,
        runtimes={"claude_code": {"accounts": accounts}},
    )


def kit(tmp_path: Path, **fields: object) -> dict:
    return {"kit": {"config_dir": str(tmp_path / "kit-home"), **fields}}


def started(lines: list[str]) -> list[str]:
    return [line.split()[1] for line in ready_queue(lines)]


def test_failed_units_filling_one_accounts_slots_do_not_stop_the_default_accounts_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(
        tmp_path,
        monkeypatch,
        capsys,
        labels={"app": "kit", "platform": "kit"},
        accounts=kit(tmp_path, max_units_in_progress=2),
        stalled_on={"app": 2},
        ready=("app", "platform", "web"),
    )

    # `app` and `platform` share the `kit` account's two places; `web` is on the default account.
    assert started(lines) == ["web-ready/1"]


def test_a_unit_counts_against_its_accounts_limit_not_the_default_accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(
        tmp_path,
        monkeypatch,
        capsys,
        labels={"app": "kit"},
        accounts=kit(tmp_path, max_units_in_progress=1),
        stalled_on={"app": 1},
        ready=("app",),
        limit=5,
    )

    assert started(lines) == []
    assert any("queue is full" in line and "limit 1" in line for line in lines)


def test_a_label_that_falls_back_to_the_default_account_counts_against_its_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(
        tmp_path,
        monkeypatch,
        capsys,
        labels={"app": "kit"},
        accounts={"kit": {"max_units_in_progress": 9}},
        stalled_on={"platform": 2},
        ready=("app", "web"),
        limit=2,
    )

    # `kit` has no directory here, so `app` is on the default account with `platform` and `web`.
    assert started(lines) == []
    assert any("queue is full" in line and "limit 2" in line for line in lines)
