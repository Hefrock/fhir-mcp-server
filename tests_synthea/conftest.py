"""
Fixtures for end-to-end smoke tests against a live fhir-synthea-lab endpoint.

These tests are DELIBERATELY separated from ``tests/`` so the unit-test mocking
fixtures (``mock_fhir``, the autouse ``_isolate_client``) do not apply here —
we want real HTTP against a real HAPI FHIR server.
"""

import asyncio
import os

import pytest


def pytest_collection_modifyitems(config, items):
    """
    Skip the entire smoke module when FHIR_BASE_URL is not set.

    Running `pytest tests_synthea/` without a live endpoint would produce
    confusing connection errors; instead we skip with a clear reason.
    """
    if os.getenv("FHIR_BASE_URL"):
        return
    skip = pytest.mark.skip(
        reason="FHIR_BASE_URL not set — smoke tests need a live endpoint"
    )
    for item in items:
        item.add_marker(skip)


@pytest.fixture(scope="session")
def event_loop():
    """
    Session-scoped event loop so the pooled httpx client persists across tests.
    Individual test coroutines share one loop and one connection pool.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
