"""The measures of a Python source: lines, parameters, nesting, cognitive complexity and boolean
operators of each function, and the lines of the file."""

from textwrap import dedent

import pytest

from agent_build_kit.quality.measure import MeasureError, measure_source

PATH = "pkg/module.py"

# (source, qualified function name, measure, expected value), one row per rule of the design.
MEASURES = [
    # lines: from the `def` line to the last line, decorators out, docstring and blanks in
    (
        '@decorator\ndef f(a):\n    """Doc."""\n\n    x = 1\n    return x\n',
        "f",
        "lines",
        5,
    ),
    (
        "def outer():\n    x = 1\n    def inner():\n        a = 1\n        b = 2\n"
        "        return a\n    return x\n",
        "outer",
        "lines",
        3,
    ),
    (
        "def outer():\n    x = 1\n    def inner():\n        a = 1\n        b = 2\n"
        "        return a\n    return x\n",
        "outer.inner",
        "lines",
        4,
    ),
    # parameters
    ("class C:\n    def m(self, a, b):\n        pass\n", "C.m", "parameters", 2),
    (
        "class C:\n    @classmethod\n    def m(cls, a):\n        pass\n",
        "C.m",
        "parameters",
        1,
    ),
    ("def f(self, a):\n    pass\n", "f", "parameters", 2),
    ("def f(a, *args, **kwargs):\n    pass\n", "f", "parameters", 3),
    ("def f(a, *, b, c):\n    pass\n", "f", "parameters", 3),
    ("def f(a, /, b):\n    pass\n", "f", "parameters", 2),
    # nesting
    ("def f():\n    x = 1\n    return x\n", "f", "nesting", 0),
    (
        "def f(a, b):\n    if a:\n        x = 1\n    elif b:\n        x = 2\n    else:\n"
        "        x = 3\n",
        "f",
        "nesting",
        1,
    ),
    (
        "def f():\n    with a:\n        try:\n            x = 1\n        except E:\n"
        "            y = 2\n",
        "f",
        "nesting",
        2,
    ),
    (
        "def outer(x):\n    y = 1\n    def inner():\n        if x:\n            if x:\n"
        "                return 1\n",
        "outer",
        "nesting",
        0,
    ),
    (
        "def outer(x):\n    y = 1\n    def inner():\n        if x:\n            if x:\n"
        "                return 1\n",
        "outer.inner",
        "nesting",
        2,
    ),
    # cognitive complexity
    (
        "def f(a, b):\n    if a:\n        return 1\n    elif b:\n        return 2\n"
        "    else:\n        return 3\n",
        "f",
        "cognitive_complexity",
        3,
    ),
    (
        "def f(a, xs):\n    if a:\n        for x in xs:\n            print(x)\n",
        "f",
        "cognitive_complexity",
        3,
    ),
    (
        "def f(xs):\n    for x in xs:\n        pass\n    else:\n        pass\n",
        "f",
        "cognitive_complexity",
        2,
    ),
    (
        "def f():\n    try:\n        g()\n    except E:\n        pass\n",
        "f",
        "cognitive_complexity",
        1,
    ),
    ("def f(a, b, c):\n    return a if b else c\n", "f", "cognitive_complexity", 1),
    ("def f(a, b, c):\n    return a and b or c\n", "f", "cognitive_complexity", 2),
    ("def f(xs):\n    return [x for x in xs if x]\n", "f", "cognitive_complexity", 1),
    (
        "def f(x):\n    match x:\n        case 1:\n            return 1\n"
        "        case _:\n            return 2\n",
        "f",
        "cognitive_complexity",
        1,
    ),
    (
        "def f(xs):\n    return sorted(xs, key=lambda x: x if x else 0)\n",
        "f",
        "cognitive_complexity",
        2,
    ),
    # boolean operators
    ("def f(a, b, c):\n    return a and b and c\n", "f", "boolean_operators", 2),
    ("def f(a, b, c):\n    return a and (b or c)\n", "f", "boolean_operators", 2),
    ("def f(a, b):\n    return not (a or b)\n", "f", "boolean_operators", 1),
    (
        "def f(a, b, c, d, e):\n    if a and b:\n        pass\n    if c and d and e:\n"
        "        pass\n",
        "f",
        "boolean_operators",
        2,
    ),
    ("def f(a):\n    return a\n", "f", "boolean_operators", 0),
]

REDEFINED = "def f():\n    return 1\n\n\ndef f():\n    return 2\n\n\ndef f():\n    return 3\n"
NESTED = "class Outer:\n    def method(self):\n        def inner():\n            pass\n"


@pytest.mark.parametrize(("source", "name", "measure", "expected"), MEASURES)
def test_a_function_is_measured_by_the_rule_of_each_measure(
    source: str, name: str, measure: str, expected: int
) -> None:
    by_name = {function.name: function for function in measure_source(source, PATH).functions}

    assert getattr(by_name[name], measure) == expected


@pytest.mark.parametrize(
    ("source", "names"),
    [
        (NESTED, ["Outer.method", "Outer.method.inner"]),
        (REDEFINED, ["f", "f#2", "f#3"]),
    ],
)
def test_a_function_is_named_by_its_enclosing_classes_and_functions(
    source: str, names: list[str]
) -> None:
    measured = measure_source(source, PATH)

    assert sorted(function.name for function in measured.functions) == sorted(names)


def test_a_function_reports_its_first_decorator_line_its_def_line_and_its_last_line() -> None:
    source = dedent(
        """\
        x = 1


        @one
        @two
        def f():
            return 1
        """
    )

    (function,) = measure_source(source, PATH).functions

    assert (function.first_line, function.def_line, function.last_line) == (4, 6, 7)


def test_a_file_is_measured_in_physical_lines() -> None:
    assert measure_source("a = 1\n\nb = 2\n", PATH).lines == 3


def test_a_source_that_does_not_parse_raises_an_error_naming_the_file() -> None:
    with pytest.raises(MeasureError) as refused:
        measure_source("def broken(:\n", PATH)

    assert PATH in str(refused.value)
