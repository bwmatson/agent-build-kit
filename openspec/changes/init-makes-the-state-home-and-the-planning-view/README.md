# init-makes-the-state-home-and-the-planning-view

In the in-repo mode `abk init` creates the planning home's `state/` folder and the ignored link `<repo>/.planning -> <planning home>/state`, so the pipeline's state is browsable in the folder a person already has open. `abk doctor` reports a missing, dangling or wrong link. Both warn, and `init --yes` refuses, when the state directory would sit inside the repository.
