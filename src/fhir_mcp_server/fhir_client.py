"""
Thin async HTTP client for FHIR R4.

FHIR (Fast Healthcare Interoperability Resources) defines a RESTful API where
every piece of clinical data is a typed "resource" (Patient, Observation, etc.)
addressable at /{ResourceType}/{id}. Searches follow standard query-string
conventions: GET /{ResourceType}?param=value.

This module owns all network I/O so the MCP tool layer stays focused on
shaping inputs and outputs, not HTTP mechanics.
"""

import os
from typing import Any

import httpx

FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "https://hapi.fhir.org/baseR4")

# The FHIR media type tells the server we want JSON-encoded FHIR, not plain JSON.
_HEADERS = {"Accept": "application/fhir+json"}


async def read_resource(resource_type: str, resource_id: str) -> dict[str, Any]:
    """GET /{resource_type}/{resource_id} — returns the resource or raises HTTPStatusError."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{FHIR_BASE_URL}/{resource_type}/{resource_id}",
            headers=_HEADERS,
        )
        response.raise_for_status()
        return response.json()


async def search_resources(
    resource_type: str, params: dict[str, str]
) -> dict[str, Any]:
    """GET /{resource_type}?params — returns a FHIR Bundle (searchset) or raises HTTPStatusError."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{FHIR_BASE_URL}/{resource_type}",
            params=params,
            headers=_HEADERS,
        )
        response.raise_for_status()
        return response.json()
