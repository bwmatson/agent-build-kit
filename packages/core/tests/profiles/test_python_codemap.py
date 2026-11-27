"""The Python profile's reader of a project's code: symbols, imports, calls, bases, test files."""

from pathlib import Path

import pytest

from agent_build_kit.codemap.graph import FileFacts, Reading
from agent_build_kit.profiles.python_uv import PythonUvProfile

LONG_DEFAULT = "x" * 45
LONG_SIGNATURE = "def f(" + ", ".join(f"argument_{i}: int" for i in range(40)) + ") -> None"

# (kind, span, lines, signature, doc) by symbol name
Expected = dict[str, tuple[str, tuple[int, int], int, str, str]]

SYMBOL_ROWS = [
    pytest.param(
        '"""Orders and their totals.\n\nMore detail."""\n',
        "Orders and their totals.",
        {},
        id="module-docstring",
    ),
    pytest.param(
        "import functools\n\n@functools.cache\ndef f(a: int = 1) -> int:\n"
        '    """Doc line.\n\n    more"""\n    return a\n',
        "",
        {"f": ("function", (3, 8), 6, "def f(a: int = 1) -> int", "Doc line.")},
        id="decorated-function",
    ),
    pytest.param(
        "async def load(path: str) -> int:\n    return 1\n",
        "",
        {"load": ("function", (1, 2), 2, "async def load(path: str) -> int", "")},
        id="async-function",
    ),
    pytest.param(
        'class Line(Base):\n    """An order line."""\n',
        "",
        {"Line": ("class", (1, 2), 2, "class Line(Base)", "An order line.")},
        id="class-with-base",
    ),
    pytest.param(
        "class C:\n    def m(self):\n        pass\n",
        "",
        {
            "C": ("class", (1, 3), 3, "class C", ""),
            "C.m": ("function", (2, 3), 2, "def m(self)", ""),
        },
        id="method",
    ),
    pytest.param(
        "def outer():\n    def inner():\n        pass\n\n    return inner\n",
        "",
        {"outer": ("function", (1, 5), 5, "def outer()", "")},
        id="nested-function-is-not-a-node",
    ),
    pytest.param(
        "def f():\n    pass\n\n\ndef f():\n    pass\n",
        "",
        {
            "f": ("function", (1, 2), 2, "def f()", ""),
            "f#2": ("function", (5, 6), 2, "def f()", ""),
        },
        id="redefinition",
    ),
    pytest.param(
        "def f(\n    a: int,\n    b: str,\n) -> None:\n    pass\n",
        "",
        {"f": ("function", (1, 5), 5, "def f( a: int, b: str, ) -> None", "")},
        id="multi-line-signature-is-collapsed",
    ),
    pytest.param(
        f'def f(a: str = "{LONG_DEFAULT}") -> None:\n    pass\n',
        "",
        {"f": ("function", (1, 2), 2, "def f(a: str = ...) -> None", "")},
        id="long-default-is-elided",
    ),
    pytest.param(
        LONG_SIGNATURE + ":\n    pass\n",
        "",
        {"f": ("function", (1, 2), 2, LONG_SIGNATURE[:199] + "…", "")},
        id="over-long-signature-is-cut",
    ),
]


def write_files(root: Path, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def read_project(root: Path, files: dict[str, str], tests: dict[str, str] | None = None) -> Reading:
    """Write the files and read them through the profile's reader."""
    tests = tests or {}
    write_files(root, {**files, **tests})
    reader = PythonUvProfile().code_reader()
    return reader.read(root, sorted(files), sorted(tests))


def facts_of(reading: Reading, path: str) -> FileFacts:
    return next(facts for facts in reading.files if facts.path == path)


@pytest.mark.parametrize(("source", "file_doc", "expected"), SYMBOL_ROWS)
def test_reader_gives_each_file_its_symbols(
    tmp_path: Path, source: str, file_doc: str, expected: Expected
) -> None:
    reading = read_project(tmp_path, {"mod.py": source})

    facts = facts_of(reading, "mod.py")
    assert facts.doc == file_doc
    assert facts.lines == len(source.splitlines())
    assert {
        symbol.name: (symbol.kind, symbol.span, symbol.lines, symbol.signature, symbol.doc)
        for symbol in facts.symbols
    } == expected
    assert reading.problems == ()


def test_imports_resolve_to_exactly_one_project_file_each(tmp_path: Path) -> None:
    user = (
        "import os\n"
        "import requests\n"
        "import ns.x\n"
        "import ns.dup\n"
        "from typing import TYPE_CHECKING\n"
        "from ns import y\n"
        "from ns.attr import name\n"
        "from . import sibling\n"
        "\n"
        "if TYPE_CHECKING:\n"
        "    from ns import typed\n"
        "\n\n"
        "def later():\n"
        "    from ns import late\n"
        "    return late\n"
    )
    sources = {
        "a/src/ns/user.py": user,
        "a/src/ns/x.py": "value = 1\n",
        "a/src/ns/attr.py": "name = 1\n",
        "a/src/ns/sibling.py": "value = 2\n",
        "a/src/ns/late.py": "value = 3\n",
        "a/src/ns/typed.py": "value = 4\n",
        "a/src/ns/dup.py": "value = 5\n",
        "b/src/ns/y.py": "value = 6\n",
        "b/src/ns/dup.py": "value = 7\n",
    }
    tests = {"tests/test_user.py": "import ns.x\nfrom ns import y\n\n\ndef test_it():\n    pass\n"}

    reading = read_project(tmp_path, sources, tests)

    imports = {(edge.source, edge.target) for edge in reading.edges if edge.kind == "imports"}
    assert imports == {
        ("a/src/ns/user.py", target)
        for target in (
            "a/src/ns/x.py",
            "b/src/ns/y.py",
            "a/src/ns/attr.py",
            "a/src/ns/sibling.py",
            "a/src/ns/typed.py",
            "a/src/ns/late.py",
        )
    }
    assert {facts.path for facts in reading.files} == set(sources)


M_FUNCTION = "def f():\n    pass\n"
M_CLASS = "class K:\n    pass\n"
M_METHOD = "class C:\n    def f(self):\n        pass\n"
M_BASE = "class B:\n    def b(self):\n        pass\n"

CALL_ROWS = [
    pytest.param(
        {"pkg/main.py": "def f():\n    pass\n\n\ndef g():\n    f()\n"},
        {("invokes", "pkg/main.py::g", "pkg/main.py::f")},
        id="same-file-function",
    ),
    pytest.param(
        {"pkg/m.py": M_FUNCTION, "pkg/main.py": "from pkg.m import f\n\n\ndef g():\n    f()\n"},
        {("invokes", "pkg/main.py::g", "pkg/m.py::f")},
        id="from-import-function",
    ),
    pytest.param(
        {"pkg/m.py": M_FUNCTION, "pkg/main.py": "from pkg import m\n\n\ndef g():\n    m.f()\n"},
        {("invokes", "pkg/main.py::g", "pkg/m.py::f")},
        id="module-attribute-call",
    ),
    pytest.param(
        {"pkg/m.py": M_CLASS, "pkg/main.py": "from pkg.m import K\n\n\ndef g():\n    K()\n"},
        {("invokes", "pkg/main.py::g", "pkg/m.py::K")},
        id="class-instantiation",
    ),
    pytest.param(
        {
            "pkg/main.py": (
                "class C:\n    def a(self):\n        self.b()\n\n    def b(self):\n        pass\n"
            )
        },
        {("invokes", "pkg/main.py::C.a", "pkg/main.py::C.b")},
        id="self-call-to-own-method",
    ),
    pytest.param(
        {
            "pkg/m.py": M_BASE,
            "pkg/main.py": (
                "from pkg.m import B\n\n\nclass C(B):\n    def a(self):\n        self.b()\n"
            ),
        },
        {
            ("invokes", "pkg/main.py::C.a", "pkg/m.py::B.b"),
            ("inherits", "pkg/main.py::C", "pkg/m.py::B"),
        },
        id="self-call-to-inherited-method",
    ),
    pytest.param(
        {
            "pkg/m.py": M_METHOD,
            "pkg/main.py": "from pkg.m import C\n\n\ndef g():\n    C.f(None)\n",
        },
        {("invokes", "pkg/main.py::g", "pkg/m.py::C.f")},
        id="class-attribute-call",
    ),
    pytest.param(
        {
            "pkg/m.py": "class B:\n    pass\n",
            "pkg/main.py": "from pkg.m import B\n\n\nclass C(B):\n    pass\n",
        },
        {("inherits", "pkg/main.py::C", "pkg/m.py::B")},
        id="base-class-from-another-module",
    ),
    pytest.param(
        {"pkg/main.py": "def g(obj, name):\n    getattr(obj, name)()\n"},
        set(),
        id="getattr-call-is-left-out",
    ),
    pytest.param(
        {"pkg/main.py": "def g(callback):\n    callback()\n"},
        set(),
        id="call-on-a-parameter-is-left-out",
    ),
    pytest.param(
        {"pkg/main.py": "def g(items):\n    print(len(items))\n"},
        set(),
        id="builtin-call-is-left-out",
    ),
]


@pytest.mark.parametrize(("files", "expected"), CALL_ROWS)
def test_calls_and_bases_resolve_only_when_statically_known(
    tmp_path: Path, files: dict[str, str], expected: set[tuple[str, str, str]]
) -> None:
    reading = read_project(tmp_path, files)

    found = {
        (edge.kind, edge.source, edge.target)
        for edge in reading.edges
        if edge.kind in ("invokes", "inherits")
    }
    assert found == expected


TEST_BODY = "def test_it():\n    pass\n"

TEST_FILE_ROWS = [
    pytest.param(
        "pkg/src/lib/pipeline/units.py",
        [],
        ["pkg/tests/pipeline/test_units.py"],
        ["pkg/tests/pipeline/test_units.py"],
        id="mirrored-folder-below-src-package",
    ),
    pytest.param(
        "pkg/src/lib/config.py",
        [],
        ["tests/test_config.py"],
        ["tests/test_config.py"],
        id="top-level-module-and-top-level-test",
    ),
    pytest.param(
        "pkg/src/lib/pipeline/units.py",
        [],
        ["pkg/tests/other/test_units.py"],
        [],
        id="same-name-in-another-folder",
    ),
    pytest.param(
        "app/orders.py",
        ["app/__init__.py"],
        ["tests/test_orders.py"],
        ["tests/test_orders.py"],
        id="flat-package",
    ),
    pytest.param(
        "pkg/src/lib/__init__.py",
        [],
        ["tests/test___init__.py"],
        [],
        id="init-module-has-none",
    ),
]


@pytest.mark.parametrize(("module", "others", "tests", "expected"), TEST_FILE_ROWS)
def test_each_module_is_given_the_test_files_that_mirror_it(
    tmp_path: Path, module: str, others: list[str], tests: list[str], expected: list[str]
) -> None:
    sources = {path: "VALUE = 1\n" for path in [module, *others]}

    reading = read_project(tmp_path, sources, {path: TEST_BODY for path in tests})

    assert list(facts_of(reading, module).tests) == expected
    assert {facts.path for facts in reading.files} == set(sources)


def test_a_file_that_does_not_parse_is_a_bare_file_node_and_a_problem(tmp_path: Path) -> None:
    broken = "def broken(:\n    pass\n"

    reading = read_project(tmp_path, {"bad.py": broken, "good.py": "def ok():\n    pass\n"})

    bad = facts_of(reading, "bad.py")
    assert bad.lines == len(broken.splitlines())
    assert bad.symbols == ()
    assert [symbol.name for symbol in facts_of(reading, "good.py").symbols] == ["ok"]
    assert any("bad.py" in problem for problem in reading.problems)
    assert not any("good.py" in problem for problem in reading.problems)
