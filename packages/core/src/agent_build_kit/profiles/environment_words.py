"""The ecosystem words the environment signs read: what a package feed failure looks like, the
files that decide a feed or a toolchain, and the executables a machine is expected to have.

Data only. The sign table (`pipeline/environment_signs.py`) reads them, so the framework code
itself names no package manager."""

from __future__ import annotations

# A line of a failed install or restore that says the package feed did not answer.
FEED_FAILURE = (
    r"npm (?:ERR!|error) code (?:E401|E403|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNRESET|ECONNREFUSED)"
    r"|ERR_PNPM_(?:META_)?FETCH\w*|NU1301"
    r"|Failed to (?:fetch|download)\b[^\n]*https?://|Could not fetch URL https?://"
)

# File names (any folder, any case) whose change makes a feed failure the unit's own.
FEED_INPUT_NAMES = (
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "packages.lock.json",
    ".npmrc", ".yarnrc", ".yarnrc.yml", "global.json", "uv.toml", "nuget.config",
    "pip.conf", "Directory.Packages.props",
)  # fmt: skip

# File names (any folder, any case) whose change makes a missing-tool failure the unit's own.
TOOLCHAIN_INPUT_NAMES = (
    ".tool-versions", "mise.toml", ".mise.toml", ".nvmrc", ".node-version", ".python-version",
    "global.json",
)  # fmt: skip

# Executables the machine provides, whose absence is the machine's.
MACHINE_TOOLS = (
    "uv", "uvx", "node", "npm", "npx", "pnpm", "yarn", "corepack",
    "dotnet", "git", "gh", "az", "docker", "python3",
)  # fmt: skip
