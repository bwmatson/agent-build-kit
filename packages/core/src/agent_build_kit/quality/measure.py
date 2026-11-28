"""The measures of a Python source: per function its lines, parameters, nesting, cognitive
complexity and boolean operators, and per file its lines."""

from agent_build_kit.model import Frozen


class MeasureError(Exception):
    """A source that cannot be measured; the message names the file."""


class FunctionMeasure(Frozen):
    """One function: where it sits and the five measures the bars are set on."""

    name: str
    first_line: int
    def_line: int
    last_line: int
    lines: int
    parameters: int
    nesting: int
    cognitive_complexity: int
    boolean_operators: int


class SourceMeasure(Frozen):
    """One file: its physical lines and every function in it."""

    lines: int
    functions: tuple[FunctionMeasure, ...]


def measure_source(source: str, path: str) -> SourceMeasure:
    """Measure `source`, the text of the file `path`; raise `MeasureError` naming `path` when it
    does not parse."""
    raise NotImplementedError
