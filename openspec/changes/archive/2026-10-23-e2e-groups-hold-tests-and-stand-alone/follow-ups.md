## From `e2e-groups-hold-tests-and-stand-alone/5-s1`

- The shared fix-change helpers (`preview_fix`, `ensure_fix_change`, `write_fix_change`, `wait_on_change`) now sit in `untouched_failures.py`, and `product_defect` imports them from there. Since they serve both kinds of fix change, they could move beside `open_fix_change`/`next_fix_name` in `flakes.py`, so that neither caller's module owns the other's protocol.
