# join-small-sequential-units

When a new change is planned, the planner looks at every unit that has not
started — the new change's and those already planned — while it works out
dependencies. Where two of them are in the same repo, touch the same code, form
a straight line with nothing branching off, and are small enough together, they
become one unit and one pull request instead of two stacked ones. Work that has
started or finished is never touched.
