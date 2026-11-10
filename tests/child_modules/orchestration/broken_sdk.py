"""An SDK that is present but whose own dependency is missing."""

import importlib

importlib.import_module("azure_dependency_that_is_not_installed")
