"""The `repos.<name>.tracker` section: kind-specific models and their validation."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from agent_build_kit import config
from agent_build_kit.model import Frozen
from agent_build_kit.trackers.base import ItemKind

# The only shape a credential may take in abk.yaml: the name of an environment variable.
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")

OFF_KIND = "none"

# The kit entities a board can hold, outermost first.
LEVEL_ORDER = ("change", "group", "task")
_PR_LINK_WORDS = ("lowest", "all")


class TrackerConfigError(Exception):
    """A tracker section that is present and incomplete or invalid, scoped to one repo."""


class TrackerSection(Frozen):
    """A validated `tracker` section; the kind says which target fields it carries."""

    kind: str
    # The environment variable holding the credential, by name only.
    token_env: str | None = None
    # The tracker's own state names, by the kit's.
    state_map: dict[str, str] = {}
    marker_prefix: str = "abk"
    # The kit entities that become board items, outermost first.
    levels: tuple[str, ...] = ("change", "group")
    # Whether a person-made top item may sit above the first level.
    epic: bool = False
    # Which levels get a merged unit's pull request: `lowest`, `all` or a list of entities.
    pr_links: str | tuple[str, ...] = "lowest"
    # The board type of each level in use, and of the epic.
    types: dict[str, str] = {}

    @field_validator("levels")
    @classmethod
    def _ordered_subset(cls, levels: tuple[str, ...]) -> tuple[str, ...]:
        if not levels:
            raise ValueError("at least one level is required")
        last = -1
        for entry in levels:
            if entry not in LEVEL_ORDER:
                raise ValueError(f"level {entry!r} is unknown (known: {', '.join(LEVEL_ORDER)})")
            position = LEVEL_ORDER.index(entry)
            if position <= last:
                raise ValueError(
                    f"level {entry!r} is repeated or out of order "
                    f"(the order is {', '.join(LEVEL_ORDER)})"
                )
            last = position
        return levels

    @model_validator(mode="after")
    def _levels_are_typed_and_links_are_in_use(self) -> Self:
        wanted = [*self.levels, *(["epic"] if self.epic else [])]
        missing = [level for level in wanted if not self.types.get(level)]
        if missing:
            raise ValueError(f"types: needs a non-empty type for {', '.join(missing)}")
        if isinstance(self.pr_links, str):
            if self.pr_links not in _PR_LINK_WORDS:
                raise ValueError("pr_links: must be lowest, all or a list of levels")
        else:
            outside = [entity for entity in self.pr_links if entity not in self.levels]
            if outside:
                raise ValueError(f"pr_links: {', '.join(outside)} is not in levels")
        return self

    @field_validator("token_env")
    @classmethod
    def _name_only(cls, value: str | None) -> str | None:
        if value is not None and not _ENV_NAME.fullmatch(value):
            raise ValueError("must be the name of an environment variable, never a credential")
        return value

    @property
    def target(self) -> str:
        """Where the tracker is, for a person reading a report."""
        return self.kind

    @property
    def level_types(self) -> dict[str, str]:
        """The board type of each level in use, and of the epic when `types` names one."""
        return {
            level: kind
            for level, kind in self.types.items()
            if level in self.levels or level == "epic"
        }

    def parent_level(self, level: str) -> str | None:
        """The level an item of this level hangs under: the previous level in use, `epic` for
        the first when an epic is set, None for the first otherwise."""
        position = self.levels.index(level)
        if position:
            return self.levels[position - 1]
        return "epic" if self.epic else None


class AzureDevOpsTracker(TrackerSection):
    kind: Literal["azure_devops"]
    organization: str = Field(min_length=1)
    project: str = Field(min_length=1)
    team: str = Field(min_length=1)
    area_path: str = Field(min_length=1)
    iteration_path: str = Field(min_length=1)
    # The old setting: the type of the group level when `types` does not name one.
    story_type: str | None = Field(default=None, min_length=1)
    # The states whose board names differ for a type, by type.
    states_by_type: dict[str, dict[str, str]] = {}

    @property
    def level_types(self) -> dict[str, str]:
        """The work item type of each level in use; `types` wins over `story_type`."""
        types = {**({"group": self.story_type} if self.story_type else {}), **self.types}
        return {
            level: kind for level, kind in types.items() if level in self.levels or level == "epic"
        }

    @property
    def target(self) -> str:
        return f"{self.kind} {self.organization}/{self.project}"


class GithubTracker(TrackerSection):
    kind: Literal["github"]
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    # The label that stands for each logical kind.
    labels: dict[ItemKind, str] | None = None
    host: str | None = None
    project_number: int | None = None

    @property
    def target(self) -> str:
        return f"{self.kind} {self.owner}/{self.repo}"

    @field_validator("labels")
    @classmethod
    def _every_kind_has_a_label(
        cls, labels: dict[ItemKind, str] | None
    ) -> dict[ItemKind, str] | None:
        if labels is None:
            return labels
        missing = [kind for kind in get_args(ItemKind) if not labels.get(kind)]
        if missing:
            raise ValueError(f"needs a non-empty label for {', '.join(missing)}")
        return labels


_SECTIONS: TypeAdapter[AzureDevOpsTracker | GithubTracker] = TypeAdapter(
    Annotated[AzureDevOpsTracker | GithubTracker, Field(discriminator="kind")]
)
_KINDS = tuple(
    kind
    for model in (AzureDevOpsTracker, GithubTracker)
    for kind in get_args(model.model_fields["kind"].annotation)
)


# The old labels, by the level each one stood for.
_OLD_LABELS = {"change": "feature", "group": "story", "task": "task"}

# What each kind's block holds, and the old flat keys that only that kind had.
_BLOCK_KEYS = {
    "azure_devops": ("organization", "project", "team", "area_path", "iteration_path"),
    "github": ("owner", "repo", "host", "project_number"),
}
_OLD_ONLY_KEYS = {"azure_devops": ("story_type",), "github": ("labels",)}


def _expand(raw: dict[str, Any], repo: str, kind: str) -> dict[str, Any]:
    """The flat shape the models validate: a provider block is merged up, and the old keys
    are read as the three levels they always meant. Refuses a mix, naming both."""

    def refuse(problem: str) -> TrackerConfigError:
        return TrackerConfigError(f"repo {repo!r}: tracker ({kind}): {problem}")

    for other in _BLOCK_KEYS:
        if other != kind and other in raw:
            raise refuse(f"{other}: the block of another provider")
    if kind not in raw:
        old = {**raw}
        if kind == "azure_devops":
            types = {"change": "Feature", "group": old.get("story_type"), "task": "Task"}
        else:
            labels = old.get("labels") or {}
            types = {level: labels.get(name) for level, name in _OLD_LABELS.items()}
        old.setdefault("levels", list(LEVEL_ORDER))
        old["types"] = {**{k: v for k, v in types.items() if v}, **old.get("types", {})}
        return old
    block = raw[kind]
    if not isinstance(block, dict):
        raise refuse(f"{kind}: must be a mapping")
    flat_old = [
        key
        for key in (*_BLOCK_KEYS[kind], *_OLD_ONLY_KEYS[kind], "state_map", "types")
        if key in raw
    ]
    if flat_old:
        raise refuse(
            f"{', '.join(flat_old)}: old keys that cannot be combined with the {kind} block"
        )
    flat = {key: value for key, value in raw.items() if key != kind}
    states = block.get("states")
    return {
        **flat,
        **{key: value for key, value in block.items() if key != "states"},
        **({"state_map": states} if states is not None else {}),
    }


def section_for(repo: str) -> TrackerSection | None:
    """The validated section of a repo in the active workspace; None when off.

    Raises TrackerConfigError naming the repo, the kind and the key when the section is
    present and incomplete or invalid. A value is never echoed.
    """
    raw = config.active().repos[repo].tracker
    if raw is None or raw.get("kind") == OFF_KIND:
        return None
    kind = raw.get("kind")
    if kind is None:
        raise TrackerConfigError(
            f"repo {repo!r}: tracker: kind is required (one of {', '.join(_KINDS)}, none)"
        )
    if kind not in _KINDS:
        raise TrackerConfigError(
            f"repo {repo!r}: tracker kind {kind!r} is unknown (known: {', '.join(_KINDS)}, none)"
        )
    try:
        return _SECTIONS.validate_python(_expand(raw, repo, kind))
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in found['loc'][1:]) or 'section'}: {found['msg']}"
            for found in error.errors(include_input=False)
        )
        raise TrackerConfigError(f"repo {repo!r}: tracker ({kind}): {problems}") from None
