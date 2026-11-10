"""A program named `node` for the tests of the node profile, which the profile's script probe
(`node -e ... <script>`) runs. It answers the probe from the `package.json` in its folder, as
the real one does, and starts nothing else: a real `node` may be a toolchain manager's shim
that looks for a toolchain the suite's empty home does not have and goes to the network."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

# With `NODE_STAND_IN_LOG` set, each call is appended to that file as its name and then its
# arguments, one per line, the way the other stand-ins record theirs.
NODE_STAND_IN = f"""\
#!{sys.executable}
import json
import os
import sys

args = sys.argv[1:]
log = os.environ.get("NODE_STAND_IN_LOG")
if log:
    with open(log, "a") as out:
        out.write("\\n".join(["node", *args]) + "\\n")
if args[:1] == ["-e"]:
    try:
        with open("package.json") as manifest:
            scripts = json.load(manifest).get("scripts") or {{}}
    except (OSError, ValueError):
        sys.exit(1)
    sys.exit(0 if isinstance(scripts.get(args[-1]), str) else 1)
"""


def install_node_stand_in(bin_dir: Path) -> Path:
    """The stand-in `node` in `bin_dir`, which is made if it is not there."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    program = bin_dir / "node"
    program.write_text(NODE_STAND_IN)
    program.chmod(program.stat().st_mode | stat.S_IEXEC)
    return program
