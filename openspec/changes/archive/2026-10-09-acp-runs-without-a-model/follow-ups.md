## From `acp-runs-without-a-model/1`

- tests/graph/test_nodes_without_a_model.py: test_over_the_claude_code_runtime_a_node_runs_on_the_model_for_its_role runs through StandInRuntime rather than the real Claude Code runtime, so it only shows that build_run passes each role's model from models() through unchanged. That is enough for task 1.2. The name promises more than the test checks: rename it (e.g. '..._a_runtime_that_names_its_models_gets_the_model_for_each_role'), or drive the real runtime's command line.
