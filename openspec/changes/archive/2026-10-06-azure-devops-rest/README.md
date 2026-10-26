# azure-devops-rest

Azure DevOps is reached over typed REST through the framework's transport instead of
`az` subprocesses, with hand-written pydantic models, bounded-concurrency reads in one
process, and the pull-request listing no longer costing several subprocesses per open
pull request per poll.
