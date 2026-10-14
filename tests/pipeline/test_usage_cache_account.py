"""A kept reading belongs to one account (spec: usage-account).

A reading, a cool-down or a fallback recorded for another account is discarded, never served
and never extended; a file with no account is served only to the default account, and the
default account writes no account field.
"""

import json
from datetime import UTC, datetime, timedelta

from agent_build_kit.pipeline.usage_guard import current_usage, read_live_usage
from agent_build_kit.settings import settings
from tests.usage_host import Host, payload

AGE = timedelta(minutes=5)


def account(host: Host, name: str | None) -> str | None:
    """Set the account to the directory `name` under the host's home; None sets none."""
    directory = host.home / name if name else None
    host.monkeypatch.setattr(settings, "claude_home", directory)
    return str(directory) if directory else None


def keep(host: Host, recorded: str | None, *, age: timedelta = AGE, **more: object) -> None:
    """The kept reading, recorded for `recorded` (no field for None), with `more` beside it."""
    host.keep_reading(age)
    body = json.loads(host.cache.read_text())
    body.update(more)
    if recorded is not None:
        body["account"] = recorded
    host.cache.write_text(json.dumps(body))


def test_a_reading_of_another_account_is_discarded_and_the_file_then_records_the_current(
    host: Host,
) -> None:
    keep(host, account(host, "a"))
    current = account(host, "b")
    host.answers = [payload(session=61.0)]

    reading = current_usage()

    assert host.asked == 1
    assert reading is not None
    assert reading.source == "live"
    assert json.loads(host.cache.read_text())["account"] == current


def test_a_cool_down_of_another_account_is_not_in_force(host: Host) -> None:
    until = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    keep(host, account(host, "a"), age=timedelta(minutes=40), cooldown_until=until)
    account(host, "b")
    host.answers = [payload()]

    reading = read_live_usage()

    assert host.asked == 1
    assert reading is not None


def test_a_file_with_no_account_is_discarded_for_an_account_and_served_with_none(
    host: Host,
) -> None:
    keep(host, None)
    account(host, None)
    served = current_usage()
    assert host.asked == 0
    assert served is not None
    assert served.source == "cache"

    account(host, "a")
    host.answers = [payload()]
    current_usage()

    assert host.asked == 1


def test_the_account_is_written_only_when_one_is_set(host: Host) -> None:
    account(host, None)
    host.answers = [payload()]
    read_live_usage()
    written = json.loads(host.cache.read_text())
    assert "account" not in written
    assert "fetched_at" in written

    host.cache.unlink()
    current = account(host, "a")
    host.answers = [payload()]
    read_live_usage()

    assert json.loads(host.cache.read_text())["account"] == current
