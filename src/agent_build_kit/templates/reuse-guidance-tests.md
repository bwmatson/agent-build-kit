**Reuse before you write tests.** Search for an existing test helper, fixture or case before adding one, and use or extend it. Look in the test runner's usual places for fixtures and test support, and read what the neighbouring tests import. Where a new case goes follows the placement rule stated in the tests prompt; it is not repeated here.

Parametrise cases that differ only in data (T21) instead of writing one test per value. Keep one shared fixture or helper per need in the shared test support, and move a helper needed in a second file there instead of copying it (T8a, T21); the same setup block in several files is a missing fixture. Name a test file for its subject, not for the change or for a flake that prompted it.

Never write a test whose subject is another test or a test helper (T22): a changed test is re-run by the repeat check, which already covers it.

Stay within the change: do not rewrite unrelated tests, and say in your summary when reuse needs a larger refactor so it can be recorded.
