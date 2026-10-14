"""`abk usage backfill-costs` is gone: the parser refuses it (spec: usage-accounting, the
temporary repair command is removed). `abk usage replay` stays."""

import pytest

from agent_build_kit.cli import build_parser


@pytest.mark.parametrize(
    "argv", [["usage", "backfill-costs"], ["usage", "backfill-costs", "--apply"]]
)
def test_the_backfill_command_is_refused(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        build_parser().parse_args(argv)

    assert stop.value.code == 2
    assert "backfill-costs" in capsys.readouterr().err


def test_the_usage_group_no_longer_lists_the_backfill(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["usage", "--help"])

    assert "backfill" not in capsys.readouterr().out
