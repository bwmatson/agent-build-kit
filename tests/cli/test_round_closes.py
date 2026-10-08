"""The pass's round retries the closes that are still pending."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from tests.cli.test_round import inst, isolated, run  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_a_round_retries_the_closes_that_are_pending(
    inst: Installation,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli, "retry_closes", lambda *args, **kwargs: calls.append(args))

    run(inst, cli.store_for(inst), submit=False)

    assert calls


def test_a_round_posts_the_replies_that_are_owed(
    inst: Installation,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(cli, "retry_replies", lambda *args, **kwargs: calls.append(args))

    run(inst, cli.store_for(inst), submit=False)

    assert calls
