"""The strict guard against an old test-kind spelling.

`old_spelling_problems` returns one `path:line` message per line of a source, test, web or
document file under `root` that carries an old spelling, and one message per file named for one.
The compatibility module, the rename tool and the tests of both, the two documents that explain
the rename and the changelog are exempt.
"""

from __future__ import annotations

from pathlib import Path


def old_spelling_problems(root: Path) -> list[str]:
    raise NotImplementedError
