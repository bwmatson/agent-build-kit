# acceptance-server-runs-in-the-scratch-environment

The acceptance tests that start the web UI's server inside the test process can now give the agents it starts the
scratch installation's environment instead of the test process's; a tier 2 test is allowed to start a real agent
(its guard against spawning one no longer applies to tests marked `local_stack`); and a failed tier 2 run keeps its
first errors: a short failure summary is requested, the full output goes to a file under the state directory, and the
result lists the first failure line of every failed or errored test ahead of any cut. The prerequisite of the failed
units `abk-web-ui/11` and `ui-chat-editing/5`, whose own tier 2 runs are the acceptance.
