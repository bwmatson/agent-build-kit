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

import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from agent_build_kit.settings import settings

Run = Callable[..., subprocess.CompletedProcess]
OpenUrl = Callable[..., object]

# Azure DevOps' own application id, for `az account get-access-token`.
_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"

# Long enough for a slow answer, short enough that a wedged call does not hold
# a tick open.
_TIMEOUT = 30


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
    # `az` is a Python program, and on a Windows host it otherwise writes its
    # JSON in the console's code page: one em-dash in a review comment then
    # arrives as a byte no UTF-8 decoder accepts, and the poll dies on what a
    # reviewer happened to type.
    base = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if settings.ado_pat:
        return {**base, "AZURE_DEVOPS_EXT_PAT": settings.ado_pat}
    # An exported but empty variable is not a credential, and passed on it
    # makes `az` attempt PAT authentication with an empty token rather than
    # falling back to the sign-in session.
    base.pop("AZURE_DEVOPS_EXT_PAT", None)
    return base


def call(args: list[str], *, org: str, run: Run | None = None) -> subprocess.CompletedProcess:
    """One `az` call, with its organisation and environment, raising nothing."""
    execute = run or subprocess.run
    return execute(
        ["az", *args, "--org", org, "--output", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        # Never let one undecodable byte end a poll: what a reviewer typed is
        # data, and the worst it may cost is that character.
        errors="replace",
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


@contextmanager
def body_file(payload: object) -> Iterator[str]:
    """A request body as a file, because that is the only way to send one.

    `az devops invoke` takes a body through `--in-file` and has no inline
    form, so a REST call that carries one writes it out and removes it again.
    """
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    try:
        json.dump(payload, handle)
        handle.close()
        yield handle.name
    finally:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)


def rest(
    method: str,
    url: str,
    *,
    payload: object = None,
    run: Run | None = None,
    open_url: OpenUrl | None = None,
) -> object:
    """A REST call `az devops invoke` cannot make.

    It exists for one reason: `invoke` resolves `git/pullRequests` to the
    organisation-level location, which answers GET and refuses PATCH — so
    retargeting a pull request, which has no CLI command either, is
    unreachable through the CLI at all.

    Authenticated the same two ways as everything else here, and kept in this
    module for the same reason: there must be no second place that knows how
    to authenticate, or a new call site will invent one.
    """
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", _authorization(run))
    opener = open_url or urllib.request.urlopen
    try:
        with opener(request, timeout=_TIMEOUT) as answer:  # type: ignore[union-attr]
            text = answer.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as error:
        raise AzError(f"{method} {url}: {error.code} {error.reason}") from None
    except OSError as error:
        raise AzError(f"{method} {url}: {error}") from None
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        raise AzError(
            f"{method} {url}: answered with something that is not JSON "
            f"(a sign-in page means the call was not authenticated): {text[:120]}"
        ) from None


def _authorization(run: Run | None = None) -> str:
    """A PAT as the password of an empty user, or the `az` session's token."""
    if settings.ado_pat:
        return "Basic " + base64.b64encode(f":{settings.ado_pat}".encode()).decode()
    execute = run or subprocess.run
    result = execute(
        ["az", "account", "get-access-token", "--resource", _RESOURCE,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env(),
    )  # fmt: skip
    token = (result.stdout or "").strip()
    if result.returncode or not token:
        raise AzError("no Azure DevOps credential: set AZURE_DEVOPS_EXT_PAT, or run `az login`")
    return f"Bearer {token}"
