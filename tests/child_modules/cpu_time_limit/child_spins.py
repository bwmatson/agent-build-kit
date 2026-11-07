import subprocess
import sys

SPIN = "import time\nd = time.monotonic() + 30\nwhile time.monotonic() < d:\n    pass\n"


def test_waits_on_a_child_that_spins() -> None:
    subprocess.run([sys.executable, "-c", SPIN], check=False)
