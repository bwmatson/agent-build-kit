## Why

`tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded` failed under load and passed alone, twice, when run again by itself. A test like that fails units that did not touch it.

It ran as `uv run pytest -n auto --maxprocesses=8 -m '(not integration and not local_stack) and not serial' -q` and failed with:

```
ackages/httpx/_client.py", line 868, in stream
    response = self.send(
        request=request,
    ...<2 lines>...
        stream=True,
    )
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpx/_client.py", line 914, in send
    response = self._send_handling_auth(
        request,
    ...<2 lines>...
        history=[],
    )
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpx/_client.py", line 942, in _send_handling_auth
    response = self._send_handling_redirects(
        request,
        follow_redirects=follow_redirects,
        history=history,
    )
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpx/_client.py", line 979, in _send_handling_redirects
    response = self._send_single_request(request)
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpx/_client.py", line 1014, in _send_single_request
    response = transport.handle_request(request)
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpx/_transports/default.py", line 250, in handle_request
    resp = self._pool.handle_request(req)
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_sync/connection_pool.py", line 256, in handle_request
    raise exc from None
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_sync/connection_pool.py", line 236, in handle_request
    response = connection.handle_request(
        pool_request.request
    )
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_sync/connection.py", line 101, in handle_request
    raise exc
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_sync/connection.py", line 78, in handle_request
    stream = self._connect(request)
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_sync/connection.py", line 124, in _connect
    stream = self._network_backend.connect_tcp(**kwargs)
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_backends/sync.py", line 207, in connect_tcp
    with map_exceptions(exc_map):
         ~~~~~~~~~~~~~~^^^^^^^^^
  File "/home/<redacted>/.local/share/uv/python/cpython-3.14.6-linux-x86_64-gnu/lib/python3.14/contextlib.py", line 162, in __exit__
    self.gen.throw(value)
    ~~~~~~~~~~~~~~^^^^^^^
  File "/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/.venv/lib/python3.14/site-packages/httpcore/_exceptions.py", line 14, in map_exceptions
    raise to_exc(exc) from exc
httpcore.ConnectError: [Errno 111] Connection refused
----------------------------------------
=========================== short test summary info ============================
FAILED tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded
1 failed, 5267 passed in 149.79s (0:02:29)

warning: `VIRTUAL_ENV=/home/<redacted>/<redacted>/.venv` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead
```

It exercises `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/src/agent_build_kit/config.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/src/agent_build_kit/replay/models.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/src/agent_build_kit/replay/store.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/tests/replay/fake_upstream.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/tests/replay/proxy.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/tests/replay/support.py`, `/home/<redacted>/.local/share/<redacted>/worktrees/agent-build-kit/spec_tier2_replays_unchanged_calls_2/tests/waiting.py`.

Times it flaked:

- 2026-10-10 19:58 UTC, unit tier2-replays-unchanged-calls/2 (this one)

## What Changes

- `tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded` is made deterministic, whether the fault is in the test or in the code it exercises.

## Impact

- agent-build-kit: the test and, if it is the racy one, the module it exercises.
