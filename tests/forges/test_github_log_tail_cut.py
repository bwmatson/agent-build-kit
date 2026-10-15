"""A failed job's log is kept to its end by the shared tail cut: whole lines, and
a code fence the dropped head left open is opened again so the report's own closing
fence closes it."""

from __future__ import annotations

import pytest

from tests.forges.github_logs import logs_host, report

pytestmark = pytest.mark.usefixtures("github_env")

PREFIX = "2026-10-01T16:34:21.1000000Z "
ERROR = "the real failure"


def long_log(*lines: str) -> str:
    filler = [f"{PREFIX}filler line {i:05d} of the job" for i in range(600)]
    return "\n".join([*filler, *lines, f"{PREFIX}##[error]{ERROR}"])


def test_a_long_log_keeps_whole_lines_from_its_end() -> None:
    text = report(logs_host(job_log=long_log()))

    body = text.split("```\n", 1)[1].rsplit("\n```", 1)[0].splitlines()[1:]
    assert body[-1].endswith(ERROR)
    assert all(line.startswith("filler line") or line.endswith(ERROR) for line in body), (
        "the first kept line is whole, not the middle of one"
    )


def test_a_fence_the_cut_head_left_open_is_opened_again() -> None:
    fenced = [f"{PREFIX}```", *(f"{PREFIX}in the fence {i:04d}" for i in range(400))]
    text = report(logs_host(job_log=long_log(*fenced)))

    body = text.split("```\n", 1)[1].rsplit("\n```", 1)[0].splitlines()[1:]
    assert body[0] == "```", "the tail's own text is inside the fence the dropped head opened"
