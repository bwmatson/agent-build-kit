# Design

## Where this sits

`build_commit` stages everything, commits, and reports how many commits
resulted — a count the runner uses to decide whether the run produced anything
worth reviewing. On a non-zero exit it raises, and `_build` turns that into a
`failed` unit.

The count contract stays exactly as it is: nothing staged is still zero, a
successful commit is still one. What changes is the middle, where a rejection
currently leaves.

## Two rejections, told apart by what the gate did

A commit gate rejects for two different reasons and the right response differs:

- **It rewrote the files.** A formatter reformatting, an import sorter sorting,
  a trailing-whitespace fixer trimming. The hook exits non-zero to say "look
  again", the fix is already on disk, and committing once more succeeds. Asking
  an agent to do anything here would be asking it to re-run a command.
- **It found something.** A lint rule, a type error, a check the author has to
  satisfy. Nothing on disk changes by itself, so retrying loops. This is the one
  worth an agent call, and the gate's own words are the best prompt available —
  they name the file, the line and the rule.

Telling them apart is done the plain way: try again, and if the second attempt
succeeds, it was the first kind. That is one cheap `git commit`, it needs no
parsing of a hook's prose, and it cannot be fooled by a gate whose wording
changes. Only when the retry fails too does an agent get involved.

## The fix round

The gate's output is handed back as the prompt, with the same tool policy the
build run had, in the same worktree — the agent is fixing its own uncommitted
work, not writing new code. Then the commit is attempted again.

Bounded, because a gate that cannot be satisfied must not become an infinite
loop paid for by the round: a small cap of attempts, then the unit fails as it
does today. The last output belongs in the unit's history, not only in the tick
log, so the next person sees the reason where they look for reasons.

## What must not happen

`--no-verify` is not a fallback. Neither is committing a subset of files to dodge
a hook, nor disabling a hook for the run. The gate is the repo's own standard and
the reason the pipeline can push unattended at all; a unit that cannot satisfy it
should stop, and say why.

The fix round must also not be allowed to rewrite the work into something
different. It exists to satisfy the gate on the work that already exists —
wrapping a line, sorting imports, adding a type — and the prompt says so, rather
than inviting a second attempt at the task.

## Why not fix the hook order instead

The immediate cause of the failure that prompted this was a hook chain that
lints before it formats, so a line the formatter would rewrap fails the linter
first. That ordering is worth correcting in the repo that had it, and has been.

But it is one instance of a general shape: gates reject, and some rejections are
fixable by whoever wrote the code. A pipeline that ends a unit on the first such
rejection will keep finding new instances — a type error the agent could resolve
in one edit, a docstring rule, a naming convention. The ordering fix removes one
cause; this removes the class.
