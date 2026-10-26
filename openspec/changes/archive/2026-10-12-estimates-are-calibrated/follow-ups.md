## From `estimates-are-calibrated/1`

- tests/pipeline/test_unit_size_calibration.py: in test_a_round_that_plans_other_groups_leaves_a_started_units_figure, plan_all never calls _record_calibration on the running unit feature/1, because it is neither in the plan nor a join target. So that test passes whether or not the unstarted guard exists. The guard is protected only by the direct set_calibration test above it. A variant where the round also replans the started unit (for example, a join onto it) would exercise the guard through plan_all.

## From `estimates-are-calibrated/2`

- `_join_raw` calls `_fitted` again, so the section is fitted twice for each prompt. A future `build_prompt` could call `_fitted` once and pass the kinds it keeps to both the section and the joining text. The output is correct either way.
