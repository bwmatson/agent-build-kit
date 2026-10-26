## From `test-the-habitat-and-the-parsers/1`

- docs/code-forges.md:35 still points at `cli/pipeline._build`. The rework renamed that function to `build_unit`, so change the table cell to `cli/pipeline.build_unit`.
- tests/runtimes/selectable.py:65 still does `monkeypatch.setitem(runtimes._REGISTRY, ...)`, which reaches a private name from test support. The new CLAUDE.md rule, "A test imports no private name", is about test modules and round 1 did not raise this file. The clean fix is a public register/unregister (or a context manager) on `runtimes` that test support can use. That is a small API decision best made in its own change.
