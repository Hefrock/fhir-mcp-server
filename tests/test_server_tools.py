"""
Unit tests for the MCP tool functions in server.py.

These tests call the Python functions directly (bypassing the MCP protocol
layer) and verify that they correctly delegate to fhir_client and return
well-formed JSON strings.
"""

import json

import httpx
import pytest

from fhir_mcp_server.server import (
    read_observation,
    read_patient,
    search_observations,
    search_patients,
)

from .conftest import (
    SAMPLE_OBSERVATION,
    SAMPLE_OBSERVATION_BUNDLE,
    SAMPLE_PATIENT,
    SAMPLE_PATIENT_BUNDLE,
)


class TestReadPatient:
    async def test_returns_json_string(self, mock_fhir):
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        result = await read_patient("example")
        data = json.loads(result)
        assert data["resourceType"] == "Patient"
        assert data["name"][0]["family"] == "Smith"

    async def test_propagates_http_error(self, mock_fhir):
        mock_fhir.get("/Patient/gone").mock(return_value=httpx.Response(404, json={}))
        with pytest.raises(httpx.HTTPStatusError):
            await read_patient("gone")


class TestSearchPatients:
    async def test_family_search(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await search_patients(family="Smith")
        bundle = json.loads(result)
        assert bundle["type"] == "searchset"
        assert bundle["entry"][0]["resource"]["id"] == "example"

    async def test_count_capped_at_50(self, mock_fhir):
        """_count should never exceed 50 regardless of what the caller passes."""
        captured = {}

        def capture(request, route):
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)

        mock_fhir.get("/Patient").mock(side_effect=capture)
        await search_patients(name="Jones", count=999)
        assert captured["params"]["_count"] == "50"

    async def test_none_params_excluded(self, mock_fhir):
        """Parameters left as None must not appear in the query string."""
        captured = {}

        def capture(request, route):
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)

        mock_fhir.get("/Patient").mock(side_effect=capture)
        await search_patients(family="Smith")
        assert "given" not in captured["params"]
        assert "name" not in captured["params"]


class TestReadObservation:
    async def test_returns_observation_json(self, mock_fhir):
        mock_fhir.get("/Observation/obs-hr-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION)
        )
        result = await read_observation("obs-hr-1")
        data = json.loads(result)
        assert data["resourceType"] == "Observation"
        assert data["valueQuantity"]["value"] == 72


class TestSearchObservations:
    async def test_vital_signs_search(self, mock_fhir):
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        result = await search_observations(patient="example", category="vital-signs")
        bundle = json.loads(result)
        assert bundle["type"] == "searchset"

    async def test_count_capped_at_50(self, mock_fhir):
        captured = {}

        def capture(request, route):
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)

        mock_fhir.get("/Observation").mock(side_effect=capture)
        await search_observations(patient="example", count=100)
        assert captured["params"]["_count"] == "50"
