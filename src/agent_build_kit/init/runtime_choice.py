"""`abk init`'s runtime question: which agent runs, and what its own setup asks.

Nothing here knows a runtime by name. The candidates come from the runtimes'
`detect` hooks, the questions from their `setup_questions`, and an answer is
written where its question says (`writes_to`, a dotted path into abk.yaml).
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter, ValidationError

from agent_build_kit import runtimes
from agent_build_kit.config import ModelsConfig, WorkspaceConfig
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.base import (
    Candidate,
    ModelSource,
    Question,
    QuestionKind,
    Which,
    models_of,
    name_validator,
    questions_of,
)

BACK = "back"
OTHER = "Other / my own configuration"

Ask = Callable[[str], str]


def yes(reply: str, *, default: bool = False) -> bool:
    """Whether a reply to a yes/no question says yes; an empty one says `default`."""
    answer = reply.strip().lower()
    return default if not answer else answer in ("y", "yes")


class RuntimeChoiceError(Exception):
    """The choice cannot be made as asked; `abk init` exits 2 having written nothing."""


class Choice(Frozen):
    runtime: str
    values: dict[str, Any]  # a fragment of abk.yaml: what the answers write

    @property
    def fragment(self) -> dict[str, Any]:
        return {"runtime": self.runtime, **self.values}

    def applied_to(self, config: WorkspaceConfig, *, keys_only: bool = False) -> WorkspaceConfig:
        """`config` with the choice written where each answer says. With `keys_only` only
        an answer written where abk.yaml has no key is refused: a value not yet in its final
        shape (an argv still to be split) is let through."""
        update: dict[str, Any] = {}
        for key, value in self.fragment.items():
            try:
                adapter = TypeAdapter(WorkspaceConfig.model_fields[key].annotation)
                current = adapter.dump_python(getattr(config, key), mode="json", by_alias=True)
                update[key] = adapter.validate_python(merge_values(current, value, at=key))
            except (KeyError, ValidationError) as error:
                if keys_only and isinstance(error, ValidationError):
                    if all(e["type"] != "extra_forbidden" for e in error.errors()):
                        continue
                raise RuntimeChoiceError(
                    f"an answer is written where abk.yaml has no place: {error}"
                ) from error
        return config.model_copy(update=update)


def _argv_paths() -> frozenset[str]:
    """Where each registered runtime's argv answers are written in abk.yaml."""
    return frozenset(
        question.writes_to
        for name in runtimes.names()
        for question in questions_of(runtimes.get(name))
        if question.kind == QuestionKind.ARGV
    )


def merge_values(base: Any, new: Any, *, at: str = "") -> Any:
    """`new` laid over `base` (`at` is where they sit in abk.yaml): mappings merge, an
    argv is replaced outright, other lists gain what they lack, else `new` wins."""
    if isinstance(base, Mapping) and isinstance(new, Mapping):
        return {
            **base,
            **{
                k: merge_values(base.get(k), v, at=f"{at}.{k}" if at else str(k))
                for k, v in new.items()
            },
        }
    if isinstance(base, list) and isinstance(new, list) and at not in _argv_paths():
        return [*base, *(item for item in new if item not in base)]
    return new


def parse_routes(sets: Sequence[str], config_file: str | None) -> dict[str, Any]:
    """What `--runtime-config FILE` and each `--set key=value` give, as one nested fragment."""
    fragment: dict[str, Any] = {}
    if config_file:
        try:
            loaded = yaml.safe_load(Path(config_file).expanduser().read_text())
        except (OSError, yaml.YAMLError) as error:
            raise RuntimeChoiceError(f"--runtime-config {config_file}: {error}") from error
        if not isinstance(loaded, Mapping):
            raise RuntimeChoiceError(f"--runtime-config {config_file}: not a mapping")
        fragment = dict(loaded)
    for item in sets:
        path, equals, value = item.partition("=")
        if not equals or not path:
            raise RuntimeChoiceError(f"--set {item!r}: use key=value")
        fragment = merge_values(fragment, _nested(path, yaml.safe_load(value) if value else ""))
    return fragment


def _unset(tree: Any, path: str) -> Any:
    """`tree` without the value at `path`, and without a mapping that leaves empty."""
    head, _, rest = path.partition(".")
    if not isinstance(tree, Mapping) or head not in tree:
        return tree
    kept = {k: v for k, v in tree.items() if k != head}
    if rest and (child := _unset(tree[head], rest)) != {}:
        kept[head] = child
    return kept


def _current(base: Mapping[str, Any], path: str) -> Any:
    node: Any = base
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _nested(path: str, value: Any) -> dict[str, Any]:
    for part in reversed(path.split(".")):
        value = {part: value}
    return value


def _value(question: Question, answer: str, base: Mapping[str, Any]) -> Any:
    if question.kind == QuestionKind.ARGV:
        return shlex.split(answer)
    if isinstance(_current(base, question.writes_to), list):
        return answer.replace(",", " ").split()
    return answer


def _answers(
    runtime_name: str,
    candidate: Candidate | None,
    *,
    ask: Ask,
    which: Which,
    base: Mapping[str, Any],
    interactive: bool,
    given: Mapping[str, str],
    extra: Mapping[str, Any] | None = None,
    can_go_back: bool = False,
) -> dict[str, Any] | str:
    """The fragment a runtime's questions write; `BACK` when the person went back. `extra`
    is what `--set` and `--runtime-config` give: it answers a question that writes where
    it sits and is otherwise laid over the answers."""
    values: dict[str, Any] = {}
    rest: Any = dict(extra or {})
    if interactive and candidate is not None and candidate.note and not _ready(candidate, ask):
        if can_go_back:
            return BACK
        raise RuntimeChoiceError(f"{candidate.label} needs {candidate.note}")
    for question in questions_of(runtimes.get(runtime_name)):
        default = ""
        if candidate is not None and question.key == "command":
            default = shlex.join(candidate.command)
        default = default or question.default
        shown = f"{question.prompt} [{default}]: " if default else f"{question.prompt}: "
        supplied = _current(extra or {}, question.writes_to)
        preset = given.get(question.key)
        if preset is None and supplied is not None:
            preset = shlex.join(supplied) if isinstance(supplied, list) else str(supplied)
            rest = _unset(rest, question.writes_to)
        while True:
            if preset is not None:
                answer = preset
            elif interactive:
                answer = ask(shown).strip()
                if can_go_back and answer.lower() == BACK:
                    return BACK
                answer = answer or default
            else:
                answer = default
            problem = question.validator(answer, which)
            if problem is None:
                break
            if not interactive or preset is not None:
                raise RuntimeChoiceError(f"{question.prompt}: {problem}")
            print(f"  {problem}")
        if answer or question.kind == QuestionKind.ARGV:
            values = merge_values(
                values, _nested(question.writes_to, _value(question, answer, base))
            )
    return merge_values(values, rest)


def _ready(candidate: Candidate, ask: Ask) -> bool:
    """Whether what the candidate needs is in place, or the person goes on without it."""
    reply = ask(f"{candidate.label} needs {candidate.note}; is it in place and running? [y/N] ")
    return yes(reply) or yes(ask("continue anyway? [y/N] "))


def _ordered(candidates: list[Candidate]) -> list[Candidate]:
    return [c for c in candidates if c.usable] + [c for c in candidates if not c.usable]


def show(candidates: list[Candidate]) -> list[Candidate]:
    """Print the candidates, usable first, and the person's own configuration last."""
    ordered = _ordered(candidates)
    print("Agent runtimes on this machine:")
    for number, candidate in enumerate(ordered, 1):
        line = f"  {number}. {candidate.label} ({shlex.join(candidate.command)})"
        if not candidate.usable:
            line += f" - not usable yet: {'; '.join(candidate.reasons)}"
        print(line)
        for note in (candidate.note, candidate.verified and f"verified: {candidate.verified}"):
            if note:
                print(f"       {note}")
    print(f"  {len(ordered) + 1}. {OTHER}")
    return ordered


def _pick_model(ask: Ask, role: str, names: list[str], *, listed: bool) -> str:
    """The model for `role` chosen from `names`, or typed when not `listed`; "" for none."""
    shown = (
        "Enter keeps the agent's default" if listed else "typed, not checked now; Enter: default"
    )
    while True:
        answer = ask(f"Model for {role} [{shown}]: ").strip()
        if answer.isdigit() and listed and 1 <= int(answer) <= len(names):
            return names[int(answer) - 1]
        if not answer or not listed or answer in names:
            return answer
        print(f"  {answer} is not one of: {', '.join(names)}")


def _models(runtime_name: str, values: Mapping[str, Any], *, ask: Ask) -> dict[str, Any]:
    """The `models:` fragment the person chooses from what needs no model call: the agent's
    advertised list, documented names, or a typed name."""
    runtime = runtimes.get(runtime_name)
    command = next(
        (
            _current(values, q.writes_to)
            for q in questions_of(runtime)
            if q.key == "command" and _current(values, q.writes_to)
        ),
        None,
    )
    listed = models_of(runtime, command)
    names = [m.name for m in listed.models]
    print(f"  {listed.note}")
    # The agent's own default first, numbered as `_pick_model` takes them.
    current = {m.name for m in listed.models if m.current}
    names.sort(key=lambda name: name not in current)
    for number, name in enumerate(names, 1):
        print(f"    {number}. {name}{' (default)' if name in current else ''}")
    per_role = bool(names)
    if names and listed.source == ModelSource.DOCUMENTED:
        menu = ""
        while menu not in ("1", "2", "3"):
            menu = (
                ask(
                    "Models: 1 = the default models (recommended), 2 = choose per role "
                    "from the list, 3 = type names [1]: "
                ).strip()
                or "1"
            )
        if menu == "1":
            return {}
        per_role = menu == "2"
    chosen = {
        role: name
        for role in ModelsConfig.model_fields
        if (name := _pick_model(ask, role, names, listed=per_role))
    }
    return {"models": chosen} if chosen else {}


def _first_usable(candidates: list[Candidate], runtime: str) -> Candidate | None:
    return next((c for c in candidates if c.runtime == runtime and c.usable), None)


def _pick(ordered: list[Candidate], *, ask: Ask) -> Candidate | None:
    """The candidate chosen, or None for the person's own configuration."""
    usable = [c for c in ordered if c.usable]
    default = str(ordered.index(usable[0]) + 1) if len(usable) == 1 else ""
    while True:
        answer = ask(f"Which runtime? [{default}]: " if default else "Which runtime? ").strip()
        answer = answer or default
        if not answer.isdigit() or not 1 <= int(answer) <= len(ordered) + 1:
            print(f"  enter a number from 1 to {len(ordered) + 1}")
            continue
        if int(answer) == len(ordered) + 1:
            return None
        picked = ordered[int(answer) - 1]
        if picked.usable:
            return picked
        print(f"  {picked.label} is not usable yet: {'; '.join(picked.reasons)}")


def _own_runtime(*, ask: Ask, which: Which) -> str:
    names = runtimes.names()
    if len(names) == 1:
        return names[0]
    validate = name_validator(tuple(names))
    while True:
        answer = ask(f"Which runtime is it? ({', '.join(names)}): ").strip()
        problem = validate(answer, which)
        if problem is None:
            return answer
        print(f"  {problem}")


def choose(
    candidates: list[Candidate],
    *,
    ask: Ask,
    which: Which,
    base: Mapping[str, Any],
    yes: bool,
    runtime: str | None = None,
    agent_command: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Choice:
    """Decide the runtime and collect its answers, asking only when not `yes`. `extra` is
    what `--set` and `--runtime-config` give; a runtime it names stands for `--runtime`."""
    extra = dict(extra or {})
    runtime = runtime or extra.pop("runtime", None)
    common: dict[str, Any] = {
        "ask": ask,
        "which": which,
        "base": base,
        "interactive": not yes,
    }
    given = {} if agent_command is None else {"command": agent_command}
    if runtime is not None:
        problem = name_validator(tuple(runtimes.names()))(runtime, which)
        if problem:
            raise RuntimeChoiceError(f"--runtime: {problem}")
        candidate = _first_usable(candidates, runtime)
        values = _answers(runtime, candidate, given=given, extra=extra, **common)
        assert isinstance(values, dict)
    elif yes:
        usable = [c for c in candidates if c.usable]
        if len(usable) != 1:
            show(candidates)
            raise RuntimeChoiceError(
                "no runtime on this machine is usable yet"
                if not usable
                else "several runtimes are usable: name one with --runtime"
            )
        runtime = usable[0].runtime
        values = _answers(runtime, usable[0], given=given, extra=extra, **common)
        assert isinstance(values, dict)
    else:
        ordered = show(candidates)
        while True:
            picked = _pick(ordered, ask=ask)
            runtime = picked.runtime if picked else _own_runtime(ask=ask, which=which)
            answered = _answers(
                runtime, picked, given=given, extra=extra, can_go_back=True, **common
            )
            if isinstance(answered, dict):
                values = answered
                break
            ordered = show(candidates)
    runtime = runtime or ""
    if not yes:
        if "models" not in values:
            values = merge_values(values, _models(runtime, values, ask=ask))
        values = _fallbacks(candidates, runtime, values, **common)
    return Choice(runtime=runtime, values=values)


def _fallbacks(
    candidates: list[Candidate],
    chosen: str,
    values: dict[str, Any],
    *,
    ask: Ask,
    which: Which,
    base: Mapping[str, Any],
    interactive: bool,
) -> dict[str, Any]:
    """Offer each other usable runtime as a fallback, configured beside the chosen one."""
    configured = base.get("runtimes") or {}
    for other in dict.fromkeys(
        c.runtime
        for c in candidates
        if c.usable and c.runtime != chosen and c.runtime not in configured
    ):
        candidate = _first_usable(candidates, other)
        reply = ask(f"also configure {candidate.label} as a fallback runtime? [y/N] ")  # type: ignore[union-attr]
        if not yes(reply):
            continue
        extra = _answers(
            other,
            candidate,
            ask=ask,
            which=which,
            base=base,
            interactive=interactive,
            given={},
            can_go_back=True,
        )
        if isinstance(extra, dict):  # BACK: its needs were declined, so it is left out
            values = merge_values(values, extra)
    return values
