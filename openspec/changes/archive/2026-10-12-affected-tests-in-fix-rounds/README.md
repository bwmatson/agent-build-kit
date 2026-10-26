# affected-tests-in-fix-rounds

After a failed check, the fixer's next check runs only the tests the change affects, on any stack that can say which they
are, and the full suite still runs once before review. Off by default; a repo opts in.
