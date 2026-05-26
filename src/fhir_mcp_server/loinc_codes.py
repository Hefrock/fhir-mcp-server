"""
Curated LOINC codes for common vitals and labs.

LOINC (Logical Observation Identifiers Names and Codes) is the universal
standard for identifying *what was measured* in an Observation. A FHIR
Observation stores its meaning as a coding like:

    {"system": "http://loinc.org", "code": "8867-4", "display": "Heart rate"}

Forcing a user (or an LLM) to know "8867-4" is hostile. This module maps
friendly snake_case names to codes so a tool can accept ``code="heart_rate"``
and resolve it to ``8867-4`` before querying FHIR.

This is deliberately a small, hand-picked subset — not the full ~100k LOINC
database. It covers the codes a primary-care conversation actually hits.
"""

from __future__ import annotations

# Friendly name -> LOINC code. snake_case keys are what tools accept.
VITAL_SIGNS: dict[str, str] = {
    "heart_rate": "8867-4",
    "respiratory_rate": "9279-1",
    "body_temperature": "8310-5",
    "body_height": "8302-2",
    "body_weight": "29463-7",
    "bmi": "39156-5",
    "blood_pressure": "85354-9",  # systolic & diastolic panel
    "systolic_bp": "8480-6",
    "diastolic_bp": "8462-4",
    "oxygen_saturation": "2708-6",
}

LABS: dict[str, str] = {
    "glucose": "2339-0",
    "hemoglobin_a1c": "4548-4",
    "cholesterol_total": "2093-3",
    "ldl_cholesterol": "13457-7",
    "hdl_cholesterol": "2085-9",
    "triglycerides": "2571-8",
    "creatinine": "2160-0",
    "sodium": "2951-2",
    "potassium": "2823-3",
    "hemoglobin": "718-7",
    "white_blood_cell_count": "6690-2",
    "platelet_count": "777-3",
    "tsh": "3016-3",
}

# Merged view for lookups. Vitals and labs share one namespace of names.
ALL_CODES: dict[str, str] = {**VITAL_SIGNS, **LABS}

# Reverse map (code -> friendly name) for display/formatting.
CODE_TO_NAME: dict[str, str] = {code: name for name, code in ALL_CODES.items()}


def resolve(name_or_code: str) -> str:
    """
    Resolve a friendly name to its LOINC code.

    Accepts either a known friendly name ("heart_rate") or a raw code that
    looks like LOINC ("8867-4"). Unknown values are returned unchanged so the
    caller can still pass arbitrary codes straight through to FHIR.
    """
    key = name_or_code.strip().lower().replace(" ", "_").replace("-", "_")
    if key in ALL_CODES:
        return ALL_CODES[key]
    return name_or_code  # already a code, or something we don't curate


def describe(code: str) -> str:
    """Return the friendly name for a code, or the code itself if unknown."""
    return CODE_TO_NAME.get(code, code)
