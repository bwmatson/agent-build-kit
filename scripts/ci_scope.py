"""Say whether a CI run's changed paths include anything outside the planning paths.

Usage: ci_scope.py BASE HEAD, run in the repository. Prints `code=true` or
`code=false`, the line the workflow appends to its step output.
"""

from __future__ import annotations


def main(argv: list[str]) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv[1:]))
