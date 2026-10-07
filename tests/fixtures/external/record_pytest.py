"""Re-record `tests/fixtures/external/pytest/*.xml` from the installed pytest.

    uv run python tests/fixtures/external/record_pytest.py

Each fixture is the JUnit report pytest wrote for one tiny test file in a
temporary directory: a test that raises `NotImplementedError`, one whose module
imports something that does not exist, one asking for a fixture nobody defines,
and one whose assertion fails. Only the temporary path, the interpreter's
and home directories, and timings are redacted; the header names the tool version and
the command.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "pytest"

CASES = {
    "missing_implementation": "def test_new():\n    raise NotImplementedError\n",
    "import_error": "from nothing_here import thing\n\n\ndef test_new():\n    assert thing\n",
    "fixture_error": "def test_new(db):\n    assert db\n",
    "assertion": "def test_new():\n    assert 1 == 2\n",
    "assertion_mentions_fixture": (
        "def load_fixture(name):\n    return None\n\n\n"
        'def test_new():\n    assert load_fixture("a") == 1\n'
    ),
    "fixture_not_implemented": (
        "import pytest\n\n\n@pytest.fixture\ndef thing():\n    raise NotImplementedError\n\n\n"
        "def test_new(thing):\n    assert thing\n"
    ),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    version = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"], capture_output=True, text=True, check=True
    )
    tool = (version.stdout + version.stderr).strip()
    for name, source in CASES.items():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_case.py").write_text(source)
            command = ["pytest", "test_case.py", "-p", "no:cacheprovider", "--tb=line", "-q"]
            subprocess.run(
                [sys.executable, "-m", *command, "--junitxml=report.xml"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            report = (root / "report.xml").read_text()
        report = re.sub(r' (time|timestamp|hostname)="[^"]*"', "", report)
        report = report.replace(tmp, "/tmp/case")
        # The interpreter's own paths name the machine that recorded them.
        report = report.replace(sys.base_prefix, "/opt/python")
        report = report.replace(str(Path.home()), "~")
        header = f"<!-- tool: {tool}\n     command: {' '.join(command)} --junitxml=<path> -->\n"
        (OUT / f"{name}.xml").write_text(header + report + "\n")


if __name__ == "__main__":
    main()
