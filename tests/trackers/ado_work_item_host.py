"""Azure DevOps work items at the HTTP boundary: a stand-in answering the REST calls.

What it receives is the request the transport sends (JSON Patch bodies to
`wit/workitems/$<type>`, `wit/wiql` queries); what it sends back is the document the
service sends. A route it does not know fails the test. It keeps the items it creates, the
forward link on a parent for each child made under it, and a record of every request.
"""

from __future__ import annotations

from typing import Any

import httpx

from agent_build_kit.model import Frozen
from tests.forges.azure_rest_host import Seen


class CreateRequest(Frozen):
    """One create call: the type in the route, the body's `add` operations by field path."""

    type: str
    content_type: str
    fields: dict[str, Any]
    relations: list[dict[str, Any]]


class WorkItemHost(httpx.MockTransport):
    creates: list[CreateRequest]
    seen: list[Seen]

    def __init__(self, *, lose_create_answer: bool = False) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500."""
        raise NotImplementedError

    def seed(self, type: str, title: str, *, parent: str | None = None) -> str:
        """An item that already exists on the board, as a person made it; its id."""
        raise NotImplementedError

    def calls(self, method: str | None = None, route: str | None = None) -> list[Seen]:
        raise NotImplementedError
