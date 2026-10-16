"""The providers a split's gate may name.

The one module where a provider is named; the tier 2 mechanism names none.
"""

from __future__ import annotations

PROVIDERS = ("modal",)


def names() -> list[str]:
    return sorted(PROVIDERS)
