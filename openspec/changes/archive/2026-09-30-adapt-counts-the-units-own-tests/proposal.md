# Proposal

## Why

The adapt step requires a decision for every test "the unit's previous work added or changed",
and `_tests_added` derives that set by running `git diff <old base>..<old head>` and pulling
`def test_…` names out of the diff's **text** with a regular expression.

A diff is not a list of changes. It is hunks, and a hunk carries context lines either side of
every edit. So a test function that merely sits within three lines of something the unit touched
is collected as a test the unit added — and then the agent is required to decide its fate, on
pain of the unit failing.

That is not hypothetical. `github-native-stacks/1` was failed for giving `no decision for
test_a_failed_restack_keeps_the_review_feedback_already_waiting`. That test was introduced by
`2d894dc`, one of the framework's first commits, has nothing to do with stacks, and was present
and unchanged on the branch and on main. It was in the list because it neighbours a line the unit
edited.

The failure mode compounds: the larger the unit's diff, the more unrelated test names are swept
in, the longer the list, and the more likely one is omitted. A unit is then discarded for failing
to account for a test it never wrote.

## What Changes

- **The unit's own tests are identified from the changes, not from the diff's text.** Git can say
  which lines a commit range added and which file they are in; a test whose definition line is not
  among them was not added by this unit.
- **A test the unit changed still counts.** The point of the accounting is to catch work that
  quietly disappeared or was weakened, so a test whose body the unit edited stays in scope; what
  leaves is the test that was only ever nearby.
- **The list is reported when it matters.** When the accounting fails, the recorded problems name
  the tests still outstanding — and with a list free of passengers, that message becomes something
  an operator can act on rather than a haystack.

## Impact

- **agent-build-kit**: how the unit's tests are derived, in one function.
- Shorter, correct accounting lists: fewer decisions asked for, and none about tests the unit never
  touched.
- Together with its predecessor — which asks only about tests that went missing or changed — the
  adapt step's ask becomes small enough that omitting an item is a real signal rather than an
  accident of diff size.
