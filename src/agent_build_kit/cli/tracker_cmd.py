"""`abk tracker`: see, run, adopt into and repair a repo's tracker mirror (spec: tracker-rollout).

Each command calls what the tick calls: `sync` the push pass and then the pull, `status` reads the
files and the machine-local snapshot, `link` writes `tracker.yaml` through the pipeline's path
after reading the item, `conflicts` reads the conflict records. A repo with no `tracker` section
prints that none is configured and nothing else happens; every command has a `--json` form.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from agent_build_kit import trackers
from agent_build_kit.cli.pipeline import store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.task_progress import TASKS_FILE, progress_root
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TargetMismatch,
    TrackerFile,
    mapping_target,
    read_for_target,
    with_manual_parent,
    write_tracker,
)
from agent_build_kit.pipeline.work_graph import epic_reference, read_tasks, validate_tasks
from agent_build_kit.trackers.apply import (
    CLOSED_FIELD,
    REMOVED,
    Place,
    apply_changes,
    board_state,
    board_text,
    close_conflict,
    closed_agrees,
    gone_from_spec,
    places_of,
)
from agent_build_kit.trackers.base import Item, Tracker
from agent_build_kit.trackers.config import TrackerConfigError, TrackerSection, section_for
from agent_build_kit.trackers.folders import (
    ARCHIVE_DIR,
    archived_entries,
    change_folder,
    tracker_read_dir,
    tracker_write_dir,
)
from agent_build_kit.trackers.levels import group_key
from agent_build_kit.trackers.manual_parent import (
    ManualParent,
    ManualParentError,
    ManualParentSource,
)
from agent_build_kit.trackers.poll import PULLED_KEY, poll_board
from agent_build_kit.trackers.reconciler import (
    adopted_entry,
    last_reconciled,
    read_snapshot,
    snapshot_path,
)
from agent_build_kit.trackers.tick_step import changes_of, has_group_for, sync_repo
from agent_build_kit.trackers.wanted_board import wanted_board

NONE_CONFIGURED = "no tracker configured for {repo}"


class Refused(Exception):
    """A command that cannot proceed; the message says why."""


def _emit(args: argparse.Namespace, payload: dict[str, Any], lines: list[str]) -> None:
    print(json.dumps(payload) if args.json else "\n".join(lines))


def _refusing(name: str, run: Callable[[], int]) -> int:
    try:
        return run()
    except (Refused, ManualParentError, TrackerConfigError, TargetMismatch) as error:
        print(f"abk tracker {name}: refused: {error}", file=sys.stderr)
        return 1


def _unconfigured(args: argparse.Namespace, repos: list[str]) -> int:
    _emit(
        args,
        {"repos": {repo: {"configured": False, "error": None} for repo in repos}},
        [NONE_CONFIGURED.format(repo=repo) for repo in repos],
    )
    return 0


def _names(inst: Installation, repo: str) -> list[str]:
    """The changes with a group for `repo`: those in flight and the archived."""
    names = changes_of(inst, repo)
    for name, folder in archived_entries(inst.changes_dir).items():
        if name not in names and has_group_for(folder / TASKS_FILE, repo):
            names.append(name)
    return names


def _files(inst: Installation, repo: str) -> dict[str, TrackerFile]:
    """The tracker file of each change of `repo` that has one for the board the configuration
    names, read where the pass reads it: an archived change's machine-local copy wins. A file
    that records another board or cannot be read is left out."""
    try:
        section = section_for(repo)
    except TrackerConfigError:
        return {}
    if section is None:
        return {}
    archive = archived_entries(inst.changes_dir)
    found: dict[str, TrackerFile] = {}
    for name in _names(inst, repo):
        folder = tracker_read_dir(inst.changes_dir, inst.state_dir, name, archive)
        try:
            recorded = read_for_target(folder, section.kind, mapping_target(section))
        except (TargetMismatch, OSError, ValueError):
            continue
        if recorded is not None:
            found[name] = recorded
    return found


def _conflict_rows(inst: Installation, repo: str) -> list[dict[str, str]]:
    return [
        {
            "id": f"{name}:{record.item_id}:{record.field}",
            "repo": repo,
            "change": name,
            "item_id": record.item_id,
            "field": record.field,
            "spec_value": record.spec_value,
            "tracker_value": record.tracker_value,
            "who": record.who,
            "when": record.when,
        }
        for name, recorded in _files(inst, repo).items()
        for record in recorded.conflicts
        if record.status == "open"
    ]


def _conflict_line(row: dict[str, str]) -> str:
    return (
        f"  {row['id']}: {row['change']} item {row['item_id']} {row['field']}: "
        f"spec {row['spec_value']!r}, board {row['tracker_value']!r}"
        f" (by {row['who']} at {row['when']})"
    )


def _repos_with(inst: Installation) -> tuple[list[str], list[str]]:
    """The repos that name a tracker section, valid or not, and those that name none."""
    named: list[str] = []
    bare: list[str] = []
    for repo in inst.repos:
        try:
            has = section_for(repo) is not None
        except TrackerConfigError:
            has = True
        (named if has else bare).append(repo)
    return named, bare


def _status_of(inst: Installation, repo: str) -> dict[str, Any]:
    row: dict[str, Any] = {"configured": True, "error": None}
    try:
        section = section_for(repo)
        tracker = trackers.for_repo(repo)
    except TrackerConfigError as error:
        return {**row, "error": str(error)}
    if section is None or tracker is None:
        return {"configured": False, "error": None}
    files = _files(inst, repo)
    snapshot = read_snapshot(snapshot_path(inst.state_dir, repo))
    pushed = last_reconciled(snapshot_path(inst.state_dir, repo))
    row.update(
        target=section.target,
        identity=None,
        changes=sum(1 for found in files.values() if found.change),
        groups=sum(len(found.groups) for found in files.values()),
        tasks=sum(len(found.tasks) for found in files.values()),
        to_create=None,
        last_push=pushed.isoformat() if pushed else None,
        last_pull=snapshot.get(PULLED_KEY),
        conflicts=_conflict_rows(inst, repo),
    )
    try:
        row["identity"] = tracker.identity().name
        pending = sync_repo(
            inst, repo, store_for(inst).all(), lambda _: None, dry_run=True, uncapped=True
        )
        row["to_create"] = len(pending.listed) if pending else 0
    except Exception as error:  # noqa: BLE001 — a host answers in its own errors
        row["error"] = f"{type(error).__name__}: {error}"
    return row


def _status_lines(repo: str, row: dict[str, Any]) -> list[str]:
    if row["error"] and "target" not in row:
        return [f"{repo}: {row['error']}"]
    lines = [f"{repo}: {row['target']} as {row['identity']}"]
    if row["error"]:
        lines.append(f"  error: {row['error']}")
    lines += [
        f"  mirrored: {row['changes']} changes, {row['groups']} groups, {row['tasks']} tasks",
        f"  waiting to be created: {row['to_create']}",
        f"  last push: {row['last_push'] or 'never'}; last pull: {row['last_pull'] or 'never'}",
        f"  open conflicts: {len(row['conflicts'])}",
        *(_conflict_line(conflict) for conflict in row["conflicts"]),
    ]
    return lines


def cmd_status(args: argparse.Namespace, inst: Installation) -> int:
    named, bare = _repos_with(inst)
    if not named:
        return _unconfigured(args, bare)
    rows = {repo: _status_of(inst, repo) for repo in named}
    rows.update({repo: {"configured": False, "error": None} for repo in bare})
    lines = (
        [line for repo, row in rows.items() for line in _status_lines(repo, row)] if named else []
    )
    lines += [NONE_CONFIGURED.format(repo=repo) for repo in bare]
    _emit(args, {"repos": rows}, lines)
    return 0


def _sync_one(
    inst: Installation, repo: str, args: argparse.Namespace
) -> tuple[dict[str, Any], list[str]]:
    units = store_for(inst).all()
    lines: list[str] = []

    def log(text: str) -> None:
        lines.append(text)

    if args.dry_run:
        report = sync_repo(inst, repo, units, log, dry_run=True)
        listed = report.listed if report else ()
        lines.append(f"{repo}: would create {len(listed)}")
        lines += [f"  {marker}" for marker in listed]
        return {"dry_run": True, "would_create": list(listed)}, lines
    expected = None
    if last_reconciled(snapshot_path(inst.state_dir, repo)) is None:
        counted = sync_repo(inst, repo, units, log, dry_run=True, uncapped=True)
        expected = len(counted.listed) if counted else 0
        lines.append(f"{repo}: first pass, a backfill of {expected} items is expected")
    report = sync_repo(inst, repo, units, log)
    created = report.created if report else 0
    payload: dict[str, Any] = {"dry_run": False, "created": created, "expected": expected}
    lines.append(f"{repo}: pushed, {created} created")
    if expected is not None and expected > created:
        payload["remaining"] = expected - created
        lines.append(f"{repo}: {expected - created} remain for later ticks")
    changes = poll_board(repo, state_dir=inst.state_dir, log=log)
    applied = apply_changes(
        repo, changes, changes_dir=inst.changes_dir, store=store_for(inst), log=log
    )
    payload["pulled"] = len(changes)
    payload["conflicts"] = len(applied.conflicts)
    lines.append(f"{repo}: pulled {len(changes)} changes, {len(applied.conflicts)} conflicts")
    return payload, lines


def cmd_sync(args: argparse.Namespace, inst: Installation) -> int:
    named, bare = _repos_with(inst)
    if not named:
        return _unconfigured(args, bare)
    payload: dict[str, Any] = {"repos": {}}
    lines: list[str] = []
    for repo in named:
        try:
            result, shown = _sync_one(inst, repo, args)
        except Exception as error:  # noqa: BLE001 — one repo's failure never stops the next
            message = f"{type(error).__name__}: {error}"
            result, shown = {"error": message}, [f"{repo}: failed: {message}"]
        payload["repos"][repo] = result
        lines += shown
    lines += [NONE_CONFIGURED.format(repo=repo) for repo in bare]
    _emit(args, payload, lines)
    return 0


def _repo_of_change(inst: Installation, change: str) -> tuple[str | None, list[str]]:
    """The repo with a tracker that `change` has groups in, and the repos it has groups in."""
    tasks = inst.changes_dir / change / TASKS_FILE
    if not tasks.is_file():
        raise Refused(f"change {change} does not exist")
    groups, _ = validate_tasks(tasks, repos=tuple(inst.repos))
    repos = sorted({group.repo for group in groups})
    for repo in repos:
        if section_for(repo) is not None:
            return repo, repos
    return None, repos


def _held_elsewhere(inst: Installation, repo: str, target: str, item_id: str) -> Place | None:
    """Where the tracker files record the item, when that is not the slot keyed `target`."""
    place = places_of(_files(inst, repo)).get(item_id)
    return place if place is not None and place.key != target else None


def _write(inst: Installation, change: str, recorded: TrackerFile) -> None:
    write_tracker(tracker_write_dir(inst.changes_dir, inst.state_dir, change), recorded)


def _current(inst: Installation, section: TrackerSection, change: str) -> TrackerFile:
    folder = tracker_read_dir(inst.changes_dir, inst.state_dir, change)
    found = read_for_target(folder, section.kind, mapping_target(section))
    return found or TrackerFile(kind=section.kind, target=mapping_target(section))


def _source(tracker: Tracker) -> ManualParentSource:
    if not (hasattr(tracker, "read_manual_parent") and hasattr(tracker, "find_manual_parents")):
        raise Refused("this tracker cannot read an existing item")
    return tracker  # type: ignore[return-value]


def _in_scope(found: ManualParent) -> bool:
    return found.in_scope


def _check_group(inst: Installation, repo: str, change: str, number: int) -> None:
    """Refuse a group number the change does not have for `repo`."""
    groups, _ = validate_tasks(inst.changes_dir / change / TASKS_FILE, repos=tuple(inst.repos))
    if not any(group.number == number and group.repo == repo for group in groups):
        raise Refused(f"change {change} has no group {number} for repo {repo}")


def _link_epic(
    inst: Installation, repo: str, section: TrackerSection, tracker: Tracker, change: str
) -> str:
    if not section.epic:
        raise Refused(f"repo {repo} has no epic setting, so a change has no manual parent")
    reference = epic_reference(inst.changes_dir / change / TASKS_FILE)
    if reference is None:
        raise Refused(f"change {change} has no `Epic:` line in its tasks.md")
    recorded = _current(inst, section, change)
    linked = with_manual_parent(recorded, section, reference, _source(tracker), _in_scope)
    _write(inst, change, linked)
    return f"{change}: epic {linked.epic} recorded"


def _link_item(
    inst: Installation,
    repo: str,
    section: TrackerSection,
    tracker: Tracker,
    args: argparse.Namespace,
) -> str:
    number: int | None = args.group
    level = "change" if number is None else "group"
    if level not in section.levels:
        raise Refused(f"repo {repo} has the levels {', '.join(section.levels)}, not {level}")
    found = _source(tracker).read_manual_parent(args.item)
    if found is None:
        raise Refused(f"no board item has the id {args.item!r}")
    if not found.in_scope:
        raise Refused(f"item {found.id} is outside the board this repo syncs")
    if found.type == section.level_types.get("task"):
        raise Refused(
            f"item {found.id} is a task item; task items are tied to lines in tasks.md "
            "and cannot be linked by hand"
        )
    expected = section.level_types[level]
    if found.type != expected:
        raise Refused(
            f"item {found.id} is a {found.type!r}, and the {level} level takes a {expected!r}"
        )
    if number is not None:
        _check_group(inst, repo, args.change, number)
    target = args.change if number is None else group_key(args.change, number)
    holder = _held_elsewhere(inst, repo, target, found.id)
    if holder is not None:
        if holder.change != args.change:
            raise Refused(f"item {found.id} is already mapped to change {holder.change}")
        raise Refused(f"item {found.id} is already mapped to {holder.key}")
    recorded = _current(inst, section, args.change)
    # A person's item keeps the title and body they wrote, as an item adopted from a hold does.
    entry: Synced = adopted_entry(tracker.get(found.id)).model_copy(update={"adopted": True})
    if number is None:
        taken = recorded.change
        update: dict[str, Any] = {"change": entry}
        where = args.change
    else:
        key = group_key(args.change, number)
        taken = recorded.groups.get(key)
        update = {"groups": {**recorded.groups, key: entry}}
        where = key
    if taken is not None and taken.id != found.id:
        raise Refused(f"{where} is already mapped to item {taken.id}")
    _write(inst, args.change, recorded.model_copy(update=update))
    return f"{where}: item {found.id} recorded"


def cmd_link(args: argparse.Namespace, inst: Installation) -> int:
    def run() -> int:
        repo, repos = _repo_of_change(inst, args.change)
        if repo is None:
            return _unconfigured(args, repos)
        section = section_for(repo)
        tracker = trackers.for_repo(repo)
        assert section is not None and tracker is not None
        if args.epic:
            if args.item is not None or args.group is not None:
                raise Refused("--epic takes the Epic: line's item; give no item id or --group")
            text = _link_epic(inst, repo, section, tracker, args.change)
        elif args.item is None:
            raise Refused("give the board item id to link, or --epic")
        else:
            text = _link_item(inst, repo, section, tracker, args)
        _emit(args, {"repo": repo, "change": args.change, "linked": text}, [text])
        return 0

    return _refusing("link", run)


def _sides(
    inst: Installation,
    section: TrackerSection,
    files: dict[str, TrackerFile],
    place: Place,
    field: str,
    item: Item,
) -> tuple[str, str]:
    """What the spec says now and what the board shows now for the field of an item."""
    tasks_path = change_folder(inst.changes_dir, place.change) / TASKS_FILE
    if place.level == "task":
        current = next(
            (t for t in read_tasks(tasks_path, place.change) if t.key == place.key), None
        )
        if current is None:
            raise Refused(f"task {place.key} is no longer in tasks.md")
        if field == "state":
            return ("done" if current.done else "new"), board_state(item)
        if field == "body":
            return current.text, board_text(item, files[place.change].tasks[place.key])
    elif field in {"title", "state"}:
        archived = change_folder(inst.changes_dir, place.change).parent.name == ARCHIVE_DIR
        wanted = wanted_board(
            section,
            inst.changes_dir,
            [place.change],
            store_for(inst).all(),
            browse=lambda _: "",
            archived=[place.change] if archived else (),
            tracking_dir=progress_root(inst),
        )
        found = next((w for w in wanted if w.marker == place.key), None)
        if found is None:
            raise Refused(f"the spec no longer wants {place.key}")
        if field == "title":
            return found.title, item.title
        return ("done" if found.state == "done" else "new"), board_state(item)
    raise Refused(f"the {field} conflict of item {item.id} is settled by hand: it has no check")


def _resolve(inst: Installation, repo: str, row: dict[str, str]) -> str:
    section, tracker = section_for(repo), trackers.for_repo(repo)
    assert section is not None and tracker is not None
    files = _files(inst, repo)
    place = places_of(files).get(row["item_id"])
    if place is None:
        raise Refused(f"item {row['item_id']} is in no change's tracker file")
    item = tracker.get(row["item_id"])
    field = row["field"]
    if field == REMOVED:
        tasks_path = change_folder(inst.changes_dir, place.change) / TASKS_FILE
        restored = (item.kit_state or item.state) != REMOVED
        if not (restored or gone_from_spec(tasks_path, place)):
            raise Refused(
                f"item {item.id} is still removed on the board and still in the spec: "
                "restore it on the board or take it out of tasks.md"
            )
    elif field == CLOSED_FIELD:
        if not closed_agrees(item, place, store_for(inst).all()):
            raise Refused(
                f"item {item.id} is still done on the board ({board_state(item)}) and its "
                f"group is still unmerged: reopen the item on the board or merge the group"
            )
    else:
        spec, board = _sides(inst, section, files, place, field, item)
        if spec != board:
            raise Refused(
                f"the sides still differ on {field} of item {item.id}: "
                f"spec {spec!r}, board {board!r}"
            )
    closed = close_conflict(files[place.change], item.id, field)
    if closed is None:
        raise Refused(f"no open conflict {field} on item {item.id}")
    _write(inst, place.change, closed)
    return f"{row['id']}: resolved"


def cmd_conflicts(args: argparse.Namespace, inst: Installation) -> int:
    named, bare = _repos_with(inst)
    if not named:
        return _unconfigured(args, bare)

    def run() -> int:
        rows = [row for repo in named for row in _conflict_rows(inst, repo)]
        if args.resolve is not None:
            row = next((row for row in rows if row["id"] == args.resolve), None)
            if row is None:
                raise Refused(f"no open conflict {args.resolve!r}")
            text = _resolve(inst, row["repo"], row)
            _emit(args, {"resolved": args.resolve}, [text])
            return 0
        lines = [f"{len(rows)} open conflicts", *(_conflict_line(row) for row in rows)]
        _emit(args, {"conflicts": rows}, lines)
        return 0

    return _refusing("conflicts", run)


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("tracker", help="the work-tracker mirror of a repo")
    actions = parser.add_subparsers(dest="tracker_command", required=True)

    def command(name: str, help: str, func: Callable[..., int]) -> argparse.ArgumentParser:
        added = actions.add_parser(name, help=help)
        added.add_argument("--json", action="store_true", help="print one JSON document")
        added.set_defaults(func=func)
        return added

    command("status", "show each mirrored repo's state", cmd_status)

    sync = command("sync", "run the push and then the pull once", cmd_sync)
    sync.add_argument("--dry-run", action="store_true", help="list the creates, make no write")

    link = command("link", "adopt an existing board item for a change", cmd_link)
    link.add_argument("change")
    link.add_argument("item", nargs="?", help="the board item id")
    link.add_argument("--group", type=int, help="adopt it for this group of the change")
    link.add_argument("--epic", action="store_true", help="record the change's `Epic:` item")

    conflicts = command("conflicts", "list open conflicts, or mark one resolved", cmd_conflicts)
    conflicts.add_argument("--resolve", metavar="ID", help="mark this conflict resolved")
