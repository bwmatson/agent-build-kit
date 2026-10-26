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
