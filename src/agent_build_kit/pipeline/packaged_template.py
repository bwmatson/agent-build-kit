"""Reading a packaged prompt text from the `templates/` folder."""

from __future__ import annotations

from importlib import resources


def packaged_template(name: str) -> str:
    """The text of the packaged template file `name`, without leading or trailing whitespace."""
    return resources.files("agent_build_kit").joinpath("templates", name).read_text().strip()
