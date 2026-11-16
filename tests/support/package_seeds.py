"""Test support: the seeds the package-boundary scan assigns modules from, and its baseline.

Seeds are dotted module names relative to `agent_build_kit` (a module or a package). The baseline
is the set of `(importer, imported)` module pairs that cross a package boundary today; it may
only shrink.
"""

from agent_build_kit.model import Frozen


class Seeds(Frozen):
    core: frozenset[str]
    worker: frozenset[str]
    orchestrator: frozenset[str]


def seeds() -> Seeds:
    """The seeds from the design of `worker-stops-importing-the-orchestrator`."""
    raise NotImplementedError


def baseline() -> frozenset[tuple[str, str]]:
    """The imports that cross a boundary today, as `(importer, imported)` module names."""
    raise NotImplementedError
