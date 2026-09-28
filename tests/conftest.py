def pytest_itemcollected(item):
    """Use the test docstring as its title in pytest output."""
    doc = getattr(item.obj, "__doc__", None)
    if doc:
        item._nodeid = doc.strip()
