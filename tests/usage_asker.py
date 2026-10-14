"""What a spawned asker process runs: it rebuilds the faked endpoint, the credential and
anchor paths and the default config that a forked child used to inherit."""

import multiprocessing
from pathlib import Path


def asking_in_a_process(
    asks: int,
    results: "multiprocessing.Queue",
    home: Path,
    calls: Path,
    answer: dict,
    call_seconds: float,
) -> None:
    raise NotImplementedError
