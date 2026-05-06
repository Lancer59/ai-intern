"""Shared pytest configuration."""

def pytest_configure(config):
    config.addinivalue_line("markers", "browser: marks tests that require a live browser and running server")

