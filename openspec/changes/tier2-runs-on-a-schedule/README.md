# tier2-runs-on-a-schedule

An e2e-test unit no longer runs the whole live-stack suite. By default it runs only the e2e-test tests its branch added or changed, and a unit that
adds or changes none runs no e2e-test and says so. The whole suite runs on a schedule instead (weekly by default, daily, monthly or never), as an
ordinary tracked unit: the pipeline writes a `scheduled-e2e-<repo>-<date>` change when one is due, its unit builds nothing, runs the full suite on
the default branch under the usual lock and usage rules, and a failure goes through the existing record, one fix change and park. Two settings, each set per repo under `repos.<name>.tests` with a global default under `limits` that the repo overrides:
`e2e_unit_scope` (`own` or `full`) and `e2e_schedule` (`weekly`, `daily`, `monthly` or `off`).
