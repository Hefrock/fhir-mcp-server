"""
Tests for structured JSON output mode.

Each MCP tool accepts ``format="json"`` and returns a JSON string whose shape
matches the Pydantic models in models.py. These tests cover:

- The JSON companion formatters produce the expected shape
- Every MCP tool honours the format="text" default (backwards compat)
- Every MCP tool with format="json" returns parseable JSON with the right keys
- Invalid format values produce a friendly error
"""

import json

import httpx

from fhir_mcp_server import formatters, models
from fhir_mcp_server.server import (
    check_connection,
    check_medication_interactions,
    get_next_page,
    get_patient_summary,
    read_allergy_intolerance,
    read_diagnostic_report,
    read_encounter,
    read_immunization,
    read_observation,
    read_patient,
    search_allergy_intolerances,
    search_conditions,
    search_diagnostic_reports,
    search_encounters,
    search_immunizations,
    search_medications,
    search_observations,
    search_patients,
)

from .conftest import (
    FHIR_BASE,
    SAMPLE_ALLERGY,
    SAMPLE_ALLERGY_BUNDLE,
    SAMPLE_CAPABILITY_STATEMENT,
    SAMPLE_CONDITION,
    SAMPLE_CONDITION_BUNDLE,
    SAMPLE_DIAGNOSTIC_REPORT,
    SAMPLE_DIAGNOSTIC_REPORT_BUNDLE,
    SAMPLE_ENCOUNTER,
    SAMPLE_ENCOUNTER_BUNDLE,
    SAMPLE_IMMUNIZATION,
    SAMPLE_IMMUNIZATION_BUNDLE,
    SAMPLE_MEDICATION,
    SAMPLE_MEDICATION_BUNDLE,
    SAMPLE_OBSERVATION,
    SAMPLE_OBSERVATION_BUNDLE,
    SAMPLE_PATIENT,
    SAMPLE_PATIENT_BUNDLE,
)

# ---------------------------------------------------------------------------
# Formatter-level JSON companions
# ---------------------------------------------------------------------------


class TestPatientToJson:
    def test_shape(self):
        out = formatters.patient_to_json(SAMPLE_PATIENT)
        assert out["id"] == "example"
        assert out["resourceType"] == "Patient"
        assert out["name"] == "John Smith"
        assert out["gender"] == "male"
        assert out["birthDate"] == "1990-06-15"
        assert isinstance(out["ageYears"], int)
        assert out["identifiers"] == [{"type": "MRN", "value": "12345"}]

    def test_tolerates_missing_fields(self):
        out = formatters.patient_to_json({"resourceType": "Patient", "id": "x"})
        assert out["id"] == "x"
        assert out["name"] == "(no name)"
        assert out["gender"] is None
        assert out["ageYears"] is None
        assert out["identifiers"] == []


class TestObservationToJson:
    def test_quantity_value(self):
        out = formatters.observation_to_json(SAMPLE_OBSERVATION)
        assert out["id"] == "obs-hr-1"
        assert "Heart rate" in out["codeDisplay"]
        assert out["value"]["quantity"] == 72
        assert out["value"]["unit"] == "beats/minute"

    def test_blood_pressure_components(self):
        obs = {
            "resourceType": "Observation",
            "id": "bp-1",
            "code": {"text": "Blood pressure"},
            "component": [
                {
                    "code": {"text": "Systolic"},
                    "valueQuantity": {"value": 120, "unit": "mmHg"},
                },
                {
                    "code": {"text": "Diastolic"},
                    "valueQuantity": {"value": 80, "unit": "mmHg"},
                },
            ],
        }
        out = formatters.observation_to_json(obs)
        assert len(out["value"]["components"]) == 2
        assert out["value"]["components"][0]["label"] == "Systolic"
        assert out["value"]["components"][0]["quantity"] == 120


class TestConditionToJson:
    def test_shape(self):
        out = formatters.condition_to_json(SAMPLE_CONDITION)
        assert out["id"] == "cond-htn"
        assert out["codeDisplay"] == "Essential hypertension"
        assert out["clinicalStatus"] == "active"
        assert out["onset"] == "2019-05-20"


class TestMedicationRequestToJson:
    def test_shape(self):
        out = formatters.medication_request_to_json(SAMPLE_MEDICATION)
        assert out["id"] == "med-warfarin"
        assert "Warfarin" in out["drug"]
        assert out["status"] == "active"
        assert out["authoredOn"] == "2023-11-02"
        assert out["dosageText"] == "Take 5 mg once daily"


class TestCapabilityToJson:
    def test_shape(self):
        out = formatters.capability_to_json(SAMPLE_CAPABILITY_STATEMENT, FHIR_BASE)
        assert out["baseUrl"] == FHIR_BASE
        assert out["fhirVersion"] == "4.0.1"
        assert out["isR4"] is True
        assert out["serverName"] == "HAPI FHIR Server"
        assert "Patient" in out["resources"]
        assert "SMART-on-FHIR" in out["securityServices"]

    def test_non_r4_flag(self):
        cap = {**SAMPLE_CAPABILITY_STATEMENT, "fhirVersion": "5.0.0"}
        out = formatters.capability_to_json(cap, FHIR_BASE)
        assert out["isR4"] is False


class TestBundleToJson:
    def test_search_envelope(self):
        out = formatters.bundle_to_json(SAMPLE_PATIENT_BUNDLE)
        assert out["total"] == 1
        assert out["returned"] == 1
        assert out["nextPage"] is None
        assert out["resources"][0]["id"] == "example"
        assert out["resources"][0]["resourceType"] == "Patient"

    def test_empty_bundle(self):
        out = formatters.bundle_to_json(
            {"resourceType": "Bundle", "type": "searchset", "total": 0}
        )
        assert out["returned"] == 0
        assert out["resources"] == []


# ---------------------------------------------------------------------------
# End-to-end tool tests — format="json"
# ---------------------------------------------------------------------------


class TestReadPatientJson:
    async def test_returns_parseable_json(self, mock_fhir):
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        result = await read_patient("example", format="json")
        parsed = json.loads(result)
        assert parsed["id"] == "example"
        assert parsed["name"] == "John Smith"

    async def test_text_default_unchanged(self, mock_fhir):
        mock_fhir.get("/Patient/example").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT)
        )
        result = await read_patient("example")
        # Default is still the readable string
        assert "John Smith" in result
        assert not result.startswith("{")


class TestSearchPatientsJson:
    async def test_returns_bundle_envelope(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await search_patients(family="Smith", format="json")
        parsed = json.loads(result)
        assert parsed["total"] == 1
        assert parsed["returned"] == 1
        assert parsed["resources"][0]["name"] == "John Smith"


class TestReadObservationJson:
    async def test_shape(self, mock_fhir):
        mock_fhir.get("/Observation/obs-hr-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION)
        )
        result = await read_observation("obs-hr-1", format="json")
        parsed = json.loads(result)
        assert parsed["id"] == "obs-hr-1"
        assert parsed["value"]["quantity"] == 72


class TestSearchToolsJson:
    async def test_search_observations_json(self, mock_fhir):
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        result = await search_observations(patient="example", format="json")
        parsed = json.loads(result)
        assert parsed["returned"] == 1
        assert parsed["resources"][0]["id"] == "obs-hr-1"

    async def test_search_conditions_json(self, mock_fhir):
        mock_fhir.get("/Condition").mock(
            return_value=httpx.Response(200, json=SAMPLE_CONDITION_BUNDLE)
        )
        result = await search_conditions(patient="example", format="json")
        parsed = json.loads(result)
        assert parsed["resources"][0]["codeDisplay"] == "Essential hypertension"

    async def test_search_medications_json(self, mock_fhir):
        mock_fhir.get("/MedicationRequest").mock(
            return_value=httpx.Response(200, json=SAMPLE_MEDICATION_BUNDLE)
        )
        result = await search_medications(patient="example", format="json")
        parsed = json.loads(result)
        assert "Warfarin" in parsed["resources"][0]["drug"]


class TestCheckMedicationInteractionsJson:
    async def test_finding_shape(self):
        result = await check_medication_interactions(
            ["warfarin", "aspirin"], format="json"
        )
        parsed = json.loads(result)
        assert parsed["medications"] == ["warfarin", "aspirin"]
        assert len(parsed["findings"]) == 1
        f = parsed["findings"][0]
        assert f["severity"] == "MAJOR"
        assert f["drugA"] == "warfarin"
        assert f["drugB"] == "aspirin"

    async def test_no_findings_returns_empty_list(self):
        result = await check_medication_interactions(
            ["acetaminophen", "loratadine"], format="json"
        )
        parsed = json.loads(result)
        assert parsed["findings"] == []

    async def test_too_few_meds_returns_empty(self):
        result = await check_medication_interactions(["warfarin"], format="json")
        parsed = json.loads(result)
        assert parsed["findings"] == []


class TestCheckConnectionJson:
    async def test_shape(self, mock_fhir):
        mock_fhir.get("/metadata").mock(
            return_value=httpx.Response(200, json=SAMPLE_CAPABILITY_STATEMENT)
        )
        result = await check_connection(format="json")
        parsed = json.loads(result)
        assert parsed["fhirVersion"] == "4.0.1"
        assert parsed["isR4"] is True
        assert "Patient" in parsed["resources"]


class TestGetPatientSummaryJson:
    def _wire_all(self, mock_fhir):
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
            return_value=httpx.Response(200, json=SAMPLE_MEDICATION_BUNDLE)
        )

    async def test_composed_shape(self, mock_fhir):
        self._wire_all(mock_fhir)
        result = await get_patient_summary("example", format="json")
        parsed = json.loads(result)
        assert parsed["patient"]["name"] == "John Smith"
        assert len(parsed["activeConditions"]) == 1
        assert len(parsed["recentVitals"]) == 1
        assert len(parsed["activeMedications"]) == 1
        # Warfarin alone shouldn't flag any interactions
        assert parsed["interactionWarnings"] == []

    async def test_patient_read_failure_returns_error_json(self, mock_fhir):
        mock_fhir.get("/Patient/missing").mock(
            return_value=httpx.Response(404, json={})
        )
        mock_fhir.get("/Condition").mock(
            return_value=httpx.Response(200, json=SAMPLE_CONDITION_BUNDLE)
        )
        mock_fhir.get("/Observation").mock(
            return_value=httpx.Response(200, json=SAMPLE_OBSERVATION_BUNDLE)
        )
        mock_fhir.get("/MedicationRequest").mock(
            return_value=httpx.Response(200, json=SAMPLE_MEDICATION_BUNDLE)
        )
        result = await get_patient_summary("missing", format="json")
        parsed = json.loads(result)
        assert "error" in parsed
        assert parsed["patientId"] == "missing"


class TestGetNextPageJson:
    async def test_json_mode(self, mock_fhir):
        mock_fhir.get("/Patient").mock(
            return_value=httpx.Response(200, json=SAMPLE_PATIENT_BUNDLE)
        )
        result = await get_next_page(
            f"{FHIR_BASE}/Patient?_getpagesoffset=10", format="json"
        )
        parsed = json.loads(result)
        assert parsed["returned"] == 1


# ---------------------------------------------------------------------------
# Invalid format handling
# ---------------------------------------------------------------------------


class TestInvalidFormat:
    async def test_bad_format_returns_friendly_error(self, mock_fhir):
        # The @fhir_tool decorator catches ValueError and returns a string.
        result = await read_patient("example", format="yaml")
        assert "Invalid request" in result
        assert "yaml" in result


# ---------------------------------------------------------------------------
# Pydantic model contract
# ---------------------------------------------------------------------------


class TestModelSchemas:
    """These models are our public contract — a schema regression should fail loudly."""

    def test_patient_model_validates_expected_shape(self):
        payload = {
            "id": "x",
            "name": "Test",
            "identifiers": [{"type": "MRN", "value": "1"}],
        }
        m = models.PatientJson(**payload)
        assert m.id == "x"
        assert m.identifiers[0].value == "1"

    def test_capability_model_computes_dump_keys(self):
        m = models.CapabilityJson(
            baseUrl="http://x", fhirVersion="4.0.1", isR4=True
        )
        dumped = m.model_dump(by_alias=True)
        assert dumped["baseUrl"] == "http://x"
        assert dumped["isR4"] is True

    def test_schemas_export_json_schema(self):
        # Downstream consumers can validate against this without importing pydantic.
        schema = models.PatientJson.model_json_schema()
        assert schema["type"] == "object"
        assert "identifiers" in schema["properties"]


class TestEncounterToJson:
    def test_shape(self):
        out = formatters.encounter_to_json(SAMPLE_ENCOUNTER)
        assert out["id"] == "enc-ambulatory-1"
        assert out["resourceType"] == "Encounter"
        assert out["status"] == "finished"
        assert out["class"] == "ambulatory"
        assert out["type"] == "Primary care visit"
        assert out["reason"] == "Annual physical exam"
        assert out["start"] == "2024-03-01T09:00:00Z"
        assert out["serviceProvider"] == "Community Clinic"

    def test_tolerates_missing_fields(self):
        out = formatters.encounter_to_json({"resourceType": "Encounter", "id": "e"})
        assert out["id"] == "e"
        assert out["type"] is None
        assert out["status"] is None


class TestAllergyToJson:
    def test_shape(self):
        out = formatters.allergy_intolerance_to_json(SAMPLE_ALLERGY)
        assert out["id"] == "allergy-penicillin"
        assert out["substance"] == "Penicillin"
        assert out["type"] == "allergy"
        assert out["categories"] == ["medication"]
        assert out["criticality"] == "high"
        assert out["clinicalStatus"] == "active"
        assert out["recordedDate"] == "2015-06-10"
        assert len(out["reactions"]) == 1
        assert "Hives" in out["reactions"][0]["manifestations"]
        assert out["reactions"][0]["severity"] == "severe"


class TestReadEncounterJson:
    async def test_returns_parseable_json(self, mock_fhir):
        mock_fhir.get("/Encounter/enc-ambulatory-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_ENCOUNTER)
        )
        result = await read_encounter("enc-ambulatory-1", format="json")
        parsed = json.loads(result)
        assert parsed["type"] == "Primary care visit"
        assert parsed["class"] == "ambulatory"


class TestSearchEncountersJson:
    async def test_bundle_envelope(self, mock_fhir):
        mock_fhir.get("/Encounter").mock(
            return_value=httpx.Response(200, json=SAMPLE_ENCOUNTER_BUNDLE)
        )
        result = await search_encounters(patient="example", format="json")
        parsed = json.loads(result)
        assert parsed["returned"] == 1
        assert parsed["resources"][0]["type"] == "Primary care visit"


class TestReadAllergyIntoleranceJson:
    async def test_returns_parseable_json(self, mock_fhir):
        mock_fhir.get("/AllergyIntolerance/allergy-penicillin").mock(
            return_value=httpx.Response(200, json=SAMPLE_ALLERGY)
        )
        result = await read_allergy_intolerance("allergy-penicillin", format="json")
        parsed = json.loads(result)
        assert parsed["substance"] == "Penicillin"
        assert parsed["criticality"] == "high"


class TestSearchAllergiesJson:
    async def test_bundle_envelope(self, mock_fhir):
        mock_fhir.get("/AllergyIntolerance").mock(
            return_value=httpx.Response(200, json=SAMPLE_ALLERGY_BUNDLE)
        )
        result = await search_allergy_intolerances(patient="example", format="json")
        parsed = json.loads(result)
        assert parsed["returned"] == 1
        assert parsed["resources"][0]["substance"] == "Penicillin"


class TestDiagnosticReportToJson:
    def test_shape(self):
        out = formatters.diagnostic_report_to_json(SAMPLE_DIAGNOSTIC_REPORT)
        assert out["id"] == "dr-cbc-1"
        assert out["resourceType"] == "DiagnosticReport"
        assert out["codeDisplay"] == "Complete blood count"
        assert out["category"] == "Laboratory"
        assert out["status"] == "final"
        assert out["conclusion"] == "Normal CBC. No cytopenias."
        assert out["performer"] == "Community Labs"
        assert len(out["resultReferences"]) == 2
        assert "Observation/obs-hgb" in out["resultReferences"]

    def test_tolerates_missing_fields(self):
        out = formatters.diagnostic_report_to_json(
            {"resourceType": "DiagnosticReport", "id": "r"}
        )
        assert out["id"] == "r"
        assert out["conclusion"] is None
        assert out["resultReferences"] == []


class TestImmunizationToJson:
    def test_shape(self):
        out = formatters.immunization_to_json(SAMPLE_IMMUNIZATION)
        assert out["id"] == "imm-flu-2024"
        assert out["resourceType"] == "Immunization"
        assert "Influenza" in out["vaccine"]
        assert out["status"] == "completed"
        assert out["occurrence"] == "2024-10-15"
        assert out["lotNumber"] == "AB123CD"
        assert out["route"] == "Intramuscular"
        assert out["site"] == "Left deltoid"
        assert out["doseQuantity"] == 0.5
        assert out["doseUnit"] == "mL"


class TestReadDiagnosticReportJson:
    async def test_returns_parseable_json(self, mock_fhir):
        mock_fhir.get("/DiagnosticReport/dr-cbc-1").mock(
            return_value=httpx.Response(200, json=SAMPLE_DIAGNOSTIC_REPORT)
        )
        result = await read_diagnostic_report("dr-cbc-1", format="json")
        parsed = json.loads(result)
        assert parsed["codeDisplay"] == "Complete blood count"
        assert parsed["conclusion"] == "Normal CBC. No cytopenias."


class TestSearchDiagnosticReportsJson:
    async def test_bundle_envelope(self, mock_fhir):
        mock_fhir.get("/DiagnosticReport").mock(
            return_value=httpx.Response(200, json=SAMPLE_DIAGNOSTIC_REPORT_BUNDLE)
        )
        result = await search_diagnostic_reports(patient="example", format="json")
        parsed = json.loads(result)
        assert parsed["returned"] == 1
        assert parsed["resources"][0]["codeDisplay"] == "Complete blood count"


class TestReadImmunizationJson:
    async def test_returns_parseable_json(self, mock_fhir):
        mock_fhir.get("/Immunization/imm-flu-2024").mock(
            return_value=httpx.Response(200, json=SAMPLE_IMMUNIZATION)
        )
        result = await read_immunization("imm-flu-2024", format="json")
        parsed = json.loads(result)
        assert "Influenza" in parsed["vaccine"]
        assert parsed["lotNumber"] == "AB123CD"


class TestSearchImmunizationsJson:
    async def test_bundle_envelope(self, mock_fhir):
        mock_fhir.get("/Immunization").mock(
            return_value=httpx.Response(200, json=SAMPLE_IMMUNIZATION_BUNDLE)
        )
        result = await search_immunizations(patient="example", format="json")
        parsed = json.loads(result)
        assert parsed["returned"] == 1
        assert "Influenza" in parsed["resources"][0]["vaccine"]
