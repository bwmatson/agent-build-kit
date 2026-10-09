"""A unit's lease: one holder at a time, shared by every process that reads the directory."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_build_kit.pipeline.lease import Leases, lease_dir


def leases(tmp_path: Path) -> Leases:
    return Leases(lease_dir(tmp_path))


def test_a_unit_nobody_chats_with_has_no_holder(tmp_path: Path) -> None:
    assert leases(tmp_path).holder("feature/2") is None


def test_the_first_holder_takes_the_lease_and_a_second_is_refused(tmp_path: Path) -> None:
    held = leases(tmp_path)

    assert held.take("feature/2", "tab:a") is True
    assert held.take("feature/2", "tab:b") is False

    assert held.holder("feature/2") == "tab:a"


def test_taking_a_lease_again_keeps_it(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take("feature/2", "tab:a")

    assert held.take("feature/2", "tab:a") is True


def test_another_process_reading_the_directory_sees_the_lease(tmp_path: Path) -> None:
    leases(tmp_path).take("feature/2", "tab:a")

    assert leases(tmp_path).holder("feature/2") == "tab:a"
    assert leases(tmp_path).take("feature/2", "tab:b") is False


def test_releasing_returns_the_unit_and_lets_another_holder_take_it(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take("feature/2", "tab:a")

    held.release("feature/2", "tab:a")

    assert held.holder("feature/2") is None
    assert held.take("feature/2", "tab:b") is True


def test_a_holder_that_does_not_hold_the_lease_cannot_release_it(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take("feature/2", "tab:a")

    held.release("feature/2", "tab:b")

    assert held.holder("feature/2") == "tab:a"


def test_units_are_leased_apart(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take("feature/2", "tab:a")

    assert held.take("feature/3", "tab:b") is True
    assert held.take("other/2", "tab:b") is True


def test_a_closing_page_releases_every_lease_it_holds_and_no_other(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take("feature/2", "tab:a")
    held.take("feature/3", "tab:a")
    held.take("feature/4", "tab:b")

    held.release_all("tab:a")

    assert [held.holder(u) for u in ("feature/2", "feature/3", "feature/4")] == [
        None,
        None,
        "tab:b",
    ]


def test_a_lease_written_by_a_process_that_has_exited_holds_nothing(tmp_path: Path) -> None:
    directory = lease_dir(tmp_path)
    code = (
        "import sys; from pathlib import Path; "
        "from agent_build_kit.pipeline.lease import Leases; "
        "assert Leases(Path(sys.argv[1])).take('feature/2', 'tab:a')"
    )
    subprocess.run([sys.executable, "-c", code, str(directory)], check=True)

    held = Leases(directory)

    assert held.holder("feature/2") is None
    assert held.take("feature/2", "tab:b") is True
