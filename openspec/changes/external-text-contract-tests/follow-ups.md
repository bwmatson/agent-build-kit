## From `external-text-contract-tests/1`

- test_external_fixture_versions.py cannot check whether the installed `claude` CLI is a major version ahead of the recordings, because tests/conftest.py refuses to spawn `claude`, even for `--version`. A person could allow a `claude --version` probe in that guard, or pass the installed version in some other way, so that the claude recordings get the same staleness check as pytest and git.
- CHANGELOG.md: the edited red-check sentence leaves one line ('...ignoring stderr around it, and says in the log when it falls back to the console. Recorded output under') much longer than the lines around it. Re-wrapping it to the bullet's width would keep the entry even.
