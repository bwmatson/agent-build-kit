# tier2-failures-in-untouched-tests-are-fixed-once

An e2e-test run that fails in a test the unit did not add or change no longer charges the unit for it. Each failed test is classified: one the
unit's branch added or changed fails the unit as today; one it left alone is run once on the base in a clean worktree. If it fails there too
it is a pre-existing failure, recorded, given one fix change per test id (previewed first, so a second unit finds the first one's change instead
of writing another), and the unit waits for that fix and resumes at e2e-test when it merges. If it passes on the base, the unit broke it and
fails as today. The stored feedback of a failed unit no longer carries the output of tests it did not touch into a rework prompt.
