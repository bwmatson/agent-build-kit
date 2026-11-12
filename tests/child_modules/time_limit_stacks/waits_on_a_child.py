import os
import subprocess
import sys

import pytest


def test_waits_on_a_program() -> None:
    if not os.environ.get("ABK_CHILD_WAITS_ON_A_PROGRAM"):
        pytest.skip("only the scenario that drives this module sets the variable")
    subprocess.run([sys.executable, "-c", "import time; time.sleep(600)", "abk-waited-for-child"])
