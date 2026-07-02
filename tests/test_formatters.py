"""
Tests for formatters — the resource -> readable summary layer.

The point of these is robustness: formatters must never crash on missing or
oddly-shaped fields, since real FHIR data is wildly inconsistent.
"""

from fhir_mcp_server import formatters

from .conftest import (
    FHIR_BASE,
    SAMPLE_CAPABILITY_STATEMENT,
    SAMPLE_CONDITION,
    SAMPLE_MEDICATION,
    SAMPLE_OBSERVATION,
    SAMPLE_OBSERVATION_BUNDLE,
    SAMPLE_PATIENT,
)


class TestFormatPatient:
    def test_includes_id_name_and_identifier(self):
        out = formatters.format_patient(SAMPLE_PATIENT)
        assert "Patient example" in out
        assert "John Smith" in out
        assert "male" in out
        assert "MRN=12345" in out

    def test_handles_missing_name(self):
        out = formatters.format_patient({"resourceType": "Patient", "id": "x"})
        assert "(no name)" in out
        assert "unknown age" in out


class TestFormatObservation:
    def test_value_quantity(self):
        out = formatters.format_observation(SAMPLE_OBSERVATION)
        assert "Heart rate" in out
        assert "72" in out

    def test_blood_pressure_components(self):
        bp = {
            "resourceType": "Observation",
            "id": "bp-1",
            "status": "final",
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
        out = formatters.format_observation(bp)
        assert "Systolic 120" in out
        assert "Diastolic 80" in out

    def test_missing_value_does_not_crash(self):
        out = formatters.format_observation(
            {"resourceType": "Observation", "id": "o", "code": {"text": "X"}}
        )
        assert "(no value)" in out


class TestFormatConditionAndMedication:
    def test_condition(self):
        out = formatters.format_condition(SAMPLE_CONDITION)
        assert "Essential hypertension" in out
        assert "active" in out

    def test_medication(self):
        out = formatters.format_medication_request(SAMPLE_MEDICATION)
        assert "Warfarin" in out
        assert "Take 5 mg once daily" in out


class TestFormatBundle:
    def test_lists_entries(self):
        out = formatters.format_bundle(SAMPLE_OBSERVATION_BUNDLE)
        assert "Found 1 result" in out
        assert "Heart rate" in out

    def test_empty_bundle(self):
        out = formatters.format_bundle(
            {"resourceType": "Bundle", "type": "searchset", "total": 0}
        )
        assert "No matching resources" in out

    def test_next_link_shown_when_present(self):
        bundle_with_next = {
            **SAMPLE_OBSERVATION_BUNDLE,
            "link": [
                {"relation": "self", "url": "https://r4.smarthealthit.org/Observation?_count=10"},
                {"relation": "next", "url": "https://r4.smarthealthit.org/Observation?_count=10&_getpagesoffset=10"},
            ],
        }
        out = formatters.format_bundle(bundle_with_next)
        assert "Next page:" in out
        assert "_getpagesoffset=10" in out

    def test_no_next_link_when_absent(self):
        out = formatters.format_bundle(SAMPLE_OBSERVATION_BUNDLE)
        assert "Next page" not in out


class TestFormatCapabilityStatement:
    def test_summary_includes_key_fields(self):
        out = formatters.format_capability_statement(
            SAMPLE_CAPABILITY_STATEMENT, FHIR_BASE
        )
        assert FHIR_BASE in out
        assert "HAPI FHIR Server v5.4.0" in out
        assert "SMART R4 Sandbox" in out
        assert "FHIR version: 4.0.1" in out
        assert "SMART-on-FHIR" in out
        # All 4 sample resource types should appear
        assert "Patient" in out
        assert "Observation" in out
        assert "Condition" in out
        assert "MedicationRequest" in out

    def test_flags_non_r4_version(self):
        cap = {**SAMPLE_CAPABILITY_STATEMENT, "fhirVersion": "3.0.2"}
        out = formatters.format_capability_statement(cap, FHIR_BASE)
        assert "3.0.2" in out
        assert "does not report FHIR R4" in out

    def test_open_server_when_no_security_service(self):
        cap = {**SAMPLE_CAPABILITY_STATEMENT, "rest": [{"mode": "server"}]}
        out = formatters.format_capability_statement(cap, FHIR_BASE)
        assert "open" in out.lower() or "unauthenticated" in out.lower()

    def test_tolerates_bare_minimum_capability(self):
        # A conformant CapabilityStatement can omit software, implementation,
        # rest, and even fhirVersion. Formatter must not crash.
        out = formatters.format_capability_statement(
            {"resourceType": "CapabilityStatement"}, FHIR_BASE
        )
        assert FHIR_BASE in out
        assert "unknown" in out
