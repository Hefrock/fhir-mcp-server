"""
Turn raw FHIR resources into readable clinical summaries.

Why this module exists
----------------------
FHIR JSON is verbose and deeply nested. Handing an LLM 400 lines of raw JSON
per patient wastes context and buries the signal. These formatters distill each
resource into a few human-readable lines that a model (and a person) can scan.

Two rules every formatter follows:

1. **Never assume structure.** Every FHIR element is optional and may repeat.
   We navigate with .get() and tolerate missing pieces rather than crashing.
2. **Always surface the resource id.** Search results must let the model chain
   a follow-up read_* call, which needs the id. So every summary leads with it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _coding_display(concept: dict[str, Any] | None) -> str:
    """
    Pull a human label out of a FHIR CodeableConcept.

    Prefers the top-level ``text``, then the first coding's ``display``, then
    its raw ``code``. Returns "unknown" if there's nothing usable.
    """
    if not concept:
        return "unknown"
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return coding["display"]
        if coding.get("code"):
            return coding["code"]
    return "unknown"


def _human_name(resource: dict[str, Any]) -> str:
    """Build 'Given Family' from the first HumanName, tolerating missing parts."""
    names = resource.get("name") or []
    if not names:
        return "(no name)"
    name = names[0]
    if name.get("text"):
        return name["text"]
    given = " ".join(name.get("given", []))
    family = name.get("family", "")
    full = f"{given} {family}".strip()
    return full or "(no name)"


def _age_from_birthdate(birth: str | None) -> str:
    """Compute integer age in years from a YYYY or YYYY-MM-DD birthDate."""
    if not birth:
        return "unknown age"
    try:
        born = datetime.strptime(birth[:10], "%Y-%m-%d").date()
    except ValueError:
        try:
            born = date(int(birth[:4]), 1, 1)
        except (ValueError, TypeError):
            return "unknown age"
    today = date.today()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return f"{years}y"


# ---------------------------------------------------------------------------
# Per-resource formatters
# ---------------------------------------------------------------------------


def format_patient(patient: dict[str, Any]) -> str:
    """One-line-ish summary: name, demographics, and identifiers."""
    pid = patient.get("id", "?")
    name = _human_name(patient)
    gender = patient.get("gender", "unknown")
    birth = patient.get("birthDate")
    age = _age_from_birthdate(birth)

    identifiers = []
    for ident in patient.get("identifier", []):
        label = _coding_display(ident.get("type")) if ident.get("type") else "id"
        value = ident.get("value", "")
        if value:
            identifiers.append(f"{label}={value}")
    ident_str = f" | {', '.join(identifiers)}" if identifiers else ""

    return (
        f"[Patient {pid}] {name}, {gender}, "
        f"{age} (DOB {birth or 'unknown'}){ident_str}"
    )


def format_observation(obs: dict[str, Any]) -> str:
    """Summary: what was measured, the value, when, and any flag."""
    oid = obs.get("id", "?")
    label = _coding_display(obs.get("code"))
    status = obs.get("status", "unknown")
    when = obs.get("effectiveDateTime", obs.get("issued", "unknown time"))

    # Observations carry their result in one of several value[x] shapes.
    value = "(no value)"
    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        value = f"{q.get('value', '?')} {q.get('unit', '')}".strip()
    elif "valueCodeableConcept" in obs:
        value = _coding_display(obs["valueCodeableConcept"])
    elif "valueString" in obs:
        value = obs["valueString"]
    elif "component" in obs:
        # e.g. blood pressure: systolic + diastolic components
        parts = []
        for comp in obs["component"]:
            c_label = _coding_display(comp.get("code"))
            cq = comp.get("valueQuantity", {})
            piece = f"{c_label} {cq.get('value', '?')} {cq.get('unit', '')}".strip()
            parts.append(piece)
        value = "; ".join(parts) if parts else value

    interp = ""
    for i in obs.get("interpretation", []):
        flag = _coding_display(i)
        if flag and flag != "unknown":
            interp = f" [{flag}]"
            break

    return f"[Observation {oid}] {label}: {value}{interp} ({status}, {when})"


def format_condition(cond: dict[str, Any]) -> str:
    """Summary: the problem, its clinical status, and onset."""
    cid = cond.get("id", "?")
    label = _coding_display(cond.get("code"))
    clinical = _coding_display(cond.get("clinicalStatus"))
    verification = _coding_display(cond.get("verificationStatus"))
    onset = cond.get("onsetDateTime", cond.get("recordedDate", "unknown onset"))
    return (
        f"[Condition {cid}] {label} — clinical: {clinical}, "
        f"verification: {verification}, onset: {onset}"
    )


def format_medication_request(med: dict[str, Any]) -> str:
    """Summary: the drug, status, and dosage instruction text."""
    mid = med.get("id", "?")
    # Medication may be inline (medicationCodeableConcept) or a reference.
    if "medicationCodeableConcept" in med:
        drug = _coding_display(med["medicationCodeableConcept"])
    else:
        ref = med.get("medicationReference", {})
        drug = ref.get("display", "unknown medication")
    status = med.get("status", "unknown")
    when = med.get("authoredOn", "unknown date")

    dosage = ""
    instructions = med.get("dosageInstruction") or []
    if instructions and instructions[0].get("text"):
        dosage = f" — {instructions[0]['text']}"

    return f"[MedicationRequest {mid}] {drug} ({status}, ordered {when}){dosage}"


# ---------------------------------------------------------------------------
# Bundle formatting
# ---------------------------------------------------------------------------

_FORMATTERS = {
    "Patient": format_patient,
    "Observation": format_observation,
    "Condition": format_condition,
    "MedicationRequest": format_medication_request,
}


def format_resource(resource: dict[str, Any]) -> str:
    """Dispatch a single resource to the right formatter by resourceType."""
    rtype = resource.get("resourceType", "")
    formatter = _FORMATTERS.get(rtype)
    if formatter is None:
        return f"[{rtype or 'Unknown'} {resource.get('id', '?')}] (no formatter)"
    return formatter(resource)


def format_bundle(bundle: dict[str, Any]) -> str:
    """
    Render a FHIR searchset Bundle as a readable list.

    Includes the reported total and one summary line per entry. An empty
    searchset returns a clear 'no matches' message rather than a blank string.
    """
    total = bundle.get("total", 0)
    entries = bundle.get("entry") or []
    if not entries:
        return f"No matching resources (total reported: {total})."

    lines = [f"Found {len(entries)} result(s) (total reported: {total}):"]
    for entry in entries:
        resource = entry.get("resource", {})
        lines.append(f"  - {format_resource(resource)}")
    return "\n".join(lines)
