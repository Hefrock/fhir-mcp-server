"""
Thin async HTTP client for FHIR R4.

FHIR (Fast Healthcare Interoperability Resources) defines a RESTful API where
every piece of clinical data is a typed "resource" (Patient, Observation, etc.)
addressable at /{ResourceType}/{id}. Searches follow standard query-string
conventions: GET /{ResourceType}?param=value.

This module owns all network I/O so the tool layer stays focused on shaping
inputs and outputs, not HTTP mechanics.

Connection reuse
----------------
We keep a single module-level httpx.AsyncClient and reuse it across calls. A
fresh client per request would open and tear down a new TCP+TLS connection
every time — wasteful for a long-lived server. One pooled client keeps
keep-alive connections warm. The client is created lazily so importing this
module never touches the network or an event loop.
"""

import os
from typing import Any

import httpx

# Default points at the SMART R4 sandbox: an open, unauthenticated test server
# seeded with synthetic patients. Override with FHIR_BASE_URL for any R4 server.
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "https://r4.smarthealthit.org")

# Optional bearer token for FHIR servers that require authentication (e.g. Epic,
# Cerner, or Meditech sandboxes). When set, every outgoing request carries an
# Authorization: Bearer <token> header. Full SMART-on-FHIR OAuth is out of scope
# for this transport layer — obtain the token externally and pass it in.
FHIR_ACCESS_TOKEN = os.getenv("FHIR_ACCESS_TOKEN")

# The FHIR media type tells the server we want JSON-encoded FHIR, not plain JSON.
_HEADERS = {"Accept": "application/fhir+json"}

_client: httpx.AsyncClient | None = None


def _build_headers() -> dict[str, str]:
    """Assemble request headers, injecting the bearer token when configured."""
    headers = dict(_HEADERS)
    if FHIR_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {FHIR_ACCESS_TOKEN}"
    return headers


def _get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it on first use."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(headers=_build_headers(), timeout=30.0)
    return _client


async def aclose() -> None:
    """Close the shared client. Call on server shutdown to release sockets."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def read_resource(resource_type: str, resource_id: str) -> dict[str, Any]:
    """GET a single resource by type and id; raises HTTPStatusError on 4xx/5xx."""
    response = await _get_client().get(f"{FHIR_BASE_URL}/{resource_type}/{resource_id}")
    response.raise_for_status()
    return response.json()


async def search_resources(
    resource_type: str, params: dict[str, str]
) -> dict[str, Any]:
    """GET a search; returns a FHIR Bundle (searchset) or raises HTTPStatusError."""
    response = await _get_client().get(
        f"{FHIR_BASE_URL}/{resource_type}", params=params
    )
    response.raise_for_status()
    return response.json()


async def get_capability_statement() -> dict[str, Any]:
    """
    Fetch the server's CapabilityStatement from GET {FHIR_BASE_URL}/metadata.

    Every conformant FHIR server exposes this resource — it advertises the FHIR
    version, supported resource types, and security requirements. Used by the
    check_connection tool to sanity-check a new endpoint before running clinical
    queries.
    """
    response = await _get_client().get(f"{FHIR_BASE_URL}/metadata")
    response.raise_for_status()
    return response.json()


async def fetch_next_page(url: str) -> dict[str, Any]:
    """
    Fetch a pre-formed FHIR pagination URL.

    The URL must start with the configured FHIR_BASE_URL — this prevents the
    model from redirecting the client to an arbitrary external host.
    """
    if not url.startswith(FHIR_BASE_URL):
        raise ValueError(
            f"Pagination URL {url!r} does not match the configured "
            f"FHIR_BASE_URL {FHIR_BASE_URL!r}. Refusing to fetch."
        )
    response = await _get_client().get(url)
    response.raise_for_status()
    return response.json()
