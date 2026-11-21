"""The copy kept beside a file a command rewrites in place (`abk redact-history`,
`abk scrub-store`): one suffix, and the ignore pattern that covers it wherever it is."""

from __future__ import annotations

from pathlib import Path

COPY_SUFFIX = ".pre-redact"
COPY_PATTERN = "*" + COPY_SUFFIX


def copy_of(path: Path) -> Path:
    """Where the original of `path` is kept before it is rewritten."""
    return path.with_name(path.name + COPY_SUFFIX)
