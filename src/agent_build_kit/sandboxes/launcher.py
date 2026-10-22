"""The program that confines itself and execs the step: `<policy file> -- <argv...>`.

It imports neither `argparse` nor `json` nor the rest of the package, so it starts fast.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence

# What the launcher hands the restriction step: the policy file's lists, as plain strings.
Restrict = Callable[[Mapping[str, list[str]]], None]

# The exit status when the sandbox could not be applied and the repo requires it.
EXIT_NOT_APPLIED = 97


def main(
    args: Sequence[str],
    *,
    restrict: Restrict | None = None,
    execvp: Callable[[str, list[str]], object] = os.execvp,
) -> None:
    raise NotImplementedError
