"""The leak gate's scans read each repository file once across the whole module.

Each scan used to read every scanned file again, so the gate read the checkout about ten
times. The reads are counted at the file read, not timed.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.installation_leaks import files
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import ROOT

GATE = ROOT / "tests" / "test_no_installation_leaks.py"


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_the_leak_gate_reads_each_scanned_file_once(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The configuration is parsed by the scans' setup, not scanned for leaks.
    scanned = {path for path in files(ROOT) if path.name != "abk.yaml"}
    reads: Counter[Path] = Counter()
    real = Path.read_text

    def counting(self: Path, *args, **kwargs):
        if self in scanned:
            reads[self] += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)

    result = pytester.inline_run("-p", "no:cacheprovider", "-m", "integration", str(GATE))

    _, _, failed = result.listoutcomes()
    assert failed == []
    assert reads, "the gate read no scanned file"
    assert [str(path) for path, count in reads.items() if count > 1] == []
