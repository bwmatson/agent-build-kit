# Design

## Method

Each group is a refactor with no change in behaviour. Its first commit adds characterisation tests that pin what
the copies did today; its last adds the guard. A guard written before the move fails by design, so each group's
guard task comes after the move and is the group's last commit. Existing tests are not rewritten to fit the new
code, except to import a helper from where it now lives. A group that finds the copies differ in behaviour records
the difference and keeps the behaviour of the one used most, rather than choosing silently.

The cleanup applies to the framework's own repository, the one surveyed. Other repositories get the same sweep
later by the same method. The survey was repeated against the code as it stands now, and the scope below is what
it found.

## Paired calls

Six places make a telemetry call and then record the same metric locally with the same name, value and attributes:
the tick duration, two usage pauses, a rate-limit pause, the unit duration and the review rounds. They call one
helper. This is not every metric: the other telemetry calls (the forges' retries, the notifications, the usage
guard and ledger, the tier 2 times) have no local record on purpose and stay as they are, so there is no rule that a
metric is emitted only through the helper. The metrics page finds instruments by scanning the source for direct
`telemetry.<kind>("abk...")` calls with a literal name; a helper that takes the name hides them from it, so the
scan learns the helper's calls too and a test pins the four listed instruments. Guard: no function but the helper
calls the local record.

The two tier 1 failure sites that classify a failure twice, and may disagree (the second falls back to "unknown"),
classify it once and use the result for both. The open entries of the stack runner's answer are computed once and
passed to the list and the rendering.

## State files

The write-to-a-temporary-then-replace idiom is copied fourteen times, with variants: some name the temporary per
process, some take the file lock around it, one removes the temporary on any exception. The shared function takes
the safest of each (a per-process name, removal on any exception); the two that lock keep their lock around the
call. The reads are not unified: about twenty sites read a state file by hand and each tolerates a missing or
unparsable file differently, so one read would either change behaviour or take a parameter for each difference. They
stay. Landing the shared write first lets the planned lanes that add state files use it. Guard: no source module
outside the shared one replaces over a file from a temporary name.

## Shared helpers

The version-control command already has one runner: the shell module's, wrapped in one line by the restack module
(which adds the conflict-memory flags) and by the tracks runner. What is left are plain subprocess calls in the init
command, the commit gate and the scaffold, which move onto it. The detection in init, the verifier and the push
wiring take an injected runner so tests can fake it, a different seam, and stay. The restack module is not touched,
because the change that resolves a conflict in one session, without holding the repository lock, splits its move
function.

`Installation` already has the change directory. The callers that hold a root and a specs directory, not an
installation (the archive step, the proposal, the graph's planning setup, the init command), take it from a function
beside it. The host-address pattern, which two modules define identically, and the diff-hunk pattern, which three
do (the pipeline's wiring, the review server and the UI review), are each defined once and imported. Guard: no two
modules under `src/` define the same module-level compiled pattern; the tests' own copies of the placeholder pattern
are not guarded.

## The hosts

GitHub's file paths come from the call that lists the files with their line counts, which is made once. Azure DevOps
pages the newest iteration's changes and has no line counts, and the local forge has no listing, so there is
nothing to derive there and they stay. The three hosts page three different ways (a link header, a cursor, skip
and top), so there is no common loop; the one thing the parsing helpers share is the step that validates the body
and raises the transport error naming the endpoint, which becomes one helper.

Deferred: the check for a branch the host has moved, written twice (in the restack builder in the events module and
in the push builder in the wiring). The planned restack lane relocates and edits the first, and the one-session and
moved-base changes edit the second, so doing it now collides with them. It can be revisited after
`a-restack-takes-no-slot-and-runs-when-seen` group 1.

## Test support

The helpers copied identically are merged into the shared test modules: the five restack `commit` helpers, the two
fakes of the change tooling, the copies of `write_change` that write the same tasks file, and the tracks tests'
own installation builder (the shared one is in the root conftest). Commit helpers of other shapes (a tree and a
config, an HTTP call, a file map, a returned sha) are different helpers and stay, as do per-file fixtures such as
`inst` and `runner` whose bodies differ. Guard: the merged names are not defined elsewhere, and no two top-level
helpers share a name and a body; a name-only rule would fail on `commit`, `inst` and `runner`.

## Order

Groups 1 and 2 come first, before the changes that add new metric pairs and state files. They are independent of
each other and of the rest; group 3's code-host half touches nothing a planned change touches; group 4 is tests only
and is best done before the one-session change's first group, which adds tests that would otherwise copy the
commit helper again. The groups are written in a serial order because the file requires one, not because any
group needs another's code. Group 4 keeps its number because the flaky-test cleanup waits for it.
