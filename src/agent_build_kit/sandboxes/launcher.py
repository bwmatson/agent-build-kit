"""The program that confines itself and execs the step: `<policy file> -- <argv...>`.

It is run as a script (`python -S launcher.py ...`) and imports neither `argparse` nor `json`
nor the rest of the package, so it starts fast: the policy is a small `key=value` file.
"""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from collections.abc import Callable, Mapping, Sequence

# What the launcher hands the restriction step: the policy file's lists, as plain strings.
Restrict = Callable[[Mapping[str, list[str]]], None]

# The exit status when the sandbox could not be applied and the repo requires it.
EXIT_NOT_APPLIED = 97

# The policy file's list keys; `required` is a single value beside them.
LIST_KEYS = ("write", "read", "host")

_SYS_CREATE_RULESET = 444
_SYS_ADD_RULE = 445
_SYS_RESTRICT_SELF = 446
_PR_SET_NO_NEW_PRIVS = 38
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1

# Filesystem rights, by the ABI that introduced them.
_EXECUTE, _WRITE_FILE, _READ_FILE, _READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
_REFER, _TRUNCATE, _IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15
_ALL_ABI1 = (1 << 13) - 1
_FILE_RIGHTS = _EXECUTE | _WRITE_FILE | _READ_FILE
_READ_RIGHTS = _EXECUTE | _READ_FILE | _READ_DIR
# Device files can be written and read, never created or removed.
_DEVICE_FOLDER = "/dev"


class _PathBeneath(ctypes.Structure):
    _pack_ = 1
    _layout_ = "ms"  # with `_pack_ = 1` the same bytes as the kernel's packed struct
    _fields_ = (("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32))


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _call(libc: ctypes.CDLL, *args: object) -> int:
    result = libc.syscall(*args)
    if result < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return result


def _abi(libc: ctypes.CDLL) -> int:
    return _call(libc, _SYS_CREATE_RULESET, None, 0, _CREATE_RULESET_VERSION)


def _rights(abi: int) -> tuple[int, int, int]:
    """The rights the ruleset handles, those a file rule may carry, and those for a folder."""
    handled = _ALL_ABI1
    file_rights = _FILE_RIGHTS
    if abi >= 2:
        handled |= _REFER
    if abi >= 3:
        handled |= _TRUNCATE
        file_rights |= _TRUNCATE
    if abi >= 5:
        handled |= _IOCTL_DEV
        file_rights |= _IOCTL_DEV
    return handled, file_rights, handled


def apply_restrictions(lists: Mapping[str, list[str]], libc: ctypes.CDLL | None = None) -> None:
    """Restrict this process and everything it starts: writes only under `write`, reads (and
    runs) only under `read`. Raises `OSError` with the kernel's errno when it cannot."""
    libc = libc or _libc()
    abi = _abi(libc)
    handled, file_rights, folder_rights = _rights(abi)
    attr = ctypes.c_uint64(handled)
    ruleset = _call(libc, _SYS_CREATE_RULESET, ctypes.byref(attr), 8, 0)
    try:
        rules = [(path, folder_rights) for path in lists.get("write", [])]
        rules += [(path, _READ_RIGHTS & handled) for path in lists.get("read", [])]
        rules.append((_DEVICE_FOLDER, file_rights & ~_EXECUTE))
        for path, rights in rules:
            _add_rule(libc, ruleset, path, rights, file_rights)
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            number = ctypes.get_errno()
            raise OSError(number, os.strerror(number))
        _call(libc, _SYS_RESTRICT_SELF, ruleset, 0)
    finally:
        os.close(ruleset)


def _add_rule(libc: ctypes.CDLL, ruleset: int, path: str, rights: int, file_rights: int) -> None:
    try:
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except OSError:
        return  # a path that does not exist grants nothing
    try:
        if not os.path.isdir(path):
            rights &= file_rights
        beneath = _PathBeneath(rights, fd)
        _call(libc, _SYS_ADD_RULE, ruleset, _RULE_PATH_BENEATH, ctypes.byref(beneath), 0)
    finally:
        os.close(fd)


def _read_policy(path: str) -> tuple[str, dict[str, list[str]]]:
    required = "files"
    lists: dict[str, list[str]] = {key: [] for key in LIST_KEYS}
    with open(path) as handle:
        text = handle.read()
    # Read once, then gone: a sibling step that can write the temp folder cannot rewrite it.
    try:
        os.unlink(path)
    except OSError:
        pass
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key == "required":
            required = value
        elif key in lists:
            lists[key].append(value)
    return required, lists


def _cause(number: int) -> str:
    if number == errno.ENOSYS:
        return "this kernel has no Landlock (it needs Linux 5.13 or later built with it)"
    if number == errno.EOPNOTSUPP:
        return "Landlock is disabled at boot on this kernel (enable it in the `lsm=` boot list)"
    return f"Landlock refused the restrictions: {os.strerror(number)}"


def main(
    args: Sequence[str],
    *,
    restrict: Restrict | None = None,
    execvp: Callable[[str, list[str]], object] = os.execvp,
) -> None:
    separator = list(args).index("--")
    required, lists = _read_policy(args[0])
    argv = list(args[separator + 1 :])
    try:
        (restrict or apply_restrictions)(lists)
    except OSError as failure:
        cause = _cause(failure.errno or 0)
        if required != "none":
            sys.stderr.write(f"sandbox could not start: {cause}\n")
            raise SystemExit(EXIT_NOT_APPLIED) from None
        sys.stderr.write(f"sandbox not in force, running unconfined: {cause}\n")
    execvp(argv[0], argv)


if __name__ == "__main__":
    main(sys.argv[1:])
