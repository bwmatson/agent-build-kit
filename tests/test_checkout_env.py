"""The suite is cut off from the checkout's environment file (spec: repo-wide-guards)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import installation
from tests.checkout_env import without_checkout_env
from tests.tracked_files import ROOT


def test_the_checkouts_own_env_file_is_reported_absent() -> None:
    lookup = without_checkout_env(lambda root: root / ".env")

    assert not lookup(ROOT).exists()


def test_another_roots_env_file_is_returned_unchanged(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ABK_KEY=1\n")
    lookup = without_checkout_env(lambda root: root / ".env")

    assert lookup(tmp_path) == tmp_path / ".env"


def test_the_lookup_in_force_for_every_test_ignores_the_checkout() -> None:
    assert not installation.env_file_for(ROOT).exists()
