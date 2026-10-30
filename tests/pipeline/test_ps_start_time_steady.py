"""`ps_start_time` names one process by one string however `ps` reads its clock.

`ps` derives a start time from the boot time plus the process's start ticks, and the boot time it
estimates can shift by a second between two runs on a loaded machine, so the same process can be
reported at two neighbouring seconds. The tests fake `ps` at its output boundary, one run after
another, so no clock and no load is involved.
"""

from __future__ import annotations

import subprocess

import pytest

from agent_build_kit.pipeline.file_lock import ps_start_time

PID = 4242
PS_STARTS = ["Wed Oct 29 18:39:00 2026", "Wed Oct 29 18:39:01 2026"]


def fake_ps(monkeypatch: pytest.MonkeyPatch, outputs: list[str]) -> None:
    """Make each `ps` run print the next of `outputs`, and any other command run as it is."""
    pending = list(outputs)
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        if argv[0] != "ps":
            return real_run(argv, *args, **kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=pending.pop(0) + "\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)


def test_a_one_second_drift_in_the_start_time_ps_reports_names_the_same_process(monkeypatch):
    fake_ps(monkeypatch, PS_STARTS)

    first = ps_start_time(PID)
    second = ps_start_time(PID)

    assert first is not None
    assert first == second, f"ps reported {PS_STARTS}; the two names should be one"


def test_a_ps_run_that_prints_nothing_once_does_not_make_a_live_process_unnamed(monkeypatch):
    fake_ps(monkeypatch, ["", PS_STARTS[0]])

    assert ps_start_time(PID) is not None
