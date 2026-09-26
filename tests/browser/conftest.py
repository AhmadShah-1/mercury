"""Browser flows drive an external loopback server and never touch the pytest database."""

import pytest


@pytest.fixture(autouse=True)
def clean_database():
    """Override the suite-wide truncation fixture: these tests don't use the test database."""
    yield
