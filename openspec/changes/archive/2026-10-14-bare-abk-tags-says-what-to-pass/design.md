# Design

## The fault

`cmd_tags` (in `cli/pipeline.py`) chooses its changes as every change's directory name when `--all` is set, and
otherwise `[args.change]`. The parser declares `change` with `nargs="?"`, so with no argument `args.change` is `None`
and the list is `[None]`. The list is not empty, so the "no changes in the store" branch does not catch it. `check_tags`
passes the `None` to `tasks_path` (in `pipeline/work_graph.py`), which computes `changes_dir / change` and raises.

## How a usage error is reported here

The other commands do not call the argument parser's `error()` for a missing or contradictory argument. They check in
the command and print to standard error, then return 2: `abk changelog check` with no path and no repo
(`cmd_changelog_check`), `abk attach release` given both `--commit` and `--discard`, and `abk replan` with no selector
(`cmd_replan`, which prints a `usage:` line and returns 2). Only `config` declares a mutually exclusive group in the
parser. `abk tags` follows the first group: the check goes at the top of `cmd_tags`, before any path is built, and
returns 2. A mutually exclusive group is not used because the change is a positional with a default of `None`, which the
group cannot tell from "not given" in a way that also lets the message be the house wording.

## Both a change and `--all`

Refused, exit 2. Letting `--all` win would check every change and drop a name the person typed on purpose, which reads
as success while ignoring part of the request; letting the name win would do the same to the flag. Refusing costs one
retry and cannot mislead. The message is `abk tags: give a change or --all, not both`.

## Help

The `tags` parser's help becomes `validate a change's task-group tags (name a change, or --all for every change)`, and
the `change` argument gets help text saying what it is.

## Other optional positionals: the same pattern, scanned, not fixed

Found by searching `cli/*.py` for `nargs="?"` and `nargs="*"`:

- `abk pr view` and `abk pr diff` `number` (`cli/pr_cmd.py`): `None` is handled in `_number`, which falls back to the
  checked-out branch's pull request and reports "no local pull request" otherwise. No fault.
- `abk changelog check` `path` (`cli/changelog_cmd.py`): `None` is handled in `cmd_changelog_check`, which uses the
  repo's setting or prints a message and returns 2. No fault.
- `abk init` `planning_dir` (`cli/init.py`): defaults to `.`, never `None`. No fault.
- `abk replan` `changes` (`nargs="*"`, in `cli/pipeline.py`): an empty list with no `--all` or `--failed` prints a usage
  line and returns 2. No fault.
- `abk passthrough` `args` (`REMAINDER`): an empty list is the valid case.

No other command reaches a path with `None`. The `work_graph` module's own `main` declares `change` as required. The
follow-up, if wanted, is only wording: `replan` prints its usage on standard output where `tags` will print to standard
error.

## Tests

One per case, each asserting the exit status, the line, that standard error holds no `Traceback`, and that nothing was
read from the changes directory: neither argument, both arguments, `--all` over a store with a tagged change, a named
change. The help text is asserted to contain `--all`.
