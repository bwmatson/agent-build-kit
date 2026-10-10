"""The cards the units call for."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.model import Frozen
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline.unit_store import StoredUnit


class Card(Frozen):
    id: str
    kind: CardKind
    title: str
    body: str
    link: str


def desired_cards(units: Sequence[StoredUnit]) -> list[Card]:
    raise NotImplementedError
