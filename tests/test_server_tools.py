"""
Tests for the MCP tool functions in server.py.

These call the tool functions directly (bypassing the MCP transport) and verify
they delegate to fhir_client correctly and return readable summaries. Where a
tool transforms its inputs (count capping, LOINC name resolution), we capture
the outgoing request params and assert on them.
"""

import httpx
import pytest

from fhir_mcp_server.server import (
    check_medication_interactions,
    read_observation,
    read_patient,
    search_conditions,
    search_medications,
    search_observations,
    search_patients,
)

from .conftest import (
    SAMPLE_CONDITION_BUNDLE,
    SAMPLE_MEDICATION_BUNDLE,
    SAMPLE_OBSERVATION,
    SAMPLE_OBSERVATION_BUNDLE,
    SAMPLE_PATIENT,
    SAMPLE_PATIENT_BUNDLE,
)


def _capture(store, json_body):
    """Build a respx side_effect that records query params then responds."""

    def handler(request):
        store["params"] = dict(request.url.params)
        return httpx.Response(200, json=json_body)

    return handler


class TestReadPatient:
    async def test_returns_readable_summary(self, mock_fhir):
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        result = await read_patient("example")
        assert "Patient example" in result
        assert "John Smith" in result
        assert "MRN=12345" in result

    async def test_propagates_http_error(self, mock_fhir):
        mock_fhir.get("/Patient/gone").mock(return_value=httpx.Response(404, json={}))
        with pytest.raises(httpx.HTTPStatusError):
            await read_patient("gone")


class TestSearchPatients:
    async def test_family_search_lists_results(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await search_patients(family="Smith")
        assert "Found 1 result" in result
        assert "John Smith" in result

    async def test_count_capped_at_50(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/Patient").mock(
            side_effect=_capture(captured, SAMPLE_PATIENT_BUNDLE)
        )
        await search_patients(name="Jones", count=999)
        assert captured["params"]["_count"] == "50"

    async def test_none_params_excluded(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/Patient").mock(
            side_effect=_capture(captured, SAMPLE_PATIENT_BUNDLE)
        )
        await search_patients(family="Smith")
        assert "given" not in captured["params"]
        assert "name" not in captured["params"]


class TestReadObservation:
    async def test_returns_observation_summary(self, mock_fhir):
        mock_fhir.get("/Observation/obs-hr-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION)
        )
        result = await read_observation("obs-hr-1")
        assert "Heart rate" in result
        assert "72" in result


class TestSearchObservations:
    async def test_vital_signs_search(self, mock_fhir):
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        result = await search_observations(patient="example", category="vital-signs")
        assert "Found 1 result" in result

    async def test_friendly_code_name_resolved_to_loinc(self, mock_fhir):
        """code='heart_rate' must be resolved to LOINC 8867-4 before querying."""
        captured: dict = {}
        mock_fhir.get("/Observation").mock(
            side_effect=_capture(captured, SAMPLE_OBSERVATION_BUNDLE)
        )
        await search_observations(patient="example", code="heart_rate")
        assert captured["params"]["code"] == "8867-4"

    async def test_raw_code_passed_through(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/Observation").mock(
            side_effect=_capture(captured, SAMPLE_OBSERVATION_BUNDLE)
        )
        await search_observations(patient="example", code="8480-6")
        assert captured["params"]["code"] == "8480-6"


class TestSearchConditions:
    async def test_lists_conditions(self, mock_fhir):
        mock_fhir.get("/Condition").mock(
            return_value=httpx.Response(200, json=SAMPLE_CONDITION_BUNDLE)
        )
        result = await search_conditions(patient="example", clinical_status="active")
        assert "Essential hypertension" in result

    async def test_clinical_status_maps_to_hyphenated_param(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/Condition").mock(
            side_effect=_capture(captured, SAMPLE_CONDITION_BUNDLE)
        )
        await search_conditions(patient="example", clinical_status="active")
        assert captured["params"]["clinical-status"] == "active"


class TestSearchMedications:
    async def test_lists_medications(self, mock_fhir):
        mock_fhir.get("/MedicationRequest").mock(
            return_value=httpx.Response(200, json=SAMPLE_MEDICATION_BUNDLE)
        )
        result = await search_medications(patient="example", status="active")
        assert "Warfarin" in result


class TestCheckMedicationInteractions:
    async def test_flags_known_major_interaction(self):
        result = await check_medication_interactions(["warfarin", "aspirin"])
        assert "MAJOR" in result
        assert "warfarin" in result and "aspirin" in result

    async def test_brand_names_normalized(self):
        result = await check_medication_interactions(["Coumadin", "ASA"])
        assert "MAJOR" in result

    async def test_no_interaction_message(self):
        result = await check_medication_interactions(["acetaminophen", "loratadine"])
        assert "No known interactions" in result

    async def test_requires_two_medications(self):
        result = await check_medication_interactions(["warfarin"])
        assert "at least two" in result
