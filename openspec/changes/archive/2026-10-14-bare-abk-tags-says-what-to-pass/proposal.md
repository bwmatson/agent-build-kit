# Proposal

## Why

`abk tags` takes an optional change name and an `--all` flag. Run with neither, it crashes with
`TypeError: unsupported operand type(s) for /: 'PosixPath' and 'NoneType'`: the command builds its list of changes as
`[None]`, and the check joins the changes directory with that `None`. The person who typed it learns nothing about what
to pass. `--all` is the existing, intended way to say "every change", so the only thing missing is saying so.

## What Changes

- **With neither a change nor `--all`,** `abk tags` prints one line, `abk tags: name a change, or pass --all for every
  change`, to standard error and exits 2, the way the other commands report a usage error. No traceback.
- **With both a change and `--all`,** `abk tags` refuses with one line on standard error and exit status 2, rather than
  quietly checking one and ignoring the other.
- **The command's help text names `--all`.**
- **Unchanged:** `abk tags --all` and `abk tags <change>` behave as before.
- **Not changed here:** other commands with an optional positional are scanned in `design.md`; none has the same
  fault, and nothing is fixed outside `abk tags`.

## Impact

- `cmd_tags` and the `tags` parser in `cli/pipeline.py`.
- The `unit-scheduling` capability, which documents `abk tags`, gains one requirement.
