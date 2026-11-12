"""
Unit tests for fhir_client — the HTTP layer.

These tests verify that the client correctly:
  - constructs URLs and headers
  - deserialises JSON responses
  - propagates HTTP errors (4xx/5xx) as exceptions
"""

import httpx
import pytest
import respx

from fhir_mcp_server import fhir_client

from .conftest import (
    SAMPLE_CAPABILITY_STATEMENT,
    SAMPLE_OBSERVATION,
    SAMPLE_OBSERVATION_BUNDLE,
    SAMPLE_PATIENT,
    SAMPLE_PATIENT_BUNDLE,
)


class TestReadResource:
    async def test_returns_parsed_json(self, mock_fhir):
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        result = await fhir_client.read_resource("Patient", "example")
        assert result["resourceType"] == "Patient"
        assert result["id"] == "example"

    async def test_observation_read(self, mock_fhir):
        mock_fhir.get("/Observation/obs-hr-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION)
        )
        result = await fhir_client.read_resource("Observation", "obs-hr-1")
        assert result["resourceType"] == "Observation"
        assert result["valueQuantity"]["value"] == 72

    async def test_raises_on_404(self, mock_fhir):
        mock_fhir.get("/Patient/missing").mock(
            return_value=httpx.Response(
                404, json={"resourceType": "OperationOutcome", "issue": []}
            )
        )
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await fhir_client.read_resource("Patient", "missing")
        assert exc_info.value.response.status_code == 404

    async def test_raises_on_server_error(self, mock_fhir):
        mock_fhir.get("/Patient/boom").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        with pytest.raises(httpx.HTTPStatusError):
            await fhir_client.read_resource("Patient", "boom")


class TestSearchResources:
    async def test_returns_bundle(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await fhir_client.search_resources("Patient", {"family": "Smith"})
        assert result["resourceType"] == "Bundle"
        assert result["type"] == "searchset"
        assert result["total"] == 1

    async def test_observation_search(self, mock_fhir):
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        result = await fhir_client.search_resources(
            "Observation", {"patient": "example"}
        )
        assert len(result["entry"]) == 1
        assert result["entry"][0]["resource"]["code"]["coding"][0]["code"] == "8867-4"

    async def test_raises_on_bad_request(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(400, text="Bad Request")
        )
        with pytest.raises(httpx.HTTPStatusError):
            await fhir_client.search_resources("Patient", {"invalid_param": "x"})


class TestBearerToken:
    """FHIR_ACCESS_TOKEN, when set, must ride on every outgoing request."""

    def _capture_auth(self, store, json_body):
        def handler(request):
            store["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=json_body)

        return handler

    async def test_no_auth_header_when_token_unset(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/Patient/example").mock(
            side_effect=self._capture_auth(captured, SAMPLE_PATIENT)
        )
        await fhir_client.read_resource("Patient", "example")
        assert captured["auth"] is None

    async def test_bearer_header_added_when_token_set(self, mock_fhir):
        fhir_client.FHIR_ACCESS_TOKEN = "test-token-abc123"
        captured: dict = {}
        mock_fhir.get("/Patient/example").mock(
            side_effect=self._capture_auth(captured, SAMPLE_PATIENT)
        )
        await fhir_client.read_resource("Patient", "example")
        assert captured["auth"] == "Bearer test-token-abc123"

    async def test_bearer_header_on_search(self, mock_fhir):
        fhir_client.FHIR_ACCESS_TOKEN = "search-token"
        captured: dict = {}
        mock_fhir.get("/Patient").mock(
            side_effect=self._capture_auth(captured, SAMPLE_PATIENT_BUNDLE)
        )
        await fhir_client.search_resources("Patient", {"family": "Smith"})
        assert captured["auth"] == "Bearer search-token"


class TestCapabilityStatement:
    async def test_fetches_metadata_endpoint(self, mock_fhir):
        mock_fhir.get("/metadata").mock(
            return_value=httpx.Response(200, json=SAMPLE_CAPABILITY_STATEMENT)
        )
        result = await fhir_client.get_capability_statement()
        assert result["resourceType"] == "CapabilityStatement"
        assert result["fhirVersion"] == "4.0.1"

    async def test_raises_on_metadata_error(self, mock_fhir):
        mock_fhir.get("/metadata").mock(return_value=httpx.Response(503, text="down"))
        with pytest.raises(httpx.HTTPStatusError):
            await fhir_client.get_capability_statement()


BAD_IDS = [
    "../../admin/users",
    "123/_history",
    "123/$everything",
    "x?_id=1&_revinclude=*",
    "",
    ".",
    "..",
    "a b",
    "a%2Fb",
    "a#b",
    "a" * 65,
]


class TestResourceIdValidation:
    """Ids go into the URL path, so anything outside the FHIR id grammar is refused."""

    @pytest.mark.parametrize("bad_id", BAD_IDS)
    async def test_rejects_ids_outside_fhir_grammar(self, mock_fhir, bad_id):
        # No route is mocked: a request escaping would fail differently.
        with pytest.raises(ValueError):
            await fhir_client.read_resource("Patient", bad_id)
        assert not mock_fhir.calls

    @pytest.mark.parametrize("good_id", ["example", "A-1.b", "a" * 64])
    async def test_accepts_valid_ids(self, mock_fhir, good_id):
        mock_fhir.get(f"/Patient/{good_id}").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        result = await fhir_client.read_resource("Patient", good_id)
        assert result["resourceType"] == "Patient"


class TestPaginationGuard:
    """The next-page URL must be the configured server, not a lookalike."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://r4.smarthealthit.org.evil.com/Patient",
            "https://r4.smarthealthit.org@evil.com/Patient",
            "https://user:pw@r4.smarthealthit.org/Patient",
            "http://r4.smarthealthit.org/Patient",
            "https://r4.smarthealthit.org:8443/Patient",
            "https://r4.smarthealthit.org/Patient?_count=5000",
            "https://r4.smarthealthit.org/a/../b",
        ],
    )
    async def test_rejects_urls_off_the_configured_server(self, mock_fhir, url):
        with pytest.raises(ValueError):
            await fhir_client.fetch_next_page(url)
        assert not mock_fhir.calls

    @pytest.mark.parametrize(
        "url",
        [
            "https://r4.smarthealthit.org?_getpages=abc&_getpagesoffset=10&_count=10",
            "https://r4.smarthealthit.org:443/Patient?_count=50",
            "https://R4.SmartHealthIT.org/Patient?_getpagesoffset=10",
        ],
    )
    async def test_accepts_urls_on_the_configured_server(self, mock_fhir, url):
        mock_fhir.route().mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await fhir_client.fetch_next_page(url)
        assert result["resourceType"] == "Bundle"

    @pytest.mark.parametrize(
        "url",
        [
            "https://fhir.example.org/fhir.evil.com/Patient",
            "https://fhir.example.org/fhir/../admin/users",
            "https://fhir.example.org/fhir/%2e%2e/admin/users",
            "https://fhir.example.org/admin/users",
        ],
    )
    async def test_rejects_paths_outside_the_base_path(self, url):
        fhir_client.FHIR_BASE_URL = "https://fhir.example.org/fhir"
        with respx.mock(assert_all_called=False) as router:
            router.route().mock(return_value=httpx.Response(200, json={}))
            with pytest.raises(ValueError):
                await fhir_client.fetch_next_page(url)
            assert not router.calls

    @pytest.mark.parametrize(
        "url",
        [
            "https://fhir.example.org/fhir?_getpages=abc",
            "https://fhir.example.org/fhir/Patient?_getpagesoffset=10",
        ],
    )
    async def test_accepts_paths_under_the_base_path(self, url):
        fhir_client.FHIR_BASE_URL = "https://fhir.example.org/fhir"
        with respx.mock(assert_all_called=False) as router:
            router.route().mock(
                return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
            )
            result = await fhir_client.fetch_next_page(url)
        assert result["resourceType"] == "Bundle"


class TestTokenTransport:
    """A bearer token is never sent over plain HTTP to a remote host."""

    async def test_token_over_remote_http_is_refused(self):
        fhir_client.FHIR_BASE_URL = "http://fhir.example.org/fhir"
        fhir_client.FHIR_ACCESS_TOKEN = "secret"
        with respx.mock(assert_all_called=False) as router:
            router.route().mock(return_value=httpx.Response(200, json={}))
            with pytest.raises(ValueError, match="HTTPS"):
                await fhir_client.read_resource("Patient", "example")
            assert not router.calls

    @pytest.mark.parametrize(
        "base,token",
        [
            ("http://localhost:8080/fhir", "secret"),
            ("http://127.0.0.1:8080/fhir", "secret"),
            ("https://fhir.example.org/fhir", "secret"),
            ("http://fhir.example.org/fhir", None),
        ],
    )
    async def test_allowed_combinations(self, base, token):
        fhir_client.FHIR_BASE_URL = base
        fhir_client.FHIR_ACCESS_TOKEN = token
        with respx.mock(assert_all_called=False) as router:
            router.route().mock(
                return_value=httpx.Response(200, json=SAMPLE_PATIENT)
            )
            result = await fhir_client.read_resource("Patient", "example")
        assert result["id"] == "example"
