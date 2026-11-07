"""The catalogue's cost does not grow with the files that cannot hold an instrument
(spec: test-determinism, the package catalogue test does not depend on machine load)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_build_kit.serve.metrics import Instrument, catalogue


def test_a_file_that_names_no_instrument_is_not_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "site.py").write_text(
        'def site(log):\n    emit_metric("count", "abk.real", 1, log)\n'
    )
    for i in range(5):
        (tmp_path / f"plain_{i}.py").write_text(f"def plain_{i}():\n    return {i}\n")
    parsed: list[str] = []
    real_parse = ast.parse

    def counting_parse(source: str, *args: object, **kwargs: object) -> ast.Module:
        parsed.append(source)
        return real_parse(source, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(ast, "parse", counting_parse)

    listed = catalogue(tmp_path)

    assert listed == [Instrument(name="abk.real", type="counter", attributes=())]
    assert len(parsed) == 1, f"parsed {len(parsed)} files, only site.py can hold an instrument"


def test_one_read_of_a_deeply_nested_file_reaches_each_node_at_most_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    depth = 30
    lines = ['def f0(r):\n    labels = {"repo": r}\n']
    for i in range(1, depth):
        lines.append(f"{'    ' * i}def f{i}():\n")
    call = 'telemetry.count("abk.deep", 1, **labels, kind="k")'
    lines.append(f"{'    ' * depth}{call}\n")
    source = "".join(lines)
    (tmp_path / "site.py").write_text(source)
    nodes = sum(1 for _ in ast.walk(ast.parse(source)))
    visits = 0
    real_iter_fields = ast.iter_fields

    def counting_iter_fields(node: ast.AST) -> object:
        nonlocal visits
        visits += 1
        return real_iter_fields(node)

    monkeypatch.setattr(ast, "iter_fields", counting_iter_fields)

    listed = catalogue(tmp_path)

    assert nodes <= visits <= 2 * nodes, f"{visits} iter_fields calls for {nodes} nodes"
    assert listed == [Instrument(name="abk.deep", type="counter", attributes=("repo", "kind"))]
