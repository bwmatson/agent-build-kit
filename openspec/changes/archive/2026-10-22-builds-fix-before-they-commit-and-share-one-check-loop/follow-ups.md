## From `builds-fix-before-they-commit-and-share-one-check-loop/2`

- Earlier optional point 1.2 is still open. `check_round` could return a typed result that says whether the unit was parked, blocked or halted. Today `run_checks` and the stub loop work this out by checking whether the `checks_ok` key is present, and they rely on `halted` routing a held unit first. Changing it touches the `CheckLoop`/`check_round` contract that both loops use, so it belongs in a later unit.

## From `builds-fix-before-they-commit-and-share-one-check-loop/4`

- architecture.md step 3's closing clause 'in a build with `builders.per_group_commits` off as in a stubbed one' would read more plainly as 'whether or not the build is stubbed (a stubbed build runs them in its stub checks)'.
