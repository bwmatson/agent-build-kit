# environment-is-language-independent

Makes the environment mechanism work for any programming language, not only the one it was first written for:
inputs become path patterns so a repository with many manifests and lock files can name them, a new `artifacts`
list names the dependency and build directories a sync produces so the pipeline owns them as it owns locks,
`abk init` detects the environment through the repository's toolchain profile (with a node profile beside the
python one), and the framework's own conventions say, and a repository check enforces, that framework code
outside profiles and init names no package manager or lock file.
