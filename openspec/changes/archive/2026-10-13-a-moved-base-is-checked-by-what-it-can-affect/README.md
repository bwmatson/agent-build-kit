# a-moved-base-is-checked-by-what-it-can-affect

After a clean move onto a new base, the local tier 1 no longer runs the whole suite. It runs the tests the move can affect: the tests the
unit added or changed, the tests that run the code the move brought in, and the tests that run the files the unit changes, chosen through the
toolchain profile's existing selection hook. A resolved conflict, a changed diff, or a move that brought in a file the unit also changed keeps
the full suite. A failure in the scoped run is rerun alone before the unit is held, so a flake on the moved base costs nothing. The full suite
stays in CI on every pull request and before every merge. A setting, `limits.restack_check`, restores today's full run.
