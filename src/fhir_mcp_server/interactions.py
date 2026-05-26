"""
Local medication interaction lookup.

Real clinical decision support pulls from licensed databases (First Databank,
Micromedex). This module is a *teaching-grade* local substitute: a curated set
of well-known, clinically significant pairwise interactions, keyed so lookup is
order-independent and tolerant of brand names.

NOT FOR CLINICAL USE. It is intentionally incomplete and exists to demonstrate
the data-modeling pattern, not to guide prescribing.

Design notes
------------
* Interactions are pairwise and symmetric, so we key each one on a
  ``frozenset({drug_a, drug_b})``. ``frozenset`` is hashable (usable as a dict
  key) and ignores order — {"a","b"} == {"b","a"}.
* Inputs are normalized to a canonical generic name via ``_SYNONYMS`` before
  lookup, so "Coumadin", "coumadin", and "warfarin" all collapse to "warfarin".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations

# Brand / alias -> canonical generic name. Extend freely.
_SYNONYMS: dict[str, str] = {
    "coumadin": "warfarin",
    "jantoven": "warfarin",
    "asa": "aspirin",
    "acetylsalicylic acid": "aspirin",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "zocor": "simvastatin",
    "glucophage": "metformin",
    "prinivil": "lisinopril",
    "zestril": "lisinopril",
    "aldactone": "spironolactone",
    "lanoxin": "digoxin",
    "biaxin": "clarithromycin",
    "viagra": "sildenafil",
    "prozac": "fluoxetine",
    "nardil": "phenelzine",
    "prilosec": "omeprazole",
    "plavix": "clopidogrel",
}


@dataclass(frozen=True)
class Interaction:
    """One pairwise interaction record."""

    severity: str  # "major" | "moderate" | "minor"
    description: str


# Each key is an unordered pair of canonical generic names.
_INTERACTIONS: dict[frozenset[str], Interaction] = {
    frozenset({"warfarin", "aspirin"}): Interaction(
        "major", "Additive bleeding risk; concurrent use raises hemorrhage risk."
    ),
    frozenset({"warfarin", "ibuprofen"}): Interaction(
        "major", "NSAIDs increase bleeding risk and may potentiate warfarin."
    ),
    frozenset({"warfarin", "amiodarone"}): Interaction(
        "major", "Amiodarone inhibits warfarin metabolism, raising INR/bleeding risk."
    ),
    frozenset({"lisinopril", "spironolactone"}): Interaction(
        "moderate", "Both raise serum potassium; risk of hyperkalemia."
    ),
    frozenset({"lisinopril", "potassium"}): Interaction(
        "moderate", "ACE inhibitor plus potassium supplement risks hyperkalemia."
    ),
    frozenset({"simvastatin", "clarithromycin"}): Interaction(
        "major", "CYP3A4 inhibition raises statin levels; rhabdomyolysis risk."
    ),
    frozenset({"simvastatin", "amlodipine"}): Interaction(
        "moderate", "Amlodipine raises simvastatin exposure; limit simvastatin dose."
    ),
    frozenset({"digoxin", "amiodarone"}): Interaction(
        "major", "Amiodarone raises digoxin levels; risk of digoxin toxicity."
    ),
    frozenset({"sildenafil", "nitroglycerin"}): Interaction(
        "major", "Concurrent use causes profound, potentially fatal hypotension."
    ),
    frozenset({"fluoxetine", "phenelzine"}): Interaction(
        "major", "SSRI + MAOI risks serotonin syndrome; contraindicated."
    ),
    frozenset({"clopidogrel", "omeprazole"}): Interaction(
        "moderate", "Omeprazole may reduce clopidogrel activation and efficacy."
    ),
    frozenset({"metformin", "contrast"}): Interaction(
        "moderate", "Hold metformin around iodinated contrast; lactic acidosis risk."
    ),
}


def _normalize(drug: str) -> str:
    """Lowercase, trim, and map brand names to canonical generic names."""
    key = drug.strip().lower()
    return _SYNONYMS.get(key, key)


def check_pair(drug_a: str, drug_b: str) -> Interaction | None:
    """Return the Interaction for a pair, or None if no known interaction."""
    return _INTERACTIONS.get(frozenset({_normalize(drug_a), _normalize(drug_b)}))


def check_medications(drugs: list[str]) -> list[dict[str, str]]:
    """
    Check every unique pair in a medication list for known interactions.

    Returns a list of dicts (sorted by severity, most severe first), each with
    the two drugs as the caller wrote them plus severity and description.
    """
    severity_rank = {"major": 0, "moderate": 1, "minor": 2}
    findings: list[dict[str, str]] = []

    # combinations() yields each unordered pair exactly once, so we never
    # double-report (a,b) and (b,a).
    for a, b in combinations(drugs, 2):
        hit = check_pair(a, b)
        if hit is not None:
            findings.append(
                {
                    "drug_a": a,
                    "drug_b": b,
                    "severity": hit.severity,
                    "description": hit.description,
                }
            )

    findings.sort(key=lambda f: severity_rank.get(f["severity"], 99))
    return findings


# Vocabulary of every name we recognize: canonical generics (drawn from the
# interaction table) plus brand aliases. Derived from the data above so it can
# never drift out of sync with it.
_KNOWN_NAMES: set[str] = (
    {name for pair in _INTERACTIONS for name in pair}
    | set(_SYNONYMS.keys())
    | set(_SYNONYMS.values())
)


def extract_known_drugs(text: str) -> list[str]:
    """
    Find known drug names mentioned in free text (e.g. a FHIR medication
    display like "Warfarin 5 mg oral tablet") and return them as canonical
    generic names, de-duplicated.

    Matching is word-boundary based so "aspirin" matches but a substring inside
    a larger word does not.
    """
    lowered = text.lower()
    found: list[str] = []
    for name in _KNOWN_NAMES:
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            generic = _normalize(name)
            if generic not in found:
                found.append(generic)
    return found
