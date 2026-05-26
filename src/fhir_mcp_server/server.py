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
from typing import Any, Callable, Optional

import httpx
from mcp.server.fastmcp import FastMCP

from . import fhir_client, formatters, interactions, loinc_codes

mcp = FastMCP(
    "FHIR R4",
    instructions=(
        "Query a FHIR R4 server for Patients, Observations, Conditions, and "
        "MedicationRequests. Use search tools to find resources by demographic "
        "or clinical criteria, then read tools to retrieve full details by id. "
        "The check_medication_interactions tool flags known drug interactions "
        "from a local reference set (not for clinical use). "
        "Search results include a 'Next page' URL when more results exist; "
        "pass it to get_next_page to fetch the following page."
    ),
)


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


# ---------------------------------------------------------------------------
# Patient tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_patient(patient_id: str) -> str:
    """
    Fetch a single Patient by FHIR id and return a readable summary.

    The summary includes name, gender, age/DOB, and identifiers (e.g. MRN).
    """
    resource = await fhir_client.read_resource("Patient", patient_id)
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
) -> str:
    """
    Search for Patients.

      - name      : any part of the name (family or given)
      - family    : family / last name
      - given     : given / first name
      - birthdate : ISO date (YYYY-MM-DD); supports prefixes like ge1990-01-01
      - identifier: system|value, e.g. "http://hospital.org/mrn|12345"
      - count     : max results (default 10, max 50)

    Returns one summary line per matching patient, each prefixed with its id.
    """
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
    return formatters.format_bundle(bundle)


# ---------------------------------------------------------------------------
# Observation tools
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def read_observation(observation_id: str) -> str:
    """
    Fetch a single Observation by FHIR id and return a readable summary.

    Observations are measurements and assertions: vitals, labs, imaging
    findings. The summary shows what was measured, the value, status, and time.
    """
    resource = await fhir_client.read_resource("Observation", observation_id)
    return formatters.format_observation(resource)


@mcp.tool()
@fhir_tool
async def search_observations(
    patient: Optional[str] = None,
    code: Optional[str] = None,
    category: Optional[str] = None,
    date: Optional[str] = None,
    count: int = 10,
) -> str:
    """
    Search for Observations.

      - patient : patient id (or Patient/{id}) to filter by subject
      - code    : a LOINC code ("8867-4") OR a friendly name ("heart_rate",
                  "glucose", "hemoglobin_a1c") which is resolved to a code
      - category: "vital-signs", "laboratory", "imaging", etc.
      - date    : ISO date or range, e.g. "ge2024-01-01"
      - count   : max results (default 10, max 50)

    Returns one summary line per matching observation.
    """
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
) -> str:
    """
    Search for Conditions (problems / diagnoses).

      - patient        : patient id (or Patient/{id}) to filter by subject
      - clinical_status: "active", "recurrence", "resolved", etc.
      - count          : max results (default 10, max 50)

    Returns one summary line per condition with its clinical status and onset.
    """
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if clinical_status is not None:
        params["clinical-status"] = clinical_status

    bundle = await fhir_client.search_resources("Condition", params)
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
) -> str:
    """
    Search for MedicationRequests (prescriptions / orders).

      - patient : patient id (or Patient/{id}) to filter by subject
      - status  : "active", "completed", "stopped", "on-hold", etc.
      - count   : max results (default 10, max 50)

    Returns one summary line per medication order with status and dosage.
    """
    params: dict[str, str] = {"_count": _capped_count(count)}
    if patient is not None:
        params["patient"] = patient
    if status is not None:
        params["status"] = status

    bundle = await fhir_client.search_resources("MedicationRequest", params)
    return formatters.format_bundle(bundle)


@mcp.tool()
@fhir_tool
async def check_medication_interactions(medications: list[str]) -> str:
    """
    Check a list of medications for known pairwise drug interactions.

    Accepts generic or brand names (e.g. "warfarin", "Coumadin", "aspirin").
    Uses a small LOCAL reference set — NOT a substitute for clinical decision
    support. Returns each interaction found with a severity and explanation,
    most severe first, or a clear message when none are found.
    """
    if len(medications) < 2:
        return "Provide at least two medications to check for interactions."

    findings = interactions.check_medications(medications)
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
# Pagination
# ---------------------------------------------------------------------------


@mcp.tool()
@fhir_tool
async def get_next_page(next_url: str) -> str:
    """
    Fetch the next page of a FHIR search result.

    Pass the 'Next page' URL from any search result here. The URL must point
    to the same FHIR server (FHIR_BASE_URL) — other hosts are refused.
    Returns the same readable summary format as the original search.
    """
    bundle = await fhir_client.fetch_next_page(next_url)
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
async def get_patient_summary(patient_id: str) -> str:
    """
    Build a one-shot clinical snapshot for a patient.

    Fetches, concurrently: the Patient, their active Conditions, recent
    vital-sign Observations, and active MedicationRequests. Then checks the
    active medications for known drug interactions. Returns a single readable
    summary. Individual sections degrade gracefully if a sub-query fails.
    """
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
        return f"Could not retrieve Patient {patient_id}: {patient}"

    lines = ["=== Patient Summary ===", formatters.format_patient(patient), ""]

    condition_resources = _resources(conditions)
    lines.append(
        _section(
            "Active conditions",
            [formatters.format_condition(c) for c in condition_resources],
        )
    )
    lines.append("")

    vital_resources = _resources(vitals)
    lines.append(
        _section(
            "Recent vital signs",
            [formatters.format_observation(o) for o in vital_resources],
        )
    )
    lines.append("")

    med_resources = _resources(meds)
    lines.append(
        _section(
            "Active medications",
            [formatters.format_medication_request(m) for m in med_resources],
        )
    )

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
