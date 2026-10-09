"""What a test that runs `abk` as a process needs to fake GitHub: the fake host
(`FakeGitHub`) reached through `ABK_GITHUB_API_URL`, and the one command still
faked as a script, `gh auth token`, which is where the credential comes from.

Any other `gh` call fails loudly, so a forge that falls back to the command
shows up as a failure and not as a quiet pass.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.forges.github_server import FakeGitHub

_GH = """#!/bin/sh
echo "$@" >> "$GH_CALLS"
if [ "$1 $2" = "auth token" ]; then echo '{token}'; exit 0; fi
echo "gh $*: the fake host answers the API; only 'gh auth token' is a script" >&2
exit 1
"""


def process_env(server: FakeGitHub, bin_dir: Path, calls: Path) -> dict[str, str]:
    """The environment for `abk` as a process: `gh` on `PATH` printing the
    server's token, the API address set to the server, and no token variable
    that would be used in place of the command."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(_GH.format(token=server.token))
    gh.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "ABK_GH_TOKEN")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["GH_CALLS"] = str(calls)
    env["ABK_GITHUB_API_URL"] = server.url
    return env
