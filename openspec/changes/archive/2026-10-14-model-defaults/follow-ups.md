## From `model-defaults/1`

- In tests/test_runtime_selection.py, `test_another_runtime_s_models_are_not_sent_to_the_active_one` asserts `review == "opus"`. That is both the flat block's value and the claude_code default, so the test would still pass if the flat block were ignored. This was already true before this branch. Giving `FLAT_MODELS` a review name that is not a default would make the test tell the two apart.
