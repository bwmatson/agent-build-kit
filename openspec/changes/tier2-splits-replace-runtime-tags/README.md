# tier2-splits-replace-runtime-tags

A repo says how its e2e-test runs are split and which splits are held, with no runtime involved: `tests.e2e_splits.<name>` names a subset of the repo's e2e-test tests by a
selector (a `marker` for the python profile), the tests in no split are the implicit `rest`, and a split is held by `hold` in the configuration, by `abk e2e-test hold` or by its gate, for
any reason (a metered backend, a host that is down, a licence server, a slow stack). This change migrates what `tier2-tests-are-tagged-by-runtime` has already built from runtimes to
splits: the three runtime lists become the split declaration, the blocked set becomes the held set (`e2e-held.json`), the selection, the exclusivity check, the parking, the record and
the scheduled changes carry a split, and `abk e2e-test check` finds a test that is in two splits. The kit's own `acp` and `claude_code` splits become installation configuration.
