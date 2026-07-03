"""
Tests for the MCP tool functions in server.py.

These call the tool functions directly (bypassing the MCP transport) and verify
they delegate to fhir_client correctly and return readable summaries. Where a
tool transforms its inputs (count capping, LOINC name resolution), we capture
the outgoing request params and assert on them.
"""

import httpx

from fhir_mcp_server.server import (
    check_connection,
    check_medication_interactions,
    get_next_page,
    get_patient_summary,
    read_allergy_intolerance,
    read_encounter,
    read_observation,
    read_patient,
    search_allergy_intolerances,
    search_conditions,
    search_encounters,
    search_medications,
    search_observations,
    search_patients,
)

from .conftest import (
    SAMPLE_ALLERGY,
    SAMPLE_ALLERGY_BUNDLE,
    SAMPLE_CAPABILITY_STATEMENT,
    SAMPLE_CONDITION_BUNDLE,
    SAMPLE_ENCOUNTER,
    SAMPLE_ENCOUNTER_BUNDLE,
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

    async def test_404_returns_friendly_message(self, mock_fhir):
        # @fhir_tool converts HTTP errors to strings — tools never raise.
        mock_fhir.get("/Patient/gone").mock(return_value=httpx.Response(404, json={}))
        result = await read_patient("gone")
        assert "404" in result
        assert "Not found" in result

    async def test_server_error_returns_friendly_message(self, mock_fhir):
        mock_fhir.get("/Patient/boom").mock(
            return_value=httpx.Response(500, text="err")
        )
        result = await read_patient("boom")
        assert "500" in result


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


# Two interacting meds, so the summary's interaction check has something to find.
_INTERACTING_MEDS_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 2,
    "entry": [
        {
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "m1",
                "status": "active",
                "medicationCodeableConcept": {"text": "Warfarin 5 mg oral tablet"},
            }
        },
        {
            "resource": {
                "resourceType": "MedicationRequest",
                "id": "m2",
                "status": "active",
                "medicationCodeableConcept": {"text": "Aspirin 81 mg oral tablet"},
            }
        },
    ],
}


class TestGetNextPage:
    _NEXT_URL = "https://r4.smarthealthit.org/Patient?_getpagesoffset=10&_count=10"

    async def test_fetches_and_formats_next_page(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await get_next_page(self._NEXT_URL)
        assert "John Smith" in result

    async def test_rejects_cross_origin_url(self):
        # Security boundary: the URL must start with FHIR_BASE_URL.
        result = await get_next_page("https://evil.example.com/Patient?x=1")
        assert "Invalid request" in result
        assert "evil.example.com" in result


class TestGetPatientSummary:
    def _wire_all(self, mock_fhir, meds_bundle):
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        mock_fhir.get("/Condition").mock(
            return_value=httpx.Response(200, json=SAMPLE_CONDITION_BUNDLE)
        )
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        mock_fhir.get("/MedicationRequest").mock(
            return_value=httpx.Response(200, json=meds_bundle)
        )

    async def test_composes_all_sections(self, mock_fhir):
        self._wire_all(mock_fhir, SAMPLE_MEDICATION_BUNDLE)
        result = await get_patient_summary("example")
        assert "Patient Summary" in result
        assert "John Smith" in result
        assert "Essential hypertension" in result  # condition
        assert "Heart rate" in result  # vital
        assert "Warfarin" in result  # medication

    async def test_flags_interactions_among_active_meds(self, mock_fhir):
        self._wire_all(mock_fhir, _INTERACTING_MEDS_BUNDLE)
        result = await get_patient_summary("example")
        assert "Medication interaction warnings" in result
        assert "MAJOR" in result
        assert "warfarin + aspirin" in result

    async def test_degrades_when_a_subquery_fails(self, mock_fhir):
        # Conditions endpoint errors; the summary should still render the rest.
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        mock_fhir.get("/Condition").mock(return_value=httpx.Response(500, text="boom"))
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        mock_fhir.get("/MedicationRequest").mock(
            return_value=httpx.Response(200, json=SAMPLE_MEDICATION_BUNDLE)
        )
        result = await get_patient_summary("example")
        assert "Active conditions: none found" in result  # degraded section
        assert "Heart rate" in result  # other sections still present

    async def test_patient_read_failure_is_fatal(self, mock_fhir):
        mock_fhir.get("/Patient/missing").mock(
            return_value=httpx.Response(404, json={})
        )
        # The other queries may or may not fire; they shouldn't matter.
        mock_fhir.get("/Condition").mock(
            return_value=httpx.Response(200, json=SAMPLE_CONDITION_BUNDLE)
        )
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        mock_fhir.get("/MedicationRequest").mock(
            return_value=httpx.Response(200, json=SAMPLE_MEDICATION_BUNDLE)
        )
        result = await get_patient_summary("missing")
        assert "Could not retrieve Patient missing" in result


class TestCheckConnection:
    async def test_reports_server_capabilities(self, mock_fhir):
        mock_fhir.get("/metadata").mock(
            return_value=httpx.Response(200, json=SAMPLE_CAPABILITY_STATEMENT)
        )
        result = await check_connection()
        assert "HAPI FHIR Server v5.4.0" in result
        assert "FHIR version: 4.0.1" in result
        assert "SMART-on-FHIR" in result
        assert "Patient" in result

    async def test_reports_friendly_error_on_metadata_failure(self, mock_fhir):
        mock_fhir.get("/metadata").mock(
            return_value=httpx.Response(503, text="down")
        )
        result = await check_connection()
        assert "503" in result


class TestReadEncounter:
    async def test_returns_readable_summary(self, mock_fhir):
        mock_fhir.get("/Encounter/enc-ambulatory-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_ENCOUNTER)
        )
        result = await read_encounter("enc-ambulatory-1")
        assert "Primary care visit" in result
        assert "ambulatory" in result


class TestSearchEncounters:
    async def test_patient_search_lists_visits(self, mock_fhir):
        mock_fhir.get("/Encounter").mock(
            return_value=httpx.Response(200, json=SAMPLE_ENCOUNTER_BUNDLE)
        )
        result = await search_encounters(patient="example")
        assert "Primary care visit" in result

    async def test_status_and_date_params_passed(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/Encounter").mock(
            side_effect=_capture(captured, SAMPLE_ENCOUNTER_BUNDLE)
        )
        await search_encounters(
            patient="example", status="finished", date="ge2024-01-01"
        )
        assert captured["params"]["status"] == "finished"
        assert captured["params"]["date"] == "ge2024-01-01"


class TestReadAllergyIntolerance:
    async def test_returns_readable_summary(self, mock_fhir):
        mock_fhir.get("/AllergyIntolerance/allergy-penicillin").mock(
            return_value=httpx.Response(200, json=SAMPLE_ALLERGY)
        )
        result = await read_allergy_intolerance("allergy-penicillin")
        assert "Penicillin" in result
        assert "medication" in result
        assert "Hives" in result


class TestSearchAllergyIntolerances:
    async def test_patient_search_lists_allergies(self, mock_fhir):
        mock_fhir.get("/AllergyIntolerance").mock(
            return_value=httpx.Response(200, json=SAMPLE_ALLERGY_BUNDLE)
        )
        result = await search_allergy_intolerances(patient="example")
        assert "Penicillin" in result

    async def test_all_filters_passed_through(self, mock_fhir):
        captured: dict = {}
        mock_fhir.get("/AllergyIntolerance").mock(
            side_effect=_capture(captured, SAMPLE_ALLERGY_BUNDLE)
        )
        await search_allergy_intolerances(
            patient="example",
            clinical_status="active",
            category="medication",
            criticality="high",
        )
        assert captured["params"]["clinical-status"] == "active"
        assert captured["params"]["category"] == "medication"
        assert captured["params"]["criticality"] == "high"
