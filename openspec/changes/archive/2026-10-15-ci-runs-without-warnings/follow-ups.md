## From `ci-runs-without-warnings/1`

- tests/ci_workflows.py:66 — Runner messages now print the whole label list as a Python repr. For example, `runs-on: ubuntu-latest` gives "runner ['ubuntu-latest'] floats" instead of naming the label that floats.

## From `ci-runs-without-warnings/2`

- Task 2.4 asked for two results to be recorded. First, no other test raises the serializer warning: the full suite ran with 0 'Pydantic serializer' lines. Second, it is still not checked whether a production path puts a list in a tuple field. The design's UNVERIFIED note should say exactly this in the planning repo. The builder has not checked where `invoke` and `__start__` build the state, so a later unit should read those paths before the note is closed.
