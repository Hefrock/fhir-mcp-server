"""
Shared pytest fixtures and sample FHIR data.

respx is an httpx-native mock library: it intercepts outgoing requests at the
transport layer, so our async client code runs unmodified while tests never
touch the network.
"""

import pytest
import respx

from fhir_mcp_server import fhir_client

FHIR_BASE = "https://r4.smarthealthit.org"

# ---------------------------------------------------------------------------
# Sample FHIR resources
# ---------------------------------------------------------------------------

SAMPLE_PATIENT = {
    "resourceType": "Patient",
    "id": "example",
    "name": [{"use": "official", "family": "Smith", "given": ["John"]}],
    "gender": "male",
    "birthDate": "1990-06-15",
    "identifier": [
        {
            "type": {"text": "MRN"},
            "system": "http://hospital.org/mrn",
            "value": "12345",
        }
    ],
}

SAMPLE_PATIENT_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [{"fullUrl": f"{FHIR_BASE}/Patient/example", "resource": SAMPLE_PATIENT}],
}

SAMPLE_OBSERVATION = {
    "resourceType": "Observation",
    "id": "obs-hr-1",
    "status": "final",
    "category": [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "vital-signs",
                }
            ]
        }
    ],
    "code": {
        "coding": [
            {"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}
        ]
    },
    "subject": {"reference": "Patient/example"},
    "effectiveDateTime": "2024-03-01",
    "valueQuantity": {
        "value": 72,
        "unit": "beats/minute",
        "system": "http://unitsofmeasure.org",
    },
}

SAMPLE_OBSERVATION_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {"fullUrl": f"{FHIR_BASE}/Observation/obs-hr-1", "resource": SAMPLE_OBSERVATION}
    ],
}

SAMPLE_CONDITION = {
    "resourceType": "Condition",
    "id": "cond-htn",
    "clinicalStatus": {
        "coding": [{"code": "active"}],
        "text": "active",
    },
    "verificationStatus": {"text": "confirmed"},
    "code": {"text": "Essential hypertension"},
    "subject": {"reference": "Patient/example"},
    "onsetDateTime": "2019-05-20",
}

SAMPLE_CONDITION_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {"fullUrl": f"{FHIR_BASE}/Condition/cond-htn", "resource": SAMPLE_CONDITION}
    ],
}

SAMPLE_MEDICATION = {
    "resourceType": "MedicationRequest",
    "id": "med-warfarin",
    "status": "active",
    "medicationCodeableConcept": {"text": "Warfarin 5 mg oral tablet"},
    "subject": {"reference": "Patient/example"},
    "authoredOn": "2023-11-02",
    "dosageInstruction": [{"text": "Take 5 mg once daily"}],
}

SAMPLE_MEDICATION_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {
            "fullUrl": f"{FHIR_BASE}/MedicationRequest/med-warfarin",
            "resource": SAMPLE_MEDICATION,
        }
    ],
}


SAMPLE_CAPABILITY_STATEMENT = {
    "resourceType": "CapabilityStatement",
    "status": "active",
    "date": "2024-01-01",
    "publisher": "SMART Health IT",
    "kind": "instance",
    "software": {"name": "HAPI FHIR Server", "version": "5.4.0"},
    "implementation": {
        "description": "SMART R4 Sandbox",
        "url": FHIR_BASE,
    },
    "fhirVersion": "4.0.1",
    "format": ["json", "xml"],
    "rest": [
        {
            "mode": "server",
            "security": {
                "cors": True,
                "service": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/restful-security-service",
                                "code": "SMART-on-FHIR",
                                "display": "SMART-on-FHIR",
                            }
                        ]
                    }
                ],
            },
            "resource": [
                {"type": "Patient"},
                {"type": "Observation"},
                {"type": "Condition"},
                {"type": "MedicationRequest"},
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_client():
    """
    Pin the base URL and reset the shared client around every test.

    fhir_client caches one AsyncClient at module scope for connection reuse. In
    tests we reset it before and after each test so no client (or its captured
    state) leaks between tests, and we pin FHIR_BASE_URL so a stray env var on
    the developer's machine can't change where requests are aimed.
    """
    fhir_client.FHIR_BASE_URL = FHIR_BASE
    fhir_client.FHIR_ACCESS_TOKEN = None
    fhir_client._client = None
    yield
    fhir_client._client = None


@pytest.fixture
def mock_fhir():
    """
    Activate respx HTTP mocking scoped to the FHIR base URL.
    Any unmocked request will raise an error, catching accidental live calls.
    """
    with respx.mock(base_url=FHIR_BASE, assert_all_called=False) as mock:
        yield mock
