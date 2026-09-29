"""Every Azure DevOps call the pipeline makes, in one place.

The twin of `shell.gh`, and for the same reason: there must be no second way
to call `az`, so a new call site cannot forget what this one remembers.

Three rules, each of them a failure that has to be prevented rather than
detected:

- **Every call names its organisation.** `az devops configure --defaults` is
  global CLI state, and units run concurrently — one repo's default would
  answer another repo's call, which is the one-active-account failure
  `shell.py` was written to prevent.
- **The token travels in the environment.** `ps` shows every argument of every
  running process, and the pipeline runs unattended for hours. Unset, calls
  fall back to the `az` sign-in session; both have to work.
- **An answer that is not JSON is an error.** Azure DevOps answers an
  unauthenticated request with a sign-in page and a 2xx. Parsed leniently that
  is `{}`, which reads as "no pull requests": the poller's failure counter
  never trips and the pipeline goes quiet with a clean log.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable

from agent_build_kit.settings import settings

Run = Callable[..., subprocess.CompletedProcess]


class AzError(RuntimeError):
    """An `az` call that did not answer. Never a quiet empty result."""


def org_url(account: str) -> str:
    """The organisation URL every call carries, from the account name."""
    return f"https://dev.azure.com/{account}"


def env() -> dict[str, str]:
    """The environment an `az` call runs in.

    The whole environment, not just the token: `az` needs PATH and HOME, and a
    partial env is the kind of thing that works until it runs under systemd.
    """
    if not settings.ado_pat:
        return dict(os.environ)
    return {**os.environ, "AZURE_DEVOPS_EXT_PAT": settings.ado_pat}


def call(args: list[str], *, org: str, run: Run | None = None) -> subprocess.CompletedProcess:
    """One `az` call, with its organisation and environment, raising nothing."""
    execute = run or subprocess.run
    return execute(
        ["az", *args, "--org", org, "--output", "json"],
        capture_output=True,
        text=True,
        check=False,
        env=env(),
    )


def json_out(args: list[str], *, org: str, run: Run | None = None) -> object:
    """The JSON an `az` call answered with, or None when it printed nothing.

    Raises `AzError` when the call failed or answered with something that is
    not JSON — see the third rule above.
    """
    result = call(args, org=org, run=run)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise AzError(f"az {' '.join(args)}: {detail}")
    text = (result.stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        raise AzError(
            f"az {' '.join(args)}: answered with something that is not JSON "
            f"(a sign-in page means the call was not authenticated): {text[:120]}"
        ) from None
