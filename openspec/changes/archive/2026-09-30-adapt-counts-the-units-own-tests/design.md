# Design

## What the current derivation actually matches

```python
diff = git(tree, "diff", old_base, old_head, "--", "*.py", check=False).stdout
return sorted(set(TEST_DEF.findall(diff)))
```

`findall` over the whole diff text sees added lines, removed lines and context lines alike, with
no way to tell them apart. Three consequences, in increasing order of harm:

- a test the unit **added** is matched — correct, and the intent;
- a test the unit **deleted** is matched, because the removed line is in the diff — which is
  wanted, since a deletion is exactly what the accounting exists to catch;
- a test that is merely **near** an edit is matched from a context line — wrong, and invisible.

The third is the bug. It has no upper bound: a unit that edits one line in a file of forty tests
can pick up several of them, and a unit with a 1600-line diff picks up many.

## Asking git instead of a regex

Git can answer this properly. A hunk header gives the line range a change occupies, and the
`+`/`-` prefixes distinguish added and removed lines from context. So the set wanted is: test
definitions on lines the range added, plus test definitions on lines it removed — and nothing
found only on context lines.

That is a small amount of parsing, and the alternative worth naming is `git log -L` or
`--function-context`, both of which answer a different question (what changed inside a function)
rather than this one (which function definitions the change introduced or deleted). The prefix
distinction is the whole of what is needed.

## Changed, not merely adjacent

There is a middle case that must stay in scope: a test the unit did not define but whose *body* it
edited. The accounting exists to catch a test that vanished or was weakened, and weakening a test
someone else wrote is the same risk as weakening your own. So a test counts when the range touched
a line inside it, and does not count when the range only touched lines near it.

That is the distinction a regex over diff text cannot make and a hunk-aware read can.

## Why this is a successor rather than the same change

Its predecessor narrows the question: of the tests the unit added, only those now missing or
changed by the replay need a decision. That is correct and independently valuable, and it assumes
the set of "tests the unit added" means what it says. This change makes that true.

Landing them in the other order would work too, but this way the narrowing is already in place when
the list becomes accurate, and the combined effect is visible in one step: an accounting list that
is both short and relevant.
