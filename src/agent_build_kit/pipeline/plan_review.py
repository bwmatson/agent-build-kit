"""A model reads a change's plan before its first unit starts; a finding holds the change.

The four questions the model is asked are `QUESTIONS`, in order: a finding names its question
by the number (from 1) of the one it answers.
"""

from __future__ import annotations

# The fixed questions every review asks, in the order a finding numbers them.
QUESTIONS: tuple[str, ...] = ()
