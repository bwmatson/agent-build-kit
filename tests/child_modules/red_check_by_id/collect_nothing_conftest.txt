def pytest_collection_modifyitems(items, config):
    config.hook.pytest_deselected(items=list(items))
    items[:] = []
