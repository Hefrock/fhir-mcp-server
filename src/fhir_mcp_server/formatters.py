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

from . import models

# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _coding_display(concept: dict[str, Any] | None) -> str:
    """
    Pull a human label out of a FHIR CodeableConcept or Coding.

    A CodeableConcept has ``text`` and/or a ``coding[]`` list. A bare Coding
    (used by e.g. Encounter.class) has ``display``/``code`` at the top level.
    We prefer the most human-readable option available: text → coding.display
    → coding.code → this-level display → this-level code → "unknown".
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
    if concept.get("display"):
        return concept["display"]
    if concept.get("code"):
        return concept["code"]
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


def format_encounter(enc: dict[str, Any]) -> str:
    """Summary: visit type/reason, class (setting), status, and time window."""
    eid = enc.get("id", "?")
    enc_class = _coding_display(enc.get("class")) if enc.get("class") else "unknown"
    type_ = "unknown"
    types = enc.get("type") or []
    if types:
        type_ = _coding_display(types[0])
    status = enc.get("status", "unknown")
    period = enc.get("period") or {}
    start = period.get("start", "unknown start")
    end = period.get("end", "ongoing")
    reason = ""
    reasons = enc.get("reasonCode") or []
    if reasons:
        reason_text = _coding_display(reasons[0])
        if reason_text and reason_text != "unknown":
            reason = f" — {reason_text}"
    return (
        f"[Encounter {eid}] {type_} ({enc_class}, {status}, "
        f"{start} → {end}){reason}"
    )


def format_diagnostic_report(r: dict[str, Any]) -> str:
    """Summary: report type/code, status, effective date, and conclusion."""
    rid = r.get("id", "?")
    label = _coding_display(r.get("code"))
    categories = r.get("category") or []
    category = _coding_display(categories[0]) if categories else "unknown category"
    status = r.get("status", "unknown")
    when = r.get("effectiveDateTime") or r.get("issued", "unknown time")
    performers = r.get("performer") or []
    performer_str = ""
    if performers:
        p_display = performers[0].get("display") or performers[0].get("reference")
        if p_display:
            performer_str = f" by {p_display}"
    results = r.get("result") or []
    result_str = f" — {len(results)} result(s)" if results else ""
    conclusion = r.get("conclusion")
    conclusion_str = f" — {conclusion}" if conclusion else ""
    return (
        f"[DiagnosticReport {rid}] {label} ({category}, {status}, "
        f"{when}){performer_str}{result_str}{conclusion_str}"
    )


def format_immunization(imm: dict[str, Any]) -> str:
    """Summary: vaccine, occurrence date, status, and route/dose if recorded."""
    iid = imm.get("id", "?")
    vaccine = _coding_display(imm.get("vaccineCode"))
    status = imm.get("status", "unknown")
    when = (
        imm.get("occurrenceDateTime") or imm.get("occurrenceString") or "unknown date"
    )
    route = _coding_display(imm.get("route")) if imm.get("route") else None
    site = _coding_display(imm.get("site")) if imm.get("site") else None
    dose = imm.get("doseQuantity") or {}
    dose_str = ""
    if dose.get("value") is not None:
        dose_str = f" {dose.get('value')} {dose.get('unit', '')}".rstrip()

    extras = []
    if dose_str:
        extras.append(f"dose:{dose_str}")
    if route and route != "unknown":
        extras.append(f"route: {route}")
    if site and site != "unknown":
        extras.append(f"site: {site}")
    extras_str = f" — {', '.join(extras)}" if extras else ""

    return f"[Immunization {iid}] {vaccine} ({status}, {when}){extras_str}"


def format_allergy_intolerance(a: dict[str, Any]) -> str:
    """Summary: substance, category/type, criticality, and reaction if recorded."""
    aid = a.get("id", "?")
    substance = _coding_display(a.get("code"))
    a_type = a.get("type") or "unknown type"
    categories = ", ".join(a.get("category") or []) or "unspecified category"
    criticality = a.get("criticality") or "unknown criticality"
    cs = a.get("clinicalStatus")
    clinical = _coding_display(cs) if cs else "unknown"
    reaction_str = ""
    reactions = a.get("reaction") or []
    if reactions:
        first = reactions[0]
        manifestations = [
            _coding_display(m) for m in (first.get("manifestation") or [])
        ]
        sev = first.get("severity")
        parts = []
        if manifestations:
            parts.append(", ".join(m for m in manifestations if m and m != "unknown"))
        if sev:
            parts.append(f"severity: {sev}")
        if parts:
            reaction_str = f" — reaction: {'; '.join(parts)}"
    return (
        f"[AllergyIntolerance {aid}] {substance} ({a_type}, {categories}, "
        f"criticality: {criticality}, clinical: {clinical}){reaction_str}"
    )


# ---------------------------------------------------------------------------
# Bundle formatting
# ---------------------------------------------------------------------------

def format_capability_statement(cap: dict[str, Any], base_url: str) -> str:
    """
    Summarize a FHIR CapabilityStatement (returned by GET /metadata).

    Surfaces the fields that matter for a preflight check: FHIR version,
    server software identification, security service (auth requirements),
    and the set of supported resource types. Flags a non-R4 fhirVersion so
    the user learns immediately that this server doesn't match what this
    MCP server targets.
    """
    fhir_version = cap.get("fhirVersion", "unknown")

    software = cap.get("software") or {}
    sw_name = software.get("name", "unknown server")
    sw_version = software.get("version")
    sw_line = f"{sw_name} v{sw_version}" if sw_version else sw_name

    impl = cap.get("implementation") or {}
    description = impl.get("description")

    # rest[0] is the standard shape; some servers publish multiple modes.
    rest_entries = cap.get("rest") or []
    security_services: list[str] = []
    resource_types: list[str] = []
    if rest_entries:
        first = rest_entries[0]
        security = first.get("security") or {}
        for svc in security.get("service") or []:
            label = _coding_display(svc)
            if label and label != "unknown":
                security_services.append(label)
        for res in first.get("resource") or []:
            rtype = res.get("type")
            if rtype:
                resource_types.append(rtype)

    lines = [f"FHIR endpoint at {base_url}"]
    lines.append(f"  Server: {sw_line}")
    if description:
        lines.append(f"  Implementation: {description}")

    version_line = f"  FHIR version: {fhir_version}"
    if fhir_version != "unknown" and not fhir_version.startswith("4"):
        version_line += "  ⚠ this server does not report FHIR R4 (this tool targets R4)"
    lines.append(version_line)

    if security_services:
        lines.append(f"  Security: {', '.join(security_services)}")
    else:
        lines.append("  Security: none advertised (open / unauthenticated)")

    if resource_types:
        lines.append(f"  Supported resources ({len(resource_types)}): "
                     f"{', '.join(resource_types)}")
    else:
        lines.append("  Supported resources: none advertised")

    return "\n".join(lines)


_FORMATTERS = {
    "Patient": format_patient,
    "Observation": format_observation,
    "Condition": format_condition,
    "MedicationRequest": format_medication_request,
    "Encounter": format_encounter,
    "AllergyIntolerance": format_allergy_intolerance,
    "DiagnosticReport": format_diagnostic_report,
    "Immunization": format_immunization,
}


def format_resource(resource: dict[str, Any]) -> str:
    """Dispatch a single resource to the right formatter by resourceType."""
    rtype = resource.get("resourceType", "")
    formatter = _FORMATTERS.get(rtype)
    if formatter is None:
        return f"[{rtype or 'Unknown'} {resource.get('id', '?')}] (no formatter)"
    return formatter(resource)


# ---------------------------------------------------------------------------
# JSON companions — structured shape for programmatic consumers
#
# Each ``*_to_json`` function mirrors the corresponding ``format_*`` function
# but returns a plain dict shaped by the Pydantic models in models.py. The
# models validate the structure; ``.model_dump(by_alias=True)`` emits camelCase
# keys where a FHIR field uses camelCase (birthDate, authoredOn, etc.).
# ---------------------------------------------------------------------------


def _age_years(birth: str | None) -> int | None:
    """Integer age; None if birthdate is missing or unparseable."""
    if not birth:
        return None
    try:
        born = datetime.strptime(birth[:10], "%Y-%m-%d").date()
    except ValueError:
        try:
            born = date(int(birth[:4]), 1, 1)
        except (ValueError, TypeError):
            return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def patient_to_json(patient: dict[str, Any]) -> dict[str, Any]:
    identifiers: list[dict[str, str]] = []
    for ident in patient.get("identifier", []):
        label = _coding_display(ident.get("type")) if ident.get("type") else "id"
        value = ident.get("value")
        if value:
            identifiers.append({"type": label, "value": str(value)})

    model = models.PatientJson(
        id=str(patient.get("id", "?")),
        name=_human_name(patient),
        gender=patient.get("gender"),
        birth_date=patient.get("birthDate"),
        age_years=_age_years(patient.get("birthDate")),
        identifiers=[models.IdentifierJson(**i) for i in identifiers],
    )
    return model.model_dump(by_alias=True)


def observation_to_json(obs: dict[str, Any]) -> dict[str, Any]:
    value = models.ObservationValueJson()
    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        value.quantity = q.get("value")
        value.unit = q.get("unit")
    elif "valueCodeableConcept" in obs:
        value.coded = _coding_display(obs["valueCodeableConcept"])
    elif "valueString" in obs:
        value.string = obs["valueString"]
    elif "component" in obs:
        for comp in obs["component"]:
            cq = comp.get("valueQuantity", {}) or {}
            value.components.append(
                models.ObservationComponentJson(
                    label=_coding_display(comp.get("code")),
                    quantity=cq.get("value"),
                    unit=cq.get("unit"),
                )
            )

    interpretation = None
    for i in obs.get("interpretation", []):
        flag = _coding_display(i)
        if flag and flag != "unknown":
            interpretation = flag
            break

    model = models.ObservationJson(
        id=str(obs.get("id", "?")),
        codeDisplay=_coding_display(obs.get("code")),
        status=obs.get("status"),
        effectiveDate=obs.get("effectiveDateTime") or obs.get("issued"),
        value=value,
        interpretation=interpretation,
    )
    return model.model_dump(by_alias=True)


def condition_to_json(cond: dict[str, Any]) -> dict[str, Any]:
    model = models.ConditionJson(
        id=str(cond.get("id", "?")),
        codeDisplay=_coding_display(cond.get("code")),
        clinicalStatus=_coding_display(cond.get("clinicalStatus"))
        if cond.get("clinicalStatus")
        else None,
        verificationStatus=_coding_display(cond.get("verificationStatus"))
        if cond.get("verificationStatus")
        else None,
        onset=cond.get("onsetDateTime") or cond.get("recordedDate"),
    )
    return model.model_dump(by_alias=True)


def medication_request_to_json(med: dict[str, Any]) -> dict[str, Any]:
    if "medicationCodeableConcept" in med:
        drug = _coding_display(med["medicationCodeableConcept"])
    else:
        drug = med.get("medicationReference", {}).get("display", "unknown medication")

    dosage_text = None
    instructions = med.get("dosageInstruction") or []
    if instructions and instructions[0].get("text"):
        dosage_text = instructions[0]["text"]

    model = models.MedicationRequestJson(
        id=str(med.get("id", "?")),
        drug=drug,
        status=med.get("status"),
        authoredOn=med.get("authoredOn"),
        dosageText=dosage_text,
    )
    return model.model_dump(by_alias=True)


def capability_to_json(cap: dict[str, Any], base_url: str) -> dict[str, Any]:
    fhir_version = cap.get("fhirVersion", "unknown")

    software = cap.get("software") or {}
    impl = cap.get("implementation") or {}
    rest_entries = cap.get("rest") or []

    security_services: list[str] = []
    resource_types: list[str] = []
    if rest_entries:
        first = rest_entries[0]
        for svc in (first.get("security") or {}).get("service") or []:
            label = _coding_display(svc)
            if label and label != "unknown":
                security_services.append(label)
        for res in first.get("resource") or []:
            rtype = res.get("type")
            if rtype:
                resource_types.append(rtype)

    model = models.CapabilityJson(
        baseUrl=base_url,
        fhirVersion=fhir_version,
        isR4=fhir_version.startswith("4"),
        serverName=software.get("name"),
        serverVersion=software.get("version"),
        implementation=impl.get("description"),
        securityServices=security_services,
        resources=resource_types,
    )
    return model.model_dump(by_alias=True)


def encounter_to_json(enc: dict[str, Any]) -> dict[str, Any]:
    types = enc.get("type") or []
    reasons = enc.get("reasonCode") or []
    period = enc.get("period") or {}
    provider = enc.get("serviceProvider") or {}

    model = models.EncounterJson(
        id=str(enc.get("id", "?")),
        status=enc.get("status"),
        **{"class": _coding_display(enc.get("class")) if enc.get("class") else None},
        type=_coding_display(types[0]) if types else None,
        reason=_coding_display(reasons[0]) if reasons else None,
        start=period.get("start"),
        end=period.get("end"),
        serviceProvider=provider.get("display") or provider.get("reference"),
    )
    return model.model_dump(by_alias=True)


def allergy_intolerance_to_json(a: dict[str, Any]) -> dict[str, Any]:
    reactions = []
    for r in a.get("reaction") or []:
        manifestations = [
            _coding_display(m) for m in (r.get("manifestation") or [])
        ]
        manifestations = [m for m in manifestations if m and m != "unknown"]
        reactions.append(
            models.AllergyReactionJson(
                manifestations=manifestations, severity=r.get("severity")
            )
        )

    model = models.AllergyIntoleranceJson(
        id=str(a.get("id", "?")),
        substance=_coding_display(a.get("code")),
        type=a.get("type"),
        categories=a.get("category") or [],
        criticality=a.get("criticality"),
        clinicalStatus=_coding_display(a.get("clinicalStatus"))
        if a.get("clinicalStatus")
        else None,
        verificationStatus=_coding_display(a.get("verificationStatus"))
        if a.get("verificationStatus")
        else None,
        recordedDate=a.get("recordedDate"),
        reactions=reactions,
    )
    return model.model_dump(by_alias=True)


def diagnostic_report_to_json(r: dict[str, Any]) -> dict[str, Any]:
    categories = r.get("category") or []
    performers = r.get("performer") or []
    performer_display = None
    if performers:
        first = performers[0]
        performer_display = first.get("display") or first.get("reference")

    model = models.DiagnosticReportJson(
        id=str(r.get("id", "?")),
        codeDisplay=_coding_display(r.get("code")),
        category=_coding_display(categories[0]) if categories else None,
        status=r.get("status"),
        effectiveDate=r.get("effectiveDateTime"),
        issued=r.get("issued"),
        performer=performer_display,
        resultReferences=[
            ref.get("reference") for ref in (r.get("result") or [])
            if ref.get("reference")
        ],
        conclusion=r.get("conclusion"),
    )
    return model.model_dump(by_alias=True)


def immunization_to_json(imm: dict[str, Any]) -> dict[str, Any]:
    dose = imm.get("doseQuantity") or {}
    model = models.ImmunizationJson(
        id=str(imm.get("id", "?")),
        vaccine=_coding_display(imm.get("vaccineCode")),
        status=imm.get("status"),
        occurrence=imm.get("occurrenceDateTime") or imm.get("occurrenceString"),
        lotNumber=imm.get("lotNumber"),
        site=_coding_display(imm.get("site")) if imm.get("site") else None,
        route=_coding_display(imm.get("route")) if imm.get("route") else None,
        doseQuantity=dose.get("value"),
        doseUnit=dose.get("unit"),
    )
    return model.model_dump(by_alias=True)


_JSON_FORMATTERS = {
    "Patient": patient_to_json,
    "Observation": observation_to_json,
    "Condition": condition_to_json,
    "MedicationRequest": medication_request_to_json,
    "Encounter": encounter_to_json,
    "AllergyIntolerance": allergy_intolerance_to_json,
    "DiagnosticReport": diagnostic_report_to_json,
    "Immunization": immunization_to_json,
}


def resource_to_json(resource: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a single resource to its JSON formatter."""
    rtype = resource.get("resourceType", "")
    fn = _JSON_FORMATTERS.get(rtype)
    if fn is None:
        return {
            "resourceType": rtype or "Unknown",
            "id": str(resource.get("id", "?")),
        }
    return fn(resource)


def bundle_to_json(bundle: dict[str, Any]) -> dict[str, Any]:
    """Envelope: total, returned count, resources, and pagination cursor."""
    entries = bundle.get("entry") or []
    resources = [resource_to_json(e.get("resource", {})) for e in entries]
    model = models.BundleJson(
        total=bundle.get("total", 0),
        returned=len(resources),
        resources=resources,
        nextPage=_next_link(bundle),
    )
    return model.model_dump(by_alias=True)


def _next_link(bundle: dict[str, Any]) -> str | None:
    """Return the 'next' pagination URL from a Bundle's link array, or None."""
    for link in bundle.get("link") or []:
        if link.get("relation") == "next":
            return link.get("url")
    return None


def format_bundle(bundle: dict[str, Any]) -> str:
    """
    Render a FHIR searchset Bundle as a readable list.

    Includes the reported total, one summary line per entry, and — when the
    server signals more pages — a 'Next page' URL the model can pass to
    get_next_page. An empty searchset returns a clear 'no matches' message.
    """
    total = bundle.get("total", 0)
    entries = bundle.get("entry") or []
    if not entries:
        return f"No matching resources (total reported: {total})."

    lines = [f"Found {len(entries)} result(s) (total reported: {total}):"]
    for entry in entries:
        resource = entry.get("resource", {})
        lines.append(f"  - {format_resource(resource)}")

    next_url = _next_link(bundle)
    if next_url:
        lines.append(f"Next page: {next_url}")

    return "\n".join(lines)
