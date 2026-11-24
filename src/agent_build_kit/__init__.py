"""agent-build-kit: a spec-driven, unattended build pipeline for Claude Code."""

import os
from pkgutil import extend_path

# The core, the worker and the orchestrator packages install into this namespace
# (docs/designs/orchestration.md).
__path__ = extend_path(__path__, __name__)

# In a source checkout the packages' trees sit beside this one, whether or not they are installed.
for _package in ("core", "worker", "orchestrator"):
    _tree = os.path.normpath(f"{__path__[0]}/../../packages/{_package}/src/{__name__}")
    if os.path.isdir(_tree) and _tree not in __path__:
        __path__.append(_tree)

__version__ = "0.1.0"
