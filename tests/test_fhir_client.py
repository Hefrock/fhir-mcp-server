"""
Unit tests for fhir_client — the HTTP layer.

These tests verify that the client correctly:
  - constructs URLs and headers
  - deserialises JSON responses
  - propagates HTTP errors (4xx/5xx) as exceptions
"""

import httpx
import pytest

from fhir_mcp_server import fhir_client

from .conftest import (
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
