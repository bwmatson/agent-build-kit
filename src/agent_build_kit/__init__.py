"""agent-build-kit: a spec-driven, unattended build pipeline for Claude Code."""

import os
from pkgutil import extend_path

# The worker package installs into this namespace (docs/designs/orchestration.md).
__path__ = extend_path(__path__, __name__)

# In a source checkout the worker's tree sits beside this one, whether or not it is installed.
_worker_tree = f"{__path__[0]}/../../packages/worker/src/{__name__}"
if os.path.isdir(_worker_tree) and os.path.normpath(_worker_tree) not in __path__:
    __path__.append(os.path.normpath(_worker_tree))

__version__ = "0.1.0"
