## From `acp-policy-covers-global-option-spellings/2`

- tests/cli/test_init_policy_spellings.py:24 — The test calls `recognised_planning(tmp_path / "planning")` a second time only to get back the path that `loosened` already built. Doing so rewrites the planning repo's pyproject.toml after init has run.
