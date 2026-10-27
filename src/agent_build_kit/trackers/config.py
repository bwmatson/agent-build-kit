"""The `repos.<name>.tracker` section: kind-specific models and their validation."""

from __future__ import annotations

import re
from typing import Annotated, Literal, get_args

from pydantic import Field, TypeAdapter, ValidationError, field_validator

from agent_build_kit import config
from agent_build_kit.model import Frozen
from agent_build_kit.trackers.base import ItemKind

# The only shape a credential may take in abk.yaml: the name of an environment variable.
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*")

OFF_KIND = "none"


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

    @field_validator("token_env")
    @classmethod
    def _name_only(cls, value: str | None) -> str | None:
        if value is not None and not _ENV_NAME.fullmatch(value):
            raise ValueError("must be the name of an environment variable, never a credential")
        return value


class AzureDevOpsTracker(TrackerSection):
    kind: Literal["azure_devops"]
    organization: str = Field(min_length=1)
    project: str = Field(min_length=1)
    team: str = Field(min_length=1)
    area_path: str = Field(min_length=1)
    iteration_path: str = Field(min_length=1)
    story_type: str = Field(min_length=1)


class GithubTracker(TrackerSection):
    kind: Literal["github"]
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    # The label that stands for each logical kind.
    labels: dict[ItemKind, str]
    host: str | None = None
    project_number: int | None = None

    @field_validator("labels")
    @classmethod
    def _every_kind_has_a_label(cls, labels: dict[ItemKind, str]) -> dict[ItemKind, str]:
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
        return _SECTIONS.validate_python(raw)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in found['loc'][1:]) or 'section'}: {found['msg']}"
            for found in error.errors(include_input=False)
        )
        raise TrackerConfigError(f"repo {repo!r}: tracker ({kind}): {problems}") from None
