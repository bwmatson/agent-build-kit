# github-native-stacks

Register the stacks the pipeline already builds as stacks the code host knows
about, so a reviewer sees one ordered series instead of six unrelated pull
requests and can merge the lot in one action.

The pipeline has stacked pull requests since it began — a unit's pull request
targets its predecessor's branch — but the host shipped first-class stacks as an
explicit object, and branch-chained pull requests are not one. Registering them
is one API call per unit; nothing about how the pipeline builds or rebases needs
to change.
