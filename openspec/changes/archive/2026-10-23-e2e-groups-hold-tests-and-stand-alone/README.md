# e2e-groups-hold-tests-and-stand-alone

An `[e2e-test]` group is never joined with another group into a unit (today a plain one can be: `consumer-intake-live-tests-run-on-the-current-gateway`
units `/1` and `/3` each hold groups 1, 2 and 3), and it holds tests, test support, docs and the changelog and no product code. A defect a live test
finds in product code is not fixed in the e2e unit: the builder reports it in a structured `product-defect` block, the pipeline writes a
`fix-product-defect-<test>` change (one `[unit-test]` group: reproduce with a unit test, then fix; priority of the e2e unit; one change per test however
many units meet it), the e2e unit is parked failed-waiting on it and is requeued by the pipeline when the fix is in review, the way a unit behind a
`fix-failing-*` change is. A build-time guard stops an e2e unit whose diff changes product code and hands it the same path; `abk tags` and `abk check`
warn when a task names a product path in an e2e group; a `Support:` line declares the rare non-test support file. A defect in the unit's own test is
still reworked in place. All groups priority 2. Follow-up listed, not done: the `test-only` definition of `a-test-only-group-commits-no-pair`.
