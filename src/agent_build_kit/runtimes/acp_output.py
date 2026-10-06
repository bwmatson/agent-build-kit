"""What an ACP agent's tool call update means: the one place it is read.

A refusal is read from the update's status and a denial code its raw output
carries; the phrase list decides whenever there is no such code, since the
protocol does not say why a call failed and no agent is recorded sending one.
"""

import json
import re
from typing import Any

from acp.schema import TextContentBlock, ToolCallProgress

# The `rawOutput.error.code` values that say the agent's own policy refused the call.
DENIAL_CODES = frozenset({"permission_denied"})

# How an agent's own refusal of a command words it, anchored to where a line
# opens: a rule's verdict (`Blocked by the user-defined deny rule ...`,
# `BLOCKED: this command matches the user-defined deny rule ...`) or a
# permission verdict (`Permission to use Bash with command ... has been
# denied`), after at most a short wrapper of the agent's own (`terminal
# failed: `). Never a bare word and never mid-line, so a command that ran and
# failed for its own reasons — the shell's `ls: cannot open directory '/root':
# Permission denied`, a test named for "forbidden", a test's own `E
# AssertionError: Permission for guest was denied`, an HTTP 403 — is not taken
# for a refusal. These are the shapes this was written from; another agent's
# wording is not covered.
BLOCKED_OUTPUT = re.compile(
    r"^\s*(?:[A-Za-z ]{1,30} failed:\s*)?"
    r"(?:blocked(?: by\b|:)[^\n]*?\bdeny rule|permission (?:to|for)\b[^\n]*\bdenied\b)",
    re.IGNORECASE | re.MULTILINE,
)


def text_of(content: Any) -> str:
    """The text blocks of a tool call's content, joined."""
    parts: list[str] = []
    for item in content or []:
        block = getattr(item, "content", None)
        if isinstance(block, TextContentBlock):
            parts.append(block.text)
    return "\n".join(parts)


def output_of(update: ToolCallProgress) -> str:
    """What a tool call update says its command produced: its content's text,
    or failing that its raw output, whichever shape the agent sends."""
    text = text_of(update.content)
    raw = update.raw_output
    if not text and raw is not None:
        return raw if isinstance(raw, str) else json.dumps(raw, default=str)
    return text


def refusal_line(output: str) -> str | None:
    """The line of `output` that words a refusal, or None."""
    match = BLOCKED_OUTPUT.search(output)
    if match is None:
        return None
    return output[output.rfind("\n", 0, match.start()) + 1 :]


def denied_call(update: ToolCallProgress) -> bool:
    """Whether `update` reports a call the agent's own policy refused."""
    if update.status != "failed":
        return False
    raw = update.raw_output
    error = raw.get("error") if isinstance(raw, dict) else None
    if isinstance(error, dict) and error.get("code") in DENIAL_CODES:
        return True
    return refusal_line(output_of(update)) is not None
