"""
FHIR R4 MCP Server.

MCP (Model Context Protocol) lets an AI assistant call tools that reach live
data sources. Each @mcp.tool() function below becomes a callable tool that
Claude (or any MCP client) can invoke by name. The function's signature becomes
the tool's input schema and its docstring becomes the description the model
reads to decide when and how to call it — so the docstrings here are not just
comments, they are part of the interface.

Tools map onto two FHIR REST interactions:
  - read   -> GET /{ResourceType}/{id}
  - search -> GET /{ResourceType}?param=value&...

Results are returned as readable clinical summaries (see formatters.py) rather
than raw JSON, so the model spends its context on signal, not boilerplate.
Every summary includes the resource id so the model can chain a follow-up read.
"""

import asyncio
import functools
import json
from typing import Any, Callable, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from . import fhir_client, formatters, interactions, loinc_codes

_BASE_INSTRUCTIONS = (
    "Query a FHIR R4 server for Patients, Observations, Conditions, "
    "MedicationRequests, Encounters (visits), AllergyIntolerance records, "
    "DiagnosticReports (labs, imaging, pathology), and Immunizations. "
    "Use search tools to find resources by demographic or clinical "
    "criteria, then read tools to retrieve full details by id. "
    "The check_medication_interactions tool flags known drug interactions "
    "from a local reference set (not for clinical use). "
    "Search results include a 'Next page' URL when more results exist; "
    "pass it to get_next_page to fetch the following page. "
    "Call check_connection first when pointing at a new endpoint to confirm "
    "the server is reachable, speaks R4, and to see its supported resources."
)


def _build_instructions() -> str:
    """
    Prepend the operator-provided FHIR_SERVER_LABEL to the instructions.

    Multi-backend setups register this server once per FHIR endpoint under
    different names; the label lets each instance announce its identity to
    the AI so it can (a) select the correct backend when the user names one
    and (b) be more cautious with backends labelled as production.
    """
    if fhir_client.FHIR_SERVER_LABEL:
        return f"[Backend: {fhir_client.FHIR_SERVER_LABEL}]\n\n{_BASE_INSTRUCTIONS}"
    return _BASE_INSTRUCTIONS


mcp = FastMCP("FHIR R4", instructions=_build_instructions())


def fhir_tool(func: Callable) -> Callable:
    """
    Decorator that converts httpx network/HTTP exceptions into readable strings.

    Applied to every MCP tool so the model receives a friendly explanation
    instead of a stack trace. functools.wraps preserves the original function's
    name, docstring, and type annotations so @mcp.tool() (applied on top) still
    reads the correct schema.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            url = str(e.request.url)
            if status == 404:
                return f"Not found (HTTP 404): {url}"
            if status >= 500:
                return f"FHIR server error (HTTP {status}): {url}. Try again later."
            return f"Request failed (HTTP {status}): {url}"
        except httpx.ConnectError as e:
            return (
                f"Could not connect to the FHIR server ({fhir_client.FHIR_BASE_URL}). "
                f"Check your FHIR_BASE_URL and network. Detail: {e}"
            )
        except httpx.TimeoutException:
            return (
                f"Request timed out after 30 s. "
                f"The FHIR server at {fhir_client.FHIR_BASE_URL} may be slow."
            )
        except ValueError as e:
            return f"Invalid request: {e}"

    return wrapper


def _capped_count(count: int) -> str:
    """FHIR _count param, capped at 50 to keep responses bounded."""
    return str(max(1, min(count, 50)))


def _validate_format(fmt: str) -> str:
    """
    Normalize the ``format`` tool argument.

    "text" (default) → human/AI-readable summary strings.
    "json"           → structured JSON documents shaped by models.py.
    """
    if fmt not in ("text", "json"):
        raise ValueError(f"format must be 'text' or 'json', got {fmt!r}")
    return fmt


def _json(payload: Any) -> str:
    """Serialize a dict/list to a JSON string for the MCP text envelope."""
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Connection preflight
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def check_connection(format: str = "text") -> str:
    """
    Verify the FHIR server is reachable and describe its capabilities.

    Fetches the server's CapabilityStatement from /metadata and returns a
    summary: FHIR version, server software, security requirements, and the
    list of supported resource types. Call this first when pointing at a new
    endpoint to confirm the connection works and the server actually speaks R4.

    - format: "text" (default, human-readable) or "json" (structured document
      shaped like {baseUrl, fhirVersion, isR4, serverName, resources, ...})
    """
    fmt = _validate_format(format)
    cap = await fhir_client.get_capability_statement()
    if fmt == "json":
        return _json(
            formatters.capability_to_json(
                cap, fhir_client.FHIR_BASE_URL, fhir_client.FHIR_SERVER_LABEL
            )
        )
    return formatters.format_capability_statement(
        cap, fhir_client.FHIR_BASE_URL, fhir_client.FHIR_SERVER_LABEL
    )


# ---------------------------------------------------------------------------
# Patient tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_patient(patient_id: str, format: str = "text") -> str:
    """
    Fetch a single Patient by FHIR id and return a readable summary.

    The summary includes name, gender, age/DOB, and identifiers (e.g. MRN).

    - format: "text" (default) or "json" for a structured document
      shaped like {id, name, gender, birthDate, ageYears, identifiers}.
    """
    fmt = _validate_format(format)
    resource = await fhir_client.read_resource("Patient", patient_id)
    if fmt == "json":
        return _json(formatters.patient_to_json(resource))
    return formatters.format_patient(resource)


@mcp.tool()
@fhir_tool
async def search_patients(
    name: Optional[str] = None,
    family: Optional[str] = None,
    given: Optional[str] = None,
    birthdate: Optional[str] = None,
    identifier: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for Patients.

      - name      : any part of the name (family or given)
      - family    : family / last name
      - given     : given / first name
      - birthdate : ISO date (YYYY-MM-DD); supports prefixes like ge1990-01-01
      - identifier: system|value, e.g. "http://hospital.org/mrn|12345"
      - count     : max results (default 10, max 50)
      - format    : "text" (default) or "json" for a bundle envelope
                    {total, returned, resources: [...], nextPage}

    Returns one summary line per matching patient, each prefixed with its id.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    for key, value in {
        "name": name,
        "family": family,
        "given": given,
        "birthdate": birthdate,
        "identifier": identifier,
    }.items():
        if value is not None:
            params[key] = value

    bundle = await fhir_client.search_resources("Patient", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Observation tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_observation(observation_id: str, format: str = "text") -> str:
    """
    Fetch a single Observation by FHIR id and return a readable summary.

    Observations are measurements and assertions: vitals, labs, imaging
    findings. The summary shows what was measured, the value, status, and time.

    - format: "text" (default) or "json" for a structured document.
    """
    fmt = _validate_format(format)
    resource = await fhir_client.read_resource("Observation", observation_id)
    if fmt == "json":
        return _json(formatters.observation_to_json(resource))
    return formatters.format_observation(resource)


@mcp.tool()
@fhir_tool
async def search_observations(
    patient: Optional[str] = None,
    code: Optional[str] = None,
    category: Optional[str] = None,
    date: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for Observations.

      - patient : patient id (or Patient/{id}) to filter by subject
      - code    : a LOINC code ("8867-4") OR a friendly name ("heart_rate",
                  "glucose", "hemoglobin_a1c") which is resolved to a code
      - category: "vital-signs", "laboratory", "imaging", etc.
      - date    : ISO date or range, e.g. "ge2024-01-01"
      - count   : max results (default 10, max 50)
      - format  : "text" (default) or "json" for a bundle envelope

    Returns one summary line per matching observation.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if code is not None:
        # Accept friendly names like "heart_rate" and resolve to LOINC.
        params["code"] = loinc_codes.resolve(code)
    if category is not None:
        params["category"] = category
    if date is not None:
        params["date"] = date

    bundle = await fhir_client.search_resources("Observation", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Condition tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def search_conditions(
    patient: Optional[str] = None,
    clinical_status: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for Conditions (problems / diagnoses).

      - patient        : patient id (or Patient/{id}) to filter by subject
      - clinical_status: "active", "recurrence", "resolved", etc.
      - count          : max results (default 10, max 50)
      - format         : "text" (default) or "json" for a bundle envelope

    Returns one summary line per condition with its clinical status and onset.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if clinical_status is not None:
        params["clinical-status"] = clinical_status

    bundle = await fhir_client.search_resources("Condition", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Medication tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def search_medications(
    patient: Optional[str] = None,
    status: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for MedicationRequests (prescriptions / orders).

      - patient : patient id (or Patient/{id}) to filter by subject
      - status  : "active", "completed", "stopped", "on-hold", etc.
      - count   : max results (default 10, max 50)
      - format  : "text" (default) or "json" for a bundle envelope

    Returns one summary line per medication order with status and dosage.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if status is not None:
        params["status"] = status

    bundle = await fhir_client.search_resources("MedicationRequest", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


@mcp.tool()
@fhir_tool
async def check_medication_interactions(
    medications: list[str], format: str = "text"
) -> str:
    """
    Check a list of medications for known pairwise drug interactions.

    Accepts generic or brand names (e.g. "warfarin", "Coumadin", "aspirin").
    Uses a small LOCAL reference set — NOT a substitute for clinical decision
    support. Returns each interaction found with a severity and explanation,
    most severe first, or a clear message when none are found.

    - format: "text" (default) or "json" — {medications, findings: [{severity,
      drugA, drugB, description}, ...]}
    """
    fmt = _validate_format(format)
    if len(medications) < 2:
        if fmt == "json":
            return _json({"medications": medications, "findings": []})
        return "Provide at least two medications to check for interactions."

    findings = interactions.check_medications(medications)

    if fmt == "json":
        return _json(
            {
                "medications": medications,
                "findings": [
                    {
                        "severity": f["severity"].upper(),
                        "drugA": f["drug_a"],
                        "drugB": f["drug_b"],
                        "description": f["description"],
                    }
                    for f in findings
                ],
            }
        )

    if not findings:
        return (
            f"No known interactions found among: {', '.join(medications)}. "
            "(Local reference set only — not for clinical use.)"
        )

    lines = [f"Found {len(findings)} potential interaction(s):"]
    for f in findings:
        lines.append(
            f"  - [{f['severity'].upper()}] {f['drug_a']} + {f['drug_b']}: "
            f"{f['description']}"
        )
    lines.append("(Local reference set only — not for clinical use.)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Encounter tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_encounter(encounter_id: str, format: str = "text") -> str:
    """
    Fetch a single Encounter by FHIR id and return a readable summary.

    An Encounter is a healthcare visit — an outpatient appointment, an ED
    visit, an inpatient admission. Summarizes type, class (setting), status,
    and time window.

    - format: "text" (default) or "json".
    """
    fmt = _validate_format(format)
    resource = await fhir_client.read_resource("Encounter", encounter_id)
    if fmt == "json":
        return _json(formatters.encounter_to_json(resource))
    return formatters.format_encounter(resource)


@mcp.tool()
@fhir_tool
async def search_encounters(
    patient: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for Encounters (healthcare visits).

      - patient : patient id (or Patient/{id}) to filter by subject
      - status  : "planned", "in-progress", "finished", "cancelled", etc.
      - date    : ISO date or range, e.g. "ge2024-01-01"
      - count   : max results (default 10, max 50)
      - format  : "text" (default) or "json" for a bundle envelope

    Returns one summary line per encounter with its type, class, and window.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if status is not None:
        params["status"] = status
    if date is not None:
        params["date"] = date

    bundle = await fhir_client.search_resources("Encounter", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# AllergyIntolerance tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_allergy_intolerance(allergy_id: str, format: str = "text") -> str:
    """
    Fetch a single AllergyIntolerance by FHIR id and return a readable summary.

    AllergyIntolerance records a documented sensitivity — food, medication,
    environmental, or biologic. Summarizes substance, criticality, clinical
    status, and the recorded reaction if any.

    - format: "text" (default) or "json".
    """
    fmt = _validate_format(format)
    resource = await fhir_client.read_resource("AllergyIntolerance", allergy_id)
    if fmt == "json":
        return _json(formatters.allergy_intolerance_to_json(resource))
    return formatters.format_allergy_intolerance(resource)


@mcp.tool()
@fhir_tool
async def search_allergy_intolerances(
    patient: Optional[str] = None,
    clinical_status: Optional[str] = None,
    category: Optional[str] = None,
    criticality: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for AllergyIntolerance records.

      - patient        : patient id (or Patient/{id}) to filter by subject
      - clinical_status: "active", "inactive", "resolved"
      - category       : "food", "medication", "environment", or "biologic"
      - criticality    : "low", "high", or "unable-to-assess"
      - count          : max results (default 10, max 50)
      - format         : "text" (default) or "json" for a bundle envelope

    Returns one summary line per allergy with its substance and reaction.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if clinical_status is not None:
        params["clinical-status"] = clinical_status
    if category is not None:
        params["category"] = category
    if criticality is not None:
        params["criticality"] = criticality

    bundle = await fhir_client.search_resources("AllergyIntolerance", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# DiagnosticReport tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_diagnostic_report(report_id: str, format: str = "text") -> str:
    """
    Fetch a single DiagnosticReport by FHIR id and return a readable summary.

    A DiagnosticReport groups related Observations under a single report —
    a CBC panel, an imaging study, a pathology report. Summarizes report type,
    status, effective date, and conclusion when present.

    - format: "text" (default) or "json".
    """
    fmt = _validate_format(format)
    resource = await fhir_client.read_resource("DiagnosticReport", report_id)
    if fmt == "json":
        return _json(formatters.diagnostic_report_to_json(resource))
    return formatters.format_diagnostic_report(resource)


@mcp.tool()
@fhir_tool
async def search_diagnostic_reports(
    patient: Optional[str] = None,
    category: Optional[str] = None,
    code: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for DiagnosticReports.

      - patient : patient id (or Patient/{id}) to filter by subject
      - category: "LAB", "RAD", "PATH", etc. (report classification)
      - code    : LOINC code (or friendly name like "hemoglobin_a1c") for the
                  specific report type
      - status  : "registered", "partial", "preliminary", "final", "amended"
      - date    : ISO date or range, e.g. "ge2024-01-01"
      - count   : max results (default 10, max 50)
      - format  : "text" (default) or "json" for a bundle envelope

    Returns one summary line per report with its code, category, and conclusion.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if category is not None:
        params["category"] = category
    if code is not None:
        params["code"] = loinc_codes.resolve(code)
    if status is not None:
        params["status"] = status
    if date is not None:
        params["date"] = date

    bundle = await fhir_client.search_resources("DiagnosticReport", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Immunization tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_immunization(immunization_id: str, format: str = "text") -> str:
    """
    Fetch a single Immunization by FHIR id and return a readable summary.

    Immunization records a vaccine dose administered (or not given, with
    reason). Summarizes vaccine, occurrence date, status, route, site, and
    dose quantity when recorded.

    - format: "text" (default) or "json".
    """
    fmt = _validate_format(format)
    resource = await fhir_client.read_resource("Immunization", immunization_id)
    if fmt == "json":
        return _json(formatters.immunization_to_json(resource))
    return formatters.format_immunization(resource)


@mcp.tool()
@fhir_tool
async def search_immunizations(
    patient: Optional[str] = None,
    status: Optional[str] = None,
    date: Optional[str] = None,
    count: int = 10,
    format: str = "text",
) -> str:
    """
    Search for Immunizations (vaccine administrations).

      - patient : patient id (or Patient/{id}) to filter by subject
      - status  : "completed", "entered-in-error", "not-done"
      - date    : ISO date or range, e.g. "ge2024-01-01"
      - count   : max results (default 10, max 50)
      - format  : "text" (default) or "json" for a bundle envelope

    Returns one summary line per vaccine dose administered.
    """
    fmt = _validate_format(format)
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if status is not None:
        params["status"] = status
    if date is not None:
        params["date"] = date

    bundle = await fhir_client.search_resources("Immunization", params)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def get_next_page(next_url: str, format: str = "text") -> str:
    """
    Fetch the next page of a FHIR search result.

    Pass the 'Next page' URL from any search result here. The URL must point
    to the same FHIR server (FHIR_BASE_URL) — other hosts are refused.

    - format: "text" (default) or "json" — same shape as the source search.
    """
    fmt = _validate_format(format)
    bundle = await fhir_client.fetch_next_page(next_url)
    if fmt == "json":
        return _json(formatters.bundle_to_json(bundle))
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Composite tool: one-shot clinical snapshot
# ---------------------------------------------------------------------------


def _resources(bundle_or_error: Any) -> list[dict[str, Any]]:
    """Pull resource dicts out of a Bundle, or [] if the fetch errored."""
    if isinstance(bundle_or_error, Exception):
        return []
    entries = bundle_or_error.get("entry") or []
    return [e.get("resource", {}) for e in entries]


def _section(title: str, items: list[str]) -> str:
    """Render a titled section, or a clear 'none' line when empty."""
    if not items:
        return f"{title}: none found"
    body = "\n".join(f"  - {line}" for line in items)
    return f"{title} ({len(items)}):\n{body}"


@mcp.tool()
@fhir_tool
async def get_patient_summary(patient_id: str, format: str = "text") -> str:
    """
    Build a one-shot clinical snapshot for a patient.

    Fetches, concurrently: the Patient, their active Conditions, recent
    vital-sign Observations, and active MedicationRequests. Then checks the
    active medications for known drug interactions. Returns a single readable
    summary. Individual sections degrade gracefully if a sub-query fails.

    - format: "text" (default) or "json" — {patient, activeConditions,
      recentVitals, activeMedications, interactionWarnings}
    """
    fmt = _validate_format(format)
    # Fire all four FHIR calls at once; gather waits for the slowest. With
    # return_exceptions=True a single failure becomes a value we can handle
    # rather than an exception that aborts the whole summary.
    patient, conditions, vitals, meds = await asyncio.gather(
        fhir_client.read_resource("Patient", patient_id),
        fhir_client.search_resources(
            "Condition",
            {"patient": patient_id, "clinical-status": "active", "_count": "20"},
        ),
        fhir_client.search_resources(
            "Observation",
            {"patient": patient_id, "category": "vital-signs", "_count": "10"},
        ),
        fhir_client.search_resources(
            "MedicationRequest",
            {"patient": patient_id, "status": "active", "_count": "20"},
        ),
        return_exceptions=True,
    )

    # The patient read is the one fetch we can't do without.
    if isinstance(patient, Exception):
        msg = f"Could not retrieve Patient {patient_id}: {patient}"
        if fmt == "json":
            return _json({"error": msg, "patientId": patient_id})
        return msg

    condition_resources = _resources(conditions)
    vital_resources = _resources(vitals)
    med_resources = _resources(meds)

    # Cross-check: extract drug names from the medication displays and run them
    # through the interaction checker.
    drug_names: list[str] = []
    for med in med_resources:
        if "medicationCodeableConcept" in med:
            text = formatters._coding_display(med["medicationCodeableConcept"])
        else:
            text = med.get("medicationReference", {}).get("display", "")
        drug_names.extend(interactions.extract_known_drugs(text))

    findings = interactions.check_medications(drug_names)

    if fmt == "json":
        return _json(
            {
                "patient": formatters.patient_to_json(patient),
                "activeConditions": [
                    formatters.condition_to_json(c) for c in condition_resources
                ],
                "recentVitals": [
                    formatters.observation_to_json(o) for o in vital_resources
                ],
                "activeMedications": [
                    formatters.medication_request_to_json(m) for m in med_resources
                ],
                "interactionWarnings": [
                    {
                        "severity": f["severity"].upper(),
                        "drugA": f["drug_a"],
                        "drugB": f["drug_b"],
                        "description": f["description"],
                    }
                    for f in findings
                ],
            }
        )

    lines = ["=== Patient Summary ===", formatters.format_patient(patient), ""]
    lines.append(
        _section(
            "Active conditions",
            [formatters.format_condition(c) for c in condition_resources],
        )
    )
    lines.append("")
    lines.append(
        _section(
            "Recent vital signs",
            [formatters.format_observation(o) for o in vital_resources],
        )
    )
    lines.append("")
    lines.append(
        _section(
            "Active medications",
            [formatters.format_medication_request(m) for m in med_resources],
        )
    )

    if findings:
        lines.append("")
        warnings = [
            f"[{f['severity'].upper()}] {f['drug_a']} + {f['drug_b']}: "
            f"{f['description']}"
            for f in findings
        ]
        lines.append(_section("Medication interaction warnings", warnings))
        lines.append("(Local reference set only — not for clinical use.)")

    return "\n".join(lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
