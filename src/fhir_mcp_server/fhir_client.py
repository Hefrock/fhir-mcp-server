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
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

# Default points at the SMART R4 sandbox: an open, unauthenticated test server
# seeded with synthetic patients. Override with FHIR_BASE_URL for any R4 server.
FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "https://r4.smarthealthit.org")

# Optional bearer token for FHIR servers that require authentication (e.g. Epic,
# Cerner, or Meditech sandboxes). When set, every outgoing request carries an
# Authorization: Bearer <token> header. Full SMART-on-FHIR OAuth is out of scope
# for this transport layer — obtain the token externally and pass it in.
FHIR_ACCESS_TOKEN = os.getenv("FHIR_ACCESS_TOKEN")

# Optional human-readable label naming this backend (e.g. "SMART sandbox",
# "Synthea lab", "Epic PROD — real patient data"). When set, the label is
# prepended to the FastMCP `instructions` string and included in the
# check_connection output so the AI (and the user) can see which backend
# they're talking to. Purely informational — does not affect HTTP behaviour.
FHIR_SERVER_LABEL = os.getenv("FHIR_SERVER_LABEL")

# The FHIR media type tells the server we want JSON-encoded FHIR, not plain JSON.
_HEADERS = {"Accept": "application/fhir+json"}

# Largest page size any tool may request; also enforced on pagination URLs.
MAX_PAGE_SIZE = 50

# The FHIR R4 id grammar. Ids are placed in the URL path, so anything else
# (slashes, "?", "$operations", dot segments) could redirect the request.
_ID_RE = re.compile(r"[A-Za-z0-9\-.]{1,64}")

_DEFAULT_PORTS = {"http": 80, "https": 443}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

_client: httpx.AsyncClient | None = None


def validate_id(resource_id: str) -> str:
    """Return the id unchanged if it is a legal FHIR id; raise ValueError if not."""
    if not _ID_RE.fullmatch(resource_id) or resource_id in (".", ".."):
        raise ValueError(
            f"{resource_id[:80]!r} is not a valid FHIR resource id "
            "(letters, digits, '-' and '.', at most 64 characters)."
        )
    return resource_id


def _origin(url: str) -> tuple[str, str, int | None]:
    """(scheme, host, port) with the scheme's default port filled in."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or _DEFAULT_PORTS.get(
        scheme
    )


def _check_token_transport() -> None:
    """Refuse to send a bearer token over plain HTTP to a non-local host."""
    scheme, host, _ = _origin(FHIR_BASE_URL)
    if FHIR_ACCESS_TOKEN and scheme != "https" and host not in _LOOPBACK_HOSTS:
        raise ValueError(
            "FHIR_ACCESS_TOKEN is set but FHIR_BASE_URL is not HTTPS. "
            "Refusing to send a bearer token over an unencrypted connection."
        )


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
        _check_token_transport()
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
    validate_id(resource_id)
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


def _check_pagination_url(url: str) -> None:
    """
    Raise ValueError unless ``url`` points at the configured FHIR server.

    A string-prefix test is not enough: "https://host.evil.com" and
    "https://host@evil.com" both start with "https://host". We compare the
    parsed scheme, host and port exactly, forbid embedded credentials and dot
    segments, and require the path to sit at or under the base path.
    """
    refusal = (
        f"Pagination URL {url[:200]!r} does not match the configured "
        f"FHIR_BASE_URL {FHIR_BASE_URL!r}. Refusing to fetch."
    )
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None or "\\" in url:
        raise ValueError(refusal)
    if _origin(url) != _origin(FHIR_BASE_URL):
        raise ValueError(refusal)

    path = unquote(parts.path)
    if any(segment in (".", "..") for segment in path.split("/")):
        raise ValueError(refusal)
    base_path = urlsplit(FHIR_BASE_URL).path.rstrip("/")
    if path.rstrip("/") != base_path and not path.startswith(base_path + "/"):
        raise ValueError(refusal)

    for value in parse_qs(parts.query).get("_count", []):
        if not value.isdigit() or int(value) > MAX_PAGE_SIZE:
            raise ValueError(
                f"Pagination URL asks for _count={value[:20]!r}; "
                f"the maximum page size is {MAX_PAGE_SIZE}."
            )


async def fetch_next_page(url: str) -> dict[str, Any]:
    """
    Fetch a pre-formed FHIR pagination URL.

    The URL must point at the configured FHIR server (see
    ``_check_pagination_url``) — this prevents the model from redirecting the
    client, and any bearer token, to another host or endpoint.
    """
    _check_pagination_url(url)
    response = await _get_client().get(url)
    response.raise_for_status()
    return response.json()
