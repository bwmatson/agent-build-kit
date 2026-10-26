# Design

## The two limits

The plugin that enforces the per-test limit reads one option today and applies it to every test. It gains a second, for tests that carry
the tier-2 marker, and picks one per test: a test with the marker gets the tier-2 limit, any other test the existing one. The marker is the
one the project already names for tier 2 (`local_stack`), so a test is not put in a different class by anything but the marker it already
carries for the pipeline's own tier-2 selection.

The tier-2 limit is thirty minutes by default, per phase as the existing one is: a build with a real agent runs for minutes, and a tick
inside a module-scoped fixture is charged to the setup of the first test that uses the fixture. Thirty minutes is well over the longest
tier-2 run seen (about twenty-three minutes for the whole command, which holds several tests) and short enough that a hung agent fails
within the pipeline's own time limit for a command. Zero turns the tier-2 limit off, as zero does for the existing one.

## What a failure says

The message names the limit that was passed and which kind it was ("test exceeded the tier-2 time limit of 1800 seconds"), so a hang in a
live test is not mistaken for a slow fast test, and the existing message for the fast suite stays as it is.

## What does not change

The pipeline's tier-2 command, its environment and the result it posts. The sixty-second limit for every other test and its option. The
limit on the whole command, which is a separate setting.

## Unverified

Whether thirty minutes covers every tier-2 test on a slow day: it is a default, set by an option, and the report of tier-2 durations
(`unit-timeline-is-recorded`) will show whether it is right.
