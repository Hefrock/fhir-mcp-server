"""
End-to-end smoke tests against fhir-synthea-lab.

Assumptions:
  - FHIR_BASE_URL is set to a live HAPI FHIR endpoint loaded with Synthea
    patients (e.g. http://localhost:8080/fhir).
  - The lab has been booted via `make all` in the sibling repo.

Run locally:
    cd ../fhir-synthea-lab && make all
    FHIR_BASE_URL=http://localhost:8080/fhir pytest tests_synthea/ -v

Run in CI: the `synthea-smoke` GitHub Actions workflow boots the lab and
sets FHIR_BASE_URL automatically.

These tests validate the tool surface against REAL FHIR quirks that the
respx-mocked unit tests cannot catch:
  - Actual HAPI response shapes (extra fields, ordering, unusual coding
    systems)
  - Synthea's generated data (real dates, brand-name meds, LOINC-coded
    observations)
  - Pagination behavior on a real server
"""

import json

import pytest

from fhir_mcp_server.server import (
    check_connection,
    check_medication_interactions,
    get_patient_summary,
    read_patient,
    search_conditions,
    search_medications,
    search_observations,
    search_patients,
)


class TestPreflight:
    async def test_endpoint_reports_r4(self):
        result = await check_connection()
        assert "FHIR endpoint at" in result
        assert "FHIR version: 4" in result

    async def test_capability_json_shape(self):
        result = await check_connection(format="json")
        parsed = json.loads(result)
        assert parsed["isR4"] is True
        # HAPI FHIR advertises the full resource set — Patient must be there
        assert "Patient" in parsed["resources"]


class TestPatientSearch:
    async def test_search_returns_patients(self):
        # Bare search — Synthea seeds 50 patients, we should get 10 back
        result = await search_patients(count=10, format="json")
        parsed = json.loads(result)
        assert parsed["returned"] > 0, "Expected at least one patient in Synthea lab"
        # Every patient must expose the fields our contract promises
        first = parsed["resources"][0]
        assert "id" in first
        assert "name" in first

    @pytest.fixture
    async def first_patient_id(self):
        """Discover a patient id at runtime — Synthea uses random UUIDs."""
        result = await search_patients(count=1, format="json")
        parsed = json.loads(result)
        assert parsed["returned"] > 0, "No patients found — is the lab loaded?"
        return parsed["resources"][0]["id"]

    async def test_read_patient_by_discovered_id(self, first_patient_id):
        result = await read_patient(first_patient_id, format="json")
        parsed = json.loads(result)
        assert parsed["id"] == first_patient_id
        # Synthea patients always have a name and gender
        assert parsed["name"] != "(no name)"


class TestPatientSummary:
    """The flagship composite tool — real Synthea patients have all four sections."""

    @pytest.fixture
    async def any_patient_id(self):
        result = await search_patients(count=1, format="json")
        parsed = json.loads(result)
        assert parsed["returned"] > 0
        return parsed["resources"][0]["id"]

    async def test_summary_composes_all_sections_text(self, any_patient_id):
        result = await get_patient_summary(any_patient_id)
        assert "Patient Summary" in result
        # Text-mode summary always includes these section headers, even when
        # a section is empty ("none found").
        assert "Active conditions" in result
        assert "Recent vital signs" in result
        assert "Active medications" in result

    async def test_summary_json_shape(self, any_patient_id):
        result = await get_patient_summary(any_patient_id, format="json")
        parsed = json.loads(result)
        assert parsed["patient"]["id"] == any_patient_id
        # These keys must exist even when the lists are empty
        assert "activeConditions" in parsed
        assert "recentVitals" in parsed
        assert "activeMedications" in parsed
        assert "interactionWarnings" in parsed
        assert isinstance(parsed["activeConditions"], list)


class TestClinicalSearches:
    """Verify search tools return typed data against a real server."""

    @pytest.fixture
    async def any_patient_id(self):
        result = await search_patients(count=1, format="json")
        parsed = json.loads(result)
        assert parsed["returned"] > 0
        return parsed["resources"][0]["id"]

    async def test_search_conditions_json(self, any_patient_id):
        result = await search_conditions(patient=any_patient_id, format="json")
        parsed = json.loads(result)
        # Whether or not this patient has conditions, the envelope shape must hold
        assert "resources" in parsed
        assert "returned" in parsed
        assert "total" in parsed

    async def test_search_medications_json(self, any_patient_id):
        result = await search_medications(patient=any_patient_id, format="json")
        parsed = json.loads(result)
        assert "resources" in parsed

    async def test_search_observations_by_friendly_name(self, any_patient_id):
        # heart_rate → 8867-4 resolution must work against the real server
        result = await search_observations(
            patient=any_patient_id, code="heart_rate", format="json"
        )
        parsed = json.loads(result)
        # Envelope always shapes correctly, even if this patient has no HR data
        assert "resources" in parsed


class TestLocalInteractions:
    """Runs without touching the server — always returns the same answer."""

    async def test_warfarin_aspirin_flags_major(self):
        result = await check_medication_interactions(
            ["warfarin", "aspirin"], format="json"
        )
        parsed = json.loads(result)
        assert any(f["severity"] == "MAJOR" for f in parsed["findings"])
