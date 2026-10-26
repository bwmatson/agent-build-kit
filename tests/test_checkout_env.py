"""The suite is cut off from the checkout's environment file (spec: repo-wide-guards)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import installation
from tests.checkout_env import ABSENT, without_checkout_env
from tests.tracked_files import ROOT


def test_a_checkout_holding_an_env_file_has_it_reported_absent(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ABK_KEY=1\n")
    plain = lambda root: root / ".env"  # noqa: E731

    lookup = without_checkout_env(plain, checkout=tmp_path)

    assert plain(tmp_path).exists()
    assert lookup(tmp_path) == tmp_path / ABSENT
    assert not lookup(tmp_path).exists()


def test_another_roots_env_file_is_returned_unchanged(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("ABK_KEY=1\n")
    lookup = without_checkout_env(lambda root: root / ".env")

    assert lookup(tmp_path) == tmp_path / ".env"


def test_the_lookup_in_force_for_every_test_ignores_the_checkout() -> None:
    assert installation.env_file_for(ROOT) == ROOT / ABSENT
