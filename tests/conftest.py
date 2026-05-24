"""
Shared pytest fixtures and sample FHIR data.

respx is an httpx-native mock library: it intercepts outgoing requests at
the transport layer, so our async client code runs unmodified while tests
never touch the network.
"""

import pytest
import respx

FHIR_BASE = "https://hapi.fhir.org/baseR4"

# ---------------------------------------------------------------------------
# Sample FHIR resources
# ---------------------------------------------------------------------------

SAMPLE_PATIENT = {
    "resourceType": "Patient",
    "id": "example",
    "name": [{"use": "official", "family": "Smith", "given": ["John"]}],
    "gender": "male",
    "birthDate": "1990-06-15",
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
            {
                "system": "http://loinc.org",
                "code": "8867-4",
                "display": "Heart rate",
            }
        ]
    },
    "subject": {"reference": "Patient/example"},
    "valueQuantity": {"value": 72, "unit": "beats/minute", "system": "http://unitsofmeasure.org"},
}

SAMPLE_OBSERVATION_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {"fullUrl": f"{FHIR_BASE}/Observation/obs-hr-1", "resource": SAMPLE_OBSERVATION}
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_fhir():
    """
    Activate respx HTTP mocking scoped to the FHIR base URL.
    Any unmocked request will raise an error, catching accidental live calls.
    """
    with respx.mock(base_url=FHIR_BASE, assert_all_called=False) as mock:
        yield mock
