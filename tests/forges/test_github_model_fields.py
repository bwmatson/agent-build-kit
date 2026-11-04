"""The GitHub REST response models read only fields the installed schema defines.

A field a model names that the API version's schema does not have is one the host
may stop sending (a pull request's `merge_commit_sha` went in version 2026-03-10),
and the model then reads its default for ever, with every test green on fakes that
still carry it. Each model is compared with the schema model of the endpoint the
forge reads it from, found through the client's generated method, so an upgrade of
the library that changes a document fails here, naming the model and the field.
"""

from __future__ import annotations

import inspect
import typing
from dataclasses import dataclass
from typing import Any, Union

import githubkit_schemas.latest.models as schema
import pytest
from githubkit import GitHub
from pydantic import BaseModel

from agent_build_kit.forges import github_models
from agent_build_kit.forges.github_models import _Rest


class _Resolve(dict[str, Any]):
    """The names a generated return annotation uses: schema models by name, and
    the `Response[data, typed-dict]` wrapper reduced to its data type."""

    def __missing__(self, name: str) -> object:
        return getattr(schema, name, name)


class _Response:
    def __class_getitem__(cls, args: tuple[object, ...]) -> object:
        return args[0]


def _model_in(annotation: object) -> type[BaseModel] | None:
    """The first schema model inside a field's or a return's type: `list[X]`,
    `X | None` and `Missing[X]` all give X."""
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        found = _model_in(arg)
        if found is not None:
            return found
    return None


def endpoint_model(namespace: str, method: str, via: tuple[str, ...] = ()) -> type[BaseModel]:
    """The schema model a generated method answers with, or the model of the
    field reached by `via` (a document's list of items, say)."""
    client = GitHub("token")
    generated = getattr(getattr(client.rest, namespace), method)
    answer = inspect.signature(generated).return_annotation
    found = _model_in(eval(answer, {}, _Resolve(Response=_Response, Union=Union, list=list)))  # noqa: S307
    assert found is not None, f"{namespace}.{method} answers with no schema model: {answer}"
    for step in via:
        found = _model_in(found.model_fields[step].annotation)
        assert found is not None, f"{namespace}.{method}: {step} is not a model"
    return found


def wire_names(model: type[BaseModel]) -> set[str]:
    return {field.alias or name for name, field in model.model_fields.items()}


def undefined_fields(
    doc: type[BaseModel], model: type[BaseModel], only: set[str] | None
) -> set[str]:
    """The fields `doc` reads (or the `only` subset of them) that `model` lacks."""
    read = {field.alias or name for name, field in doc.model_fields.items()}
    return (read if only is None else read & only) - wire_names(model)


@dataclass(frozen=True)
class Endpoint:
    """Where a document is read from: a generated method, the path to the nested
    model when the document is part of the answer, and the fields this read uses
    when it does not use them all."""

    namespace: str
    method: str
    via: tuple[str, ...] = ()
    only: frozenset[str] | None = None


# Each REST document, with every endpoint the forge reads it from.
READ_FROM: dict[type[_Rest], list[Endpoint]] = {
    github_models.NumberDoc: [
        Endpoint("pulls", "list"),  # find_pr
        Endpoint("pulls", "create"),  # create_pr
    ],
    github_models.PullDoc: [Endpoint("pulls", "get")],
    github_models.MergeDoc: [Endpoint("pulls", "merge")],
    github_models.ReviewDoc: [Endpoint("pulls", "list_reviews")],
    github_models.InlineCommentDoc: [
        Endpoint("pulls", "list_review_comments"),
        Endpoint("pulls", "create_reply_for_review_comment"),
        # comment_exists lists a pull request's conversation comments with the same document,
        # which reads only these three of them; the rest default.
        Endpoint("issues", "list_comments", only=frozenset({"id", "node_id", "body"})),
    ],
    github_models.LabelDoc: [
        Endpoint("issues", "list_labels_for_repo"),
        Endpoint("issues", "list_labels_on_issue"),
    ],
    github_models.FileDoc: [Endpoint("pulls", "list_files")],
    github_models.JobsDoc: [Endpoint("actions", "list_jobs_for_workflow_run")],
    github_models.JobDoc: [Endpoint("actions", "list_jobs_for_workflow_run", via=("jobs",))],
    github_models.NodeIdDoc: [
        Endpoint("pulls", "get_review"),
        Endpoint("issues", "create_comment"),
    ],
    # The stacks requests are raw (`gh.request`), so the forge reads no generated model, but
    # the library documents the same answers: compared with those, not skipped.
    github_models.StackDoc: [
        Endpoint("pulls", "stacks_create"),
        Endpoint("pulls", "stacks_list"),
        Endpoint("pulls", "stacks_add"),  # add_to_stack
        Endpoint("pulls", "stacks_get"),
    ],
    github_models.StackPullDoc: [
        Endpoint("pulls", "stacks_create", via=("pull_requests",)),
        Endpoint("pulls", "stacks_list", via=("pull_requests",)),
    ],
}


def rest_documents() -> list[type[_Rest]]:
    return [
        member
        for _, member in inspect.getmembers(github_models, inspect.isclass)
        if issubclass(member, _Rest) and member is not _Rest
    ]


def test_every_rest_document_is_compared_with_an_endpoint() -> None:
    unmapped = [doc.__name__ for doc in rest_documents() if doc not in READ_FROM]

    assert not unmapped, f"REST documents with no endpoint named in READ_FROM: {unmapped}"


@pytest.mark.parametrize(
    "doc, endpoint",
    [(doc, endpoint) for doc, endpoints in READ_FROM.items() for endpoint in endpoints],
    ids=lambda item: item.__name__ if isinstance(item, type) else f"{item.namespace}.{item.method}",
)
def test_a_rest_document_reads_only_fields_the_schema_defines(
    doc: type[_Rest], endpoint: Endpoint
) -> None:
    model = endpoint_model(endpoint.namespace, endpoint.method, endpoint.via)

    missing = undefined_fields(doc, model, None if endpoint.only is None else set(endpoint.only))

    assert not missing, (
        f"{doc.__name__} reads {sorted(missing)}, which {model.__name__} "
        f"({endpoint.namespace}.{endpoint.method}) does not define"
    )


def test_a_document_naming_a_field_the_schema_lacks_fails_naming_both() -> None:
    class Removed(BaseModel):
        number: int
        merge_commit_sha: str | None = None

    model = endpoint_model("pulls", "get")

    assert undefined_fields(Removed, model, None) == {"merge_commit_sha"}
    assert "merge_commit_sha" not in wire_names(model)


def test_the_schema_models_are_those_of_the_version_the_client_sends() -> None:
    client = GitHub("token")
    version = str(client.rest.pulls._REST_API_VERSION)  # pyrefly: ignore[missing-attribute]

    model = endpoint_model("pulls", "get")

    assert f".v{version.replace('-', '_')}." in model.__module__, model.__module__
