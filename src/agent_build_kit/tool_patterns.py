"""Claude Code `Bash(...)` tool patterns, matched without the protocol library.

The ACP runtime applies them to a read-only run, and config load and `abk doctor` judge the
commands a build agent is told it may run by them, so they live where nothing imports the
protocol library."""

import re

# Shell syntax that chains or redirects a command: a read-only pattern vouches
# for one command, so a line that strings another after it is not covered.
SHELL_OPERATORS = (";", "&", "|", "`", "$(", ">", "<", "\n")


def tokens(tool_list: str) -> list[str]:
    """The list's entries, `Name` or `Name(pattern)`, a pattern's own spaces
    kept."""
    return re.findall(r"[^\s(]+(?:\([^)]*\))?", tool_list)


def name_of(token: str) -> str:
    return token.split("(", 1)[0]


def command_patterns(tool_list: str) -> tuple[str, ...]:
    """The `Bash(...)` patterns a list grants; a bare `Bash` grants any."""
    return tuple(
        token[len("Bash(") : -1] if "(" in token else "*"
        for token in tokens(tool_list)
        if name_of(token) == "Bash"
    )


def matches(command: str, patterns: tuple[str, ...]) -> bool:
    """Claude Code's `Bash(...)` matching: `*` stands for anything and the
    pattern covers the whole line, which may not chain a second command."""
    line = command.strip()
    if any(operator in line for operator in SHELL_OPERATORS):
        return False
    return any(
        re.fullmatch(".*".join(re.escape(part) for part in pattern.split("*")), line, re.DOTALL)
        for pattern in patterns
    )


def allows(tool_list: str, command: str) -> bool:
    """Whether a Claude Code tool list (`--allowedTools` syntax) allows a shell
    command: some `Bash(...)` entry, or a bare `Bash`, matches the whole line, and
    the line chains no second command."""
    return matches(command, command_patterns(tool_list))
