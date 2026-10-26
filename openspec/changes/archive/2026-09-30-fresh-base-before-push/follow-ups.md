## From `fresh-base-before-push/1`

- AzureDevOpsForge._base_missing treats any TF401398 as a missing base because the host does not say whether the source or the target is gone. This relies on the source having been pushed just before, and the docstring says so. If a later unit adds a single-PR state lookup to the Forge protocol (see the build_fresh_base docstring), the same lookup could confirm whether the target branch still exists before the error is read as BaseMissing.
- The tier-1-failure-after-clean-move path now has a same-run test with the usage window open. The tier 2 failure path after a clean move is still tested only with the window shut. A matching open-window test for tier 2 would pin the same review → tier → push → PR order.
