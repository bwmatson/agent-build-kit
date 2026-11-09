"""Looks up a local implementation, then prints the Azure modules that were imported.

Run as a file with `python -I <this file> <planning root>`.
"""

import sys
from pathlib import Path

from agent_build_kit import orchestration
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
installation = Installation(WorkspaceConfig.model_validate(dict(repos=dict())), root)
orchestration.register("store", "local", lambda inst: "local")
assert orchestration.get("store", installation) == "local"
print(sorted(m for m in sys.modules if m.split(".")[0] == "azure"))
