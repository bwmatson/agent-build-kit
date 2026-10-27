# Design

## What was checked, and where

Read from `origin/main` (paths under the repository root), except `tests/test_marked_time_limit.py`, read from the open unit branch of `fix-flaky-tests-test-marked-time-limit-py-test-a-marked-test-8237727a` (in review, not merged), and cited as `branch:`.

### The time-limit tests

- `branch:tests/test_marked_time_limit.py`: `RECORDER` is the source of an autouse fixture `recording_timer` that replaces `threading.Timer` with a subclass recording each interval in a list `armed` (`:17-38`; `{fire}` at `:23` is the one `.format()` field). `READS_THE_LIMIT` (`:40-57`) and `BLOCKS` (`:59-71`) append test functions with `RECORDER.format(fire=False)` / `format(fire=True)`. Three tests (`:74`, `:85`, `:92`) pass a string to `run_child(tmp_path, SOURCE, "--test-time-limit=...", "--e2e-test-time-limit=...")`, imported from `tests/test_e2e_time_limit.py` (`:15`). No assertion depends on elapsed time: `READS_THE_LIMIT` reads `armed[-1]`; `BLOCKS` has the recorder fire the first timer of a test with a zero interval (`:35`) and the test then waits on an event that only the limit's signal ends (`:65`, `:69`).
- `tests/test_e2e_time_limit.py`: strings `INI` (`:20-24`), `SPIN` (`:26-36`), `SLOW_E2E` (`:38-82`), `HANGING` (`:84-96`), `SLOW_BOTH` (`:98-110`), `MARKED_E2E` (`:113-122`); `run_child` (`:125-146`) writes `pytest.ini` and `test_child.py` into the folder and runs `python -m pytest -p tests.time_limit -p no:cacheprovider -q ...` in a subprocess with `PYTHONPATH` set to the repository root (`:131-141`). Seven tests call it (`:152`, `:160`, `:169`, `:188`, `:198`, `:206`, `:215`); the test at `:178` reads the plugin's constants and runs no child. These scenarios use the wall clock on purpose (`spin(3)` against a limit of 1): the time limit is the thing under test, and the margin is a factor of three.
- **How the plugin is loaded.** The suite loads `tests.time_limit` through `pytest_plugins` in `tests/conftest.py:45-54`, together with `"pytester"` (`:46`). The child loads it with `-p tests.time_limit` (`tests/test_e2e_time_limit.py:133-134`), not through an entry point or a conftest, which is why the child needs the repository root on `PYTHONPATH` (`:141`): its rootdir is a temporary folder, where `pythonpath = ["."]` (`pyproject.toml:87`) does not apply.
- **Not collected by the repo's own runs.** `pyproject.toml:85` `testpaths = ["tests"]`; `python_files` is not set, so pytest's default `test_*.py` and `*_test.py` apply; `addopts` (`:101`) is `--strict-markers -m 'not integration and not local_stack'`; `tests/conftest.py` sets no `collect_ignore`. A folder under `tests/` is walked, and its `conftest.py` is loaded even when it holds no test, so the folder needs an ignore as well as names that do not match `test_*.py`.
- **Lint and type config.** `[tool.ruff]` (`pyproject.toml:62-67`: line length 100, `select = ["E","F","I","UP","B"]`, no `exclude`) and `[tool.pyrefly]` (`:69-82`: `project-includes = ["src", "tests"]`) cover every file below `tests/`; the pre-commit hooks `ruff-format`, `ruff` and `pyrefly-check` (`.pre-commit-config.yaml`) pass the changed Python files to them. A real file under `tests/child_modules/` is therefore linted, formatted and type-checked by the existing configuration, and nothing about them needs a new setting.

### Other guards that walk `tests/`

`tests/timing_hazards.py:185` walks every `*.py` under `tests/` for bare sleeps, unjoined threads and fixed ports (`SHARED_HELPERS`, `ALLOWLIST` at `:25-50`); `tests/test_test_helpers_defined_once.py` parses every module for copied helper bodies; `tests/test_repo_wide_guards_use_the_helper.py:74` fails a module that walks the checkout by hand and tells to use `tests/tracked_files.py` `guarded_files` (`:60`; it returns the tracked files, leaves planning content out and takes `under=` and `suffixes=`). The child modules must pass the first two: they hold no sleep, no `Thread` and no port (a recorder subclassing `threading.Timer` is not a `Thread` construction).

### Survey: tests that build a child's source as a string

A hand survey (a scan of every string constant in `tests/` for `def test_`, `def pytest_` and `@pytest.fixture`, crossed with the calls that run or collect it: `makepyfile`, `makeconftest`, `runpytest_inprocess`, `runpytest_subprocess`, `inline_genitems`, `subprocess` of `-m pytest`). Many other strings holding `def test_` are fed to an AST or text analyser and never run (`tests/pipeline/test_defined_tests_in_range.py:17-58`, `tests/pipeline/test_commit_order.py`, `tests/test_timing_guard.py`); those are not children.

| Module | Where the source is run or collected | Strings |
|---|---|---|
| `tests/test_marked_time_limit.py` (branch) | `run_child` `:75`, `:86`, `:93` | 3 (`:17`, `:40`, `:59`) |
| `tests/test_e2e_time_limit.py` | `run_child` def `:125-146` | 6 (`:20-122`) |
| `tests/test_time_limit.py` | `run_pytest` `:70-80`; `write_text` `:83`, `:96` | 2 (`:21-33`, `:36-67`) |
| `tests/test_e2e_time_split.py` | `makepyfile` `:74`, `runpytest_inprocess` `:75`, `inline_genitems` `:205` | 7 (`:18-176`) |
| `tests/scratch_dump_support.py` | `run_children` `:199-204` (`makepyfile` `:202`) | `PRELUDE` |
| `tests/test_scratch_dump.py`, `tests/test_scratch_dump_bounds.py` | through `run_children` (`test_scratch_dump.py:52`, `:79`, `:106`, `:139`, `:183`, `:217`, `:252`, `:326`; `test_scratch_dump_bounds.py:156`) | 7 and 1 |
| `tests/test_spawn_guards.py` | `makeconftest` `:162`, `makepyfile` `:165`, `runpytest_subprocess` `:166` | 5 |
| `tests/test_warning_filters.py` | `makepyfile` `:72`, `:83`, `:93`, `:143`, `:152`, `:160`; `runpytest_subprocess` `:62`, `:129` | 5 |
| `tests/test_openspec_cli_probe.py` | `makeconftest` `:134`, `:146`; `makepyfile` `:135`, `:147`; `runpytest_inprocess` `:137`, `:149` | 3 |
| `tests/replay/support.py`, `test_replay_label.py`, `test_replay_plugin.py`, `test_replay_proxy_lifetime.py`, `test_replay_unit_build_tier.py` | `makepyfile` `support.py:124`, `runpytest_inprocess` `support.py:125`, `makeconftest` `test_replay_label.py:75`, `runpytest_inprocess` `test_replay_unit_build_tier.py:82` | 6 |
| `tests/profiles/test_python_uv_e2e_durations_real_pytest.py`, `..._summary_real_pytest.py` | `makepyfile` `:34` / `:47`, `runpytest_subprocess` `:36` / `:50` | 1 and 3 |
| `tests/live_tag_drift.py`, `tests/runtime_tag_collection.py` | `makepyfile` `live_tag_drift.py:395`, `inline_genitems` `:396`; `collect` `runtime_tag_collection.py:25-40` | helpers |
| their users: `tests/test_runtime_tag_rule.py`, `test_runtime_tag_agrees_with_start.py`, `test_agent_start_signals.py`, `test_live_tests_across_dimensions.py`, `test_claude_without_acp_gap_list.py`, `test_live_tests_use_shared_tick.py` (`makepyfile` `:115`, `makeconftest` `:116`) | through those helpers | about 25 |

That is about 25 modules, 2 of them (the first two rows) the subject of this change. Counting differs by what a "module" is (helper and users), so the guard's own detector, not this table, fixes the allow-list; the table is the expected content (the build lists what the detector finds and checks it against this table).

`pytester` is already how most of them run: `"pytester"` is a plugin of the suite (`tests/conftest.py:46`), and `runpytest_subprocess` / `runpytest_inprocess` are used by the modules above. `Pytester.copy_example` copies a file or a folder from the directory named by the `pytester_example_dir` ini key (read relative to the rootdir) into the test's directory, so the key is the only addition; I ran it in a scratch project under the repository's environment: a copied conftest-and-module scenario ran as a `runpytest_subprocess` child with `-p tests.time_limit`, failed the blocking test with "test exceeded the time limit of 1 seconds", and the test took under a second. Ruff reported nothing and pyrefly no error on a recorder written as below.

## Decisions

### The form: real files run through `pytester` (a and b together)

The brief's two forms are not alternatives: `pytester` is how a child is started and isolated (its own temporary directory as the working directory, a clean `HOME`, `PYTEST_ADDOPTS` unset, the plugin loaded with `-p`), and it has no way of holding the child's code except as strings (`makepyfile`) or as files copied from an example folder (`copy_example`). Files are the only form ruff and pyrefly check.

- **Why not `makepyfile` with a function body** (`pytester.makepyfile(inspect.getsource(fn))`)? It checks the code, but a child's helper functions, module-level names and imports would all have to be inside the function or repeated; it still copies source text, and a debugger shows the temporary copy.
- **Why not in-process** (`runpytest_inprocess`)? The plugin raises its failure from a signal handler in the main thread and the recorder replaces `threading.Timer` for the whole process; in-process, the outer run's own time limit and the child's would share both. `runpytest_subprocess` keeps what `run_child` has today, one interpreter per child, at the same cost (about a second each; the experiment above took 0.9 s). `tests/replay/support.py:14` shows what in-process runs need for module state.
- **`-n auto`.** `pytester` is used under `poe test` (`pytest -n auto --maxprocesses=8`, `pyproject.toml:109`) by the modules above, and each test has its own directory, so the children do not share files. The repeat check below proves it for the converted tests.

### The layout

```
tests/child_modules/
  marked_time_limit/        conftest.py  pytest.ini  reads_the_limit.py  blocks.py
  fast_and_e2e_time_limit/  conftest.py  pytest.ini  slow_e2e.py  hanging.py  slow_both.py  marked_e2e.py
```

- File names never match `test_*.py`, so the repo's own pytest run does not collect them even if the folder were walked; the module to run is passed as an argument, and a file named on the command line is collected whatever its name. Child ids therefore read `reads_the_limit.py::test_marked_runs_past_the_default` (the assertions change from `test_child.py::...`).
- `tests/conftest.py` gains `collect_ignore_glob = ["child_modules/*"]`, so the folder's `conftest.py` files are not loaded by the repo's own run either. Collection is checked by a test, not assumed.
- `pyproject.toml` `[tool.pytest.ini_options]` gains `pytester_example_dir = "tests/child_modules"`. Tool config stays in `pyproject.toml`.
- The child's `pytest.ini` (the markers `local_stack` and `time_limit` its tests use, which `INI` held in a string at `tests/test_e2e_time_limit.py:20-24`) is a real file in each scenario folder, copied with it.
- **Shared names are fixtures, not imports.** A scenario folder has no `__init__.py` and pyrefly's `search-path` is `["src", "."]`, so a sibling `import recorder` would not resolve for the checker. The recorder and `spin` are therefore fixtures in the folder's `conftest.py` and the child tests ask for them by name (`def test_x(armed)`, `def test_y(spin)`), which pytest and the type checker both accept.
- `tests/test_marked_time_limit.py` and `tests/test_e2e_time_limit.py` keep their test names; the strings and `run_child` go. Test basenames stay unique (the child files carry distinct names, and the helper is `tests/child_pytest.py`).

### The helper

```
class ChildRun(Frozen):            # agent_build_kit.model.Frozen, as tests/tracked_files.py uses
    code: int
    output: str                    # stdout and stderr joined

def run_scenario(pytester, scenario: str, module: str, *args: str, env: Mapping[str, str] = {}) -> ChildRun
```

`run_scenario` copies `tests/child_modules/<scenario>` with `pytester.copy_example(scenario)`, sets `PYTHONPATH` to the repository root and each of `env` through the test's `monkeypatch` (the subprocess inherits the environment; `Pytester.runpytest_subprocess` prepends its working directory to `PYTHONPATH` and keeps the rest), and calls `pytester.runpytest_subprocess("-p", "tests.time_limit", "-p", "no:cacheprovider", "-q", module, *args)`. It returns the exit code and the output (`stdout.str() + stderr.str()`). It takes `pytester` and a `MonkeyPatch` the caller owns; it does not import the suite's other helpers.

### Parameters that `.format()` carried

`{fire}` becomes the environment variable `CHILD_FIRE_FIRST_TIMER=1`, read once by the scenario's `conftest.py`; `run_scenario(..., env={"CHILD_FIRE_FIRST_TIMER": "1"})` is the blocking scenario, no `env` the reading one. Limits stay command-line options. Nothing is formatted into a source again.

The recorder, as a file ruff and pyrefly accept (it ran clean in the experiment):

```python
REAL_TIMER = threading.Timer
FIRE_FIRST_VARIABLE = "CHILD_FIRE_FIRST_TIMER"
FIRE_FIRST = os.getenv(FIRE_FIRST_VARIABLE) == "1"

@pytest.fixture(autouse=True)
def armed(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    intervals: list[float] = []
    class Recording(REAL_TIMER):
        def __init__(self, interval: float, *args, **kwargs) -> None:
            first = not intervals
            intervals.append(interval)
            super().__init__(0 if FIRE_FIRST and first else interval, *args, **kwargs)
    monkeypatch.setattr(threading, "Timer", Recording)
    yield intervals
```

### Determinism

The recorder's behaviour is the one the unit branch builds: a test reads the interval the hook armed (`armed[-1]`), and the blocking test is ended by the first timer firing at zero. A new meta-test over the scenario files of `marked_time_limit/` parses them (`ast`) and fails on an import of `time`, on `sleep`, `monotonic`, `perf_counter` or `time.time` calls, and on a `Timer` interval other than zero or the armed one; the assertions in `tests/test_marked_time_limit.py` name the intervals (`5000`, `7000`, `9000`, `1`, `20`), none an elapsed time. The `fast_and_e2e_time_limit/` scenarios keep their busy waits (they exist to test the limit against real time, with the margins they have); they are not covered by the meta-test, only by the repeat check. The repeat check is `for i in $(seq 20); do pytest -n auto --maxprocesses=8 tests/test_marked_time_limit.py tests/test_e2e_time_limit.py -q || break; done`, run by the person building and recorded in the pull request; the convertible tests are also run in parallel with the rest of the suite by `poe test`.

### Scope: two time-limit files now, a guard for the rest

About 25 modules is far over six, and the other ones are not all alike (several use `makeconftest`, in-process runs, `format()` of many fields, helpers shared by others). Migrating them here would be a large change with several review problems at once. So:

- `tests/test_marked_time_limit.py` and `tests/test_e2e_time_limit.py` (with `run_child`) move: they are the ones the unit branch just rewrote and the ones named in the request; `tests/test_time_limit.py`, with its own `run_pytest` and two strings, stays in the allow-list (it is the next in line).
- A guard, `tests/child_sources.py` (the detection) and `tests/test_child_pytest_sources_are_real_files.py` (its tests and the run over the real tree), fails a module that holds a string constant defining a test, fixture or hook (`def test_`, `def pytest_`, `@pytest.fixture` at the start of a line) and also calls a function that runs or collects a source: `makepyfile`, `makeconftest`, `runpytest`, `runpytest_inprocess`, `runpytest_subprocess`, `inline_run`, `inline_genitems`, `run_child`, `run_children`, `run_session`, `run_pytest`, `collected`, `drifted`, `collect`. It reads the files through `tests/tracked_files.py` `guarded_files(under=["tests"], suffixes={".py"})`, as the repo-wide-guards requirement says, and parses with `ast`. The modules it finds today are listed in `ALLOWED`, each with a reason ("migrate to tests/child_modules"), the way `tests/timing_hazards.py:25-50` lists its allowlist; the list may only shrink: a listed module that no longer matches fails the guard until its entry is removed, and a module not listed that matches fails naming `path:line`. The files under `tests/child_modules/` are exempt (they are the target form). Names such as `collect` are generic, so a false hit is fixed by an `ALLOWED` entry with its reason, never by loosening the detector.

## Risks

- `copy_example` takes the folder's `pytest.ini` and `conftest.py` into the child's directory; the child's rootdir is the temporary folder, so the repo's `pyproject.toml` options (`addopts`, `filterwarnings = ["error:Pydantic ..."]`) do not apply to a child, as today.
- `collect_ignore_glob` also hides the folder from a person running `pytest tests/child_modules`; that is intended (those files are not tests of the repo).
- A name in the detector is a name, not a type: a helper renamed to avoid it escapes the guard. The guard is a nudge for the common route, not a proof.
