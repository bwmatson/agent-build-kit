"""The files that set a quality bar, with the key paths of each that do (none: the whole file).

A file protected whole is a protected path; a keyed one is judged at the verdict, by comparing
those key paths before and after. The ecosystems' file names live here, beside the profiles.
"""

from __future__ import annotations

PROTECTED_CONFIG_DEFAULTS: dict[str, tuple[str, ...]] = {
    "**/pyproject.toml": (
        "tool.pytest",
        "tool.ruff",
        "tool.pyrefly",
        "tool.coverage",
        "tool.complexipy",
        "tool.mutmut",
    ),
    "**/package.json": (
        "scripts.test",
        "scripts.lint",
        "scripts.typecheck",
        "scripts.format:check",
        "jest",
        "vitest",
        "eslintConfig",
    ),
    "**/setup.cfg": ("tool:pytest", "flake8", "coverage:run", "coverage:report"),
    "**/tox.ini": ("pytest", "flake8"),
    **{
        pattern: ()
        for pattern in (
            "**/.jscpd.json",
            "**/ruff.toml",
            "**/.ruff.toml",
            "**/pyrefly.toml",
            "**/pytest.ini",
            "**/.coveragerc",
            "**/.flake8",
            "**/.pre-commit-config.yaml",
            "**/eslint.config.*",
            "**/.eslintrc*",
            "**/biome.json",
            "**/biome.jsonc",
            "**/.oxlintrc.json",
            "**/vitest.config.*",
            "**/vitest.workspace.*",
            "**/jest.config.*",
        )
    },
}
