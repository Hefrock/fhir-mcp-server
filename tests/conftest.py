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


SAMPLE_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-ambulatory-1",
    "status": "finished",
    "class": {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "AMB",
        "display": "ambulatory",
    },
    "type": [{"text": "Primary care visit"}],
    "subject": {"reference": "Patient/example"},
    "period": {"start": "2024-03-01T09:00:00Z", "end": "2024-03-01T09:30:00Z"},
    "reasonCode": [{"text": "Annual physical exam"}],
    "serviceProvider": {"reference": "Organization/1", "display": "Community Clinic"},
}

SAMPLE_ENCOUNTER_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {
            "fullUrl": f"{FHIR_BASE}/Encounter/enc-ambulatory-1",
            "resource": SAMPLE_ENCOUNTER,
        }
    ],
}

SAMPLE_ALLERGY = {
    "resourceType": "AllergyIntolerance",
    "id": "allergy-penicillin",
    "clinicalStatus": {
        "coding": [{"code": "active"}],
        "text": "active",
    },
    "verificationStatus": {"text": "confirmed"},
    "type": "allergy",
    "category": ["medication"],
    "criticality": "high",
    "code": {"text": "Penicillin"},
    "patient": {"reference": "Patient/example"},
    "recordedDate": "2015-06-10",
    "reaction": [
        {
            "manifestation": [{"text": "Hives"}, {"text": "Difficulty breathing"}],
            "severity": "severe",
        }
    ],
}

SAMPLE_ALLERGY_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {
            "fullUrl": f"{FHIR_BASE}/AllergyIntolerance/allergy-penicillin",
            "resource": SAMPLE_ALLERGY,
        }
    ],
}

SAMPLE_DIAGNOSTIC_REPORT = {
    "resourceType": "DiagnosticReport",
    "id": "dr-cbc-1",
    "status": "final",
    "category": [
        {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                    "code": "LAB",
                    "display": "Laboratory",
                }
            ]
        }
    ],
    "code": {
        "coding": [
            {"system": "http://loinc.org", "code": "58410-2", "display": "CBC panel"}
        ],
        "text": "Complete blood count",
    },
    "subject": {"reference": "Patient/example"},
    "effectiveDateTime": "2024-03-01",
    "issued": "2024-03-02T10:15:00Z",
    "performer": [{"display": "Community Labs"}],
    "result": [
        {"reference": "Observation/obs-hgb", "display": "Hemoglobin 12.5 g/dL"},
        {"reference": "Observation/obs-wbc", "display": "WBC 5.2 x10^9/L"},
    ],
    "conclusion": "Normal CBC. No cytopenias.",
}

SAMPLE_DIAGNOSTIC_REPORT_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {
            "fullUrl": f"{FHIR_BASE}/DiagnosticReport/dr-cbc-1",
            "resource": SAMPLE_DIAGNOSTIC_REPORT,
        }
    ],
}

SAMPLE_IMMUNIZATION = {
    "resourceType": "Immunization",
    "id": "imm-flu-2024",
    "status": "completed",
    "vaccineCode": {
        "coding": [
            {"system": "http://hl7.org/fhir/sid/cvx", "code": "158",
             "display": "Influenza, injectable, quadrivalent"}
        ],
        "text": "Influenza vaccine (quadrivalent)",
    },
    "patient": {"reference": "Patient/example"},
    "occurrenceDateTime": "2024-10-15",
    "primarySource": True,
    "lotNumber": "AB123CD",
    "site": {"text": "Left deltoid"},
    "route": {"text": "Intramuscular"},
    "doseQuantity": {"value": 0.5, "unit": "mL"},
}

SAMPLE_IMMUNIZATION_BUNDLE = {
    "resourceType": "Bundle",
    "type": "searchset",
    "total": 1,
    "entry": [
        {
            "fullUrl": f"{FHIR_BASE}/Immunization/imm-flu-2024",
            "resource": SAMPLE_IMMUNIZATION,
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
