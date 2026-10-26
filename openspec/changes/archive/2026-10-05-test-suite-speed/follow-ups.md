## From `test-suite-speed/1`

- docs/toolchain-profiles.md protocol table: add the `tolerates_exit(command, returncode)` row (tier 1; python-uv tolerates 5 only on the serial pass).
- python_uv._root_tests: recognise `pytest-xdist` in root_extras with `_DEP_NAME`/`_normalize`, so a version-pinned extra still gets the parallel passes.
- wiring.build_tier1's `ran` log: report a tolerated exit (the serial pass's 5) as passed, not `exit 5`.
- PR body: state how many repeated parallel runs passed (tasks 1.4/1.5). The builder reports two clean runs, not ten.
- docs/toolchain-profiles.md:38 — The protocol member table in docs/toolchain-profiles.md (lines 22–43) does not list the new `tolerates_exit(command, returncode)` member, although `profiles/base.py` now declares it and tier 1 calls it.
- src/agent_build_kit/profiles/python_uv.py:184 — `_root_tests` decides whether xdist is present with `extra.split("[")[0]`, so a root extra with a version specifier, such as `pytest-xdist>=3.6`, is not recognised. Everywhere else the profile uses `_DEP_NAME`.
- src/agent_build_kit/pipeline/wiring.py:550 — The tier 1 log line in `ran` reports a tolerated serial pass as `exit 5`, not as passed, because it checks `returncode == 0` rather than `tolerates_exit`.
