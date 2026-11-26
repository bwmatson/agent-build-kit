"""Test support: the modules the package table assigns to the worker.

The guard against framework code naming an ecosystem is an entry of the table in
`tests/exclusions.py`, with its token list, allowlist and own-tooling list.
"""

from __future__ import annotations

# The modules the package table assigns to the worker, as paths under a source tree; a test of the
# package boundaries asserts the list equals what the seeds assign.
WORKER_MODULES = (
    "graph/build.py",
    "graph/check_loop.py",
    "graph/nodes.py",
    "graph/run.py",
    "graph/state.py",
    "graph/unit.py",
    "pipeline/resolution_lane.py",
    "pipeline/verify.py",
    "cli/worker.py",
    "worker_run.py",
)
