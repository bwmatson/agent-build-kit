"""The `repos.<name>.tracker` section: kind-specific models and their validation."""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from agent_build_kit import config
from agent_build_kit.model import Frozen
from agent_build_kit.trackers.base import ItemKind

# The only shape a credential may take in abk.yaml: the name of an environment variable.
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")

OFF_KIND = "none"

logger = logging.getLogger(__name__)

# The kit entities a board can hold, outermost first.
LEVEL_ORDER = ("change", "group", "task")
_PR_LINK_WORDS = ("lowest", "all")
# The level each protocol kind stands for.
KIND_LEVELS: dict[ItemKind, str] = {"feature": "change", "story": "group", "task": "task"}


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
        types = self.level_types
        missing = [level for level in wanted if not types.get(level)]
        if missing:
            raise ValueError(f"types: needs a non-empty type for {', '.join(missing)}")
        shared = [
            level
            for position, level in enumerate(self.levels)
            if types[level] in [types[earlier] for earlier in self.levels[:position]]
        ]
        if shared:
            raise ValueError(f"types: {', '.join(shared)} shares its type with a level above it")
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
        """The board type of each level in use, and of the epic when it is named."""
        return {
            level: kind
            for level, kind in self._declared_types().items()
            if level in self.levels or level == "epic"
        }

    def _declared_types(self) -> dict[str, str]:
        """Every type the section names, before it is narrowed to the levels in use."""
        return self.types

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

    def _declared_types(self) -> dict[str, str]:
        """`types` wins over `story_type`, which is the group level's type when it names none."""
        return {**({"group": self.story_type} if self.story_type else {}), **self.types}

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
# The protocol kind each level stood for, for reading an old section's labels.
_LABEL_KINDS = {level: kind for kind, level in KIND_LEVELS.items()}
_KINDS = tuple(
    kind
    for model in (AzureDevOpsTracker, GithubTracker)
    for kind in get_args(model.model_fields["kind"].annotation)
)


_MODELS: dict[str, type[AzureDevOpsTracker | GithubTracker]] = {
    "azure_devops": AzureDevOpsTracker,
    "github": GithubTracker,
}
# The old flat keys that name a type, which a block's `types` replaces.
_OLD_ONLY_KEYS = {"azure_devops": ("story_type",), "github": ("labels",)}
_OLD_REPLACEMENTS = {"story_type": "types.group", "labels": "types", "state_map": "states"}
_COMMON_KEYS = set(TrackerSection.model_fields)


def _own_keys(kind: str) -> tuple[str, ...]:
    """The fields a kind's model adds to the common ones: its connection settings and its
    old flat keys."""
    return tuple(key for key in _MODELS[kind].model_fields if key not in _COMMON_KEYS)


def _block_keys(kind: str) -> tuple[str, ...]:
    """What a provider block may hold: the connection settings, `types` and `states`."""
    connection = [key for key in _own_keys(kind) if key not in _OLD_ONLY_KEYS[kind]]
    return (*connection, "types", "states")


# The section whose old keys were last warned about, and which of them: the active
# configuration is one object for the life of a run, so each key is warned of once.
_warned: tuple[object, set[tuple[str, str]]] | None = None


def _warn_old_keys(raw: dict[str, Any], repo: str, kind: str) -> None:
    global _warned
    current = config.active()
    if _warned is None or _warned[0] is not current:
        _warned = (current, set())
    for key in (*_own_keys(kind), "state_map", "types"):
        if key not in raw or (repo, key) in _warned[1]:
            continue
        _warned[1].add((repo, key))
        replacement = f"{kind}.{_OLD_REPLACEMENTS.get(key, key)}"
        logger.warning(
            "repo %r: tracker %s: %r is the old placement and is read as %r; "
            "move it into the %s block, as the old keys are dropped in 0.3.0",
            repo,
            kind,
            key,
            replacement,
            kind,
        )


def _expand(raw: dict[str, Any], repo: str, kind: str) -> dict[str, Any]:
    """The flat shape the models validate: a provider block is merged up, and the old keys
    are read as the three levels they always meant. Refuses a mix, naming both."""

    def refuse(problem: str) -> TrackerConfigError:
        return TrackerConfigError(f"repo {repo!r}: tracker ({kind}): {problem}")

    for other in _MODELS:
        if other != kind and other in raw:
            raise refuse(f"{other}: the block of another provider")
    if kind not in raw:
        _warn_old_keys(raw, repo, kind)
        old = {**raw}
        written = old.get("types", {})
        labels = old.get("labels", {})
        if not isinstance(written, dict) or not isinstance(labels, dict):
            # Not a mapping: left for validation to report against its key.
            return old
        if kind == "azure_devops":
            types = {"change": "Feature", "group": old.get("story_type"), "task": "Task"}
        else:
            types = {level: labels.get(name) for level, name in _LABEL_KINDS.items()}
        old.setdefault("levels", list(LEVEL_ORDER))
        old["types"] = {**{k: v for k, v in types.items() if v}, **written}
        return old
    block = raw[kind]
    if not isinstance(block, dict):
        raise refuse(f"{kind}: must be a mapping")
    flat_old = [key for key in (*_own_keys(kind), "state_map", "types") if key in raw]
    if flat_old:
        raise refuse(
            f"{', '.join(flat_old)}: old keys that cannot be combined with the {kind} block"
        )
    foreign = [key for key in block if key not in _block_keys(kind)]
    if foreign:
        raise refuse(f"{', '.join(foreign)}: not a key of the {kind} block")
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
