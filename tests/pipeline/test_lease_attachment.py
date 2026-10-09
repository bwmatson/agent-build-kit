"""A lease records what a chat left in the checkouts it covers, and outlives its process and
its page while it holds changes or a commit that was made and not delivered."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.lease import Leases, lease_dir
from tests.attach_driver import leave_lease

UNIT = "feature/2"


def leases(tmp_path: Path) -> Leases:
    return Leases(lease_dir(tmp_path))


def test_a_lease_records_the_checkouts_the_session_the_runtime_and_the_head(
    tmp_path: Path,
) -> None:
    held = leases(tmp_path)

    held.take(
        UNIT,
        "tab:a",
        checkouts=("worktree", "planning"),
        session="sess-1",
        runtime="acp",
        head="9f2c1ab",
    )

    recorded = held.attachment(UNIT)
    assert recorded is not None
    assert (recorded.holder, recorded.checkouts) == ("tab:a", ("worktree", "planning"))
    assert (recorded.session, recorded.runtime, recorded.head) == ("sess-1", "acp", "9f2c1ab")
    assert recorded.changed == 0
    assert recorded.committed == ""
    assert recorded.stale is False


def test_a_record_written_before_the_fields_existed_still_reads(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take(UNIT, "tab:a")
    path = lease_dir(tmp_path) / "feature--2.lease"
    record = json.loads(path.read_text())
    path.write_text(json.dumps({key: record[key] for key in ("holder", "pid", "started")}))

    assert held.holder(UNIT) == "tab:a"
    recorded = held.attachment(UNIT)
    assert recorded is not None and recorded.changed == 0 and recorded.checkouts == ()


def test_marking_changes_records_how_many_files_are_changed(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take(UNIT, "tab:a", checkouts=("worktree",))

    held.mark_changes(UNIT, "tab:a", 3)

    recorded = held.attachment(UNIT)
    assert recorded is not None and recorded.changed == 3


def test_a_lease_whose_process_has_gone_and_which_holds_nothing_holds_nothing(
    tmp_path: Path,
) -> None:
    leave_lease(lease_dir(tmp_path), UNIT)

    held = leases(tmp_path)

    assert held.holder(UNIT) is None
    assert held.attachment(UNIT) is None
    assert held.take(UNIT, "tab:b") is True


def test_a_lease_whose_process_has_gone_with_changes_reads_as_a_stale_lease(
    tmp_path: Path,
) -> None:
    leave_lease(lease_dir(tmp_path), UNIT, files=2)

    held = leases(tmp_path)

    assert held.holder(UNIT) is None, "no process holds it"
    recorded = held.attachment(UNIT)
    assert recorded is not None
    assert (recorded.stale, recorded.changed, recorded.holder) == (True, 2, "tab:gone")
    assert (recorded.session, recorded.runtime, recorded.head) == ("sess", "claude_code", "abc123")


def test_a_commit_made_and_not_delivered_reads_as_a_stale_lease_with_its_hash(
    tmp_path: Path,
) -> None:
    leave_lease(lease_dir(tmp_path), UNIT, commit="7d41e90")

    recorded = leases(tmp_path).attachment(UNIT)

    assert recorded is not None
    assert (recorded.stale, recorded.committed) == (True, "7d41e90")


def test_a_live_lease_reads_as_not_stale(tmp_path: Path) -> None:
    held = leases(tmp_path)
    held.take(UNIT, "tab:a")
    held.mark_changes(UNIT, "tab:a", 1)

    recorded = held.attachment(UNIT)

    assert recorded is not None and recorded.stale is False


def test_every_attachment_is_listed_and_a_clean_lease_of_a_dead_process_is_not(
    tmp_path: Path,
) -> None:
    leave_lease(lease_dir(tmp_path), "feature/2", files=2)
    leave_lease(lease_dir(tmp_path), "feature/3")
    held = leases(tmp_path)
    held.take("feature/4", "tab:a")

    listed = {a.unit_id: a.stale for a in held.attachments()}

    assert listed == {"feature/2": True, "feature/4": False}


def test_closing_a_page_releases_a_lease_with_no_changes_and_keeps_one_with_changes(
    tmp_path: Path,
) -> None:
    held = leases(tmp_path)
    held.take("feature/2", "tab:a")
    held.take("feature/3", "tab:a")
    held.mark_changes("feature/3", "tab:a", 1)

    held.release_all("tab:a")

    assert held.attachment("feature/2") is None
    kept = held.attachment("feature/3")
    assert kept is not None and kept.changed == 1


def test_a_stale_lease_with_changes_is_taken_over_by_a_new_holder(tmp_path: Path) -> None:
    leave_lease(lease_dir(tmp_path), UNIT, files=2)
    held = leases(tmp_path)

    assert held.take(UNIT, "server") is True

    recorded = held.attachment(UNIT)
    assert recorded is not None
    assert (recorded.holder, recorded.stale, recorded.changed) == ("server", False, 2)
