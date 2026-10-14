"""Re-record `tests/fixtures/external/vitest/*.xml` from Vitest.

    uv run python tests/fixtures/external/record_vitest.py

Each fixture is the JUnit report Vitest wrote for one tiny project in a temporary
directory: a failing assertion beside a skipped and a passing test, a stub that throws
`not implemented`, a test file importing a module that does not exist, a type error, and a
passing run, a syntax error, a run that executed nothing, and a failing test file beside a
passing one from another file. Needs network access once, for `npx` to fetch Vitest. Only the
temporary path, the tool's cache path, timings and host name are redacted; the header names the
tool version and the command. Name cases on the command line to record only those.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "vitest"

COMMAND = ["npx", "--yes", "vitest", "run", "--reporter=junit", "--passWithNoTests"]
REPORT_FILE = "report.xml"
HEADER = "import { expect, test } from 'vitest';\n"

CASES = {
    "assertion": (
        "a.test.ts",
        HEADER
        + "test('adds', () => {\n  expect(1).toBe(2);\n});\n"
        + "test.skip('later', () => {});\n"
        + "test('holds', () => {\n  expect(1).toBe(1);\n});\n",
    ),
    "not_implemented": (
        "b.test.ts",
        HEADER
        + "import { create } from './b';\n"
        + "test('creates', () => {\n  expect(create()).toBe(1);\n});\n",
        {
            "b.ts": (
                "export function create(): number {\n  throw new Error('not implemented');\n}\n"
            )
        },
    ),
    "missing_import": (
        "c.test.ts",
        HEADER
        + "import { thing } from './nothing';\n"
        + "test('uses', () => {\n  expect(thing).toBe(1);\n});\n",
    ),
    "type_error": (
        "e.test.ts",
        HEADER
        + "const n: number = 'text';\ntest('types', () => {\n  expect(n).toBe('text');\n});\n",
    ),
    "assertion_only": (
        "a.test.ts",
        HEADER + "test('adds', () => {\n  expect(1).toBe(2);\n});\n",
    ),
    "other_not_implemented": (
        "i.test.ts",
        HEADER
        + "test('reads', () => {\n"
        + "  throw new Error('the _read() method is not implemented');\n});\n",
    ),
    "syntax_error": (
        "f.test.ts",
        HEADER + "test('parses', () => {\n  expect(1 +).toBe(1);\n});\n",
    ),
    "empty": (None, ""),
    "extra_suite": (
        "g.test.ts",
        HEADER + "test('adds', () => {\n  expect(1).toBe(2);\n});\n",
        {"h.test.ts": HEADER + "test('holds', () => {\n  expect(1).toBe(1);\n});\n"},
    ),
    "passing": (
        "d.test.ts",
        HEADER
        + "test('one', () => {\n  expect(1).toBe(1);\n});\n"
        + "test('two', () => {\n  expect(2).toBe(2);\n});\n",
    ),
}


def record(name: str, case: tuple) -> None:
    test_name, source, *extra = case
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "package.json").write_text('{"name": "case", "type": "module"}\n')
        if test_name:
            (root / test_name).write_text(source)
        for file, content in (extra[0] if extra else {}).items():
            (root / file).write_text(content)
        subprocess.run(
            [*COMMAND, f"--outputFile={REPORT_FILE}"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        report = (root / REPORT_FILE).read_text()
        version = subprocess.run(
            ["npx", "--yes", "vitest", "--version"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    report = report.replace(tmp, "")
    # A stack frame inside the tool's own cache names the machine's home directory.
    report = re.sub(r"(?:\.\./)+\S*?/node_modules/", "node_modules/", report)
    report = re.sub(r'(time|timestamp|hostname)="[^"]*"', r'\1="0"', report)
    tool = version.replace("vitest/", "vitest ")
    header = f"<!-- tool: {tool}\n     command: {' '.join(COMMAND[2:])} --outputFile=<path> -->\n"
    (OUT / f"{name}.xml").write_text(header + report)


def main() -> None:
    """Record the cases named on the command line, or all of them."""
    OUT.mkdir(exist_ok=True)
    for name in sys.argv[1:] or CASES:
        record(name, CASES[name])


if __name__ == "__main__":
    main()
