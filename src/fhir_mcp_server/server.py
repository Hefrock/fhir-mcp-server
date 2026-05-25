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

from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import fhir_client, formatters, interactions, loinc_codes

mcp = FastMCP(
    "FHIR R4",
    instructions=(
        "Query a FHIR R4 server for Patients, Observations, Conditions, and "
        "MedicationRequests. Use search tools to find resources by demographic "
        "or clinical criteria, then read tools to retrieve full details by id. "
        "The check_medication_interactions tool flags known drug interactions "
        "from a local reference set (not for clinical use)."
    ),
)


def _capped_count(count: int) -> str:
    """FHIR _count param, capped at 50 to keep responses bounded."""
    return str(max(1, min(count, 50)))


# ---------------------------------------------------------------------------
# Patient tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def read_patient(patient_id: str) -> str:
    """
    Fetch a single Patient by FHIR id and return a readable summary.

    The summary includes name, gender, age/DOB, and identifiers (e.g. MRN).
    """
    resource = await fhir_client.read_resource("Patient", patient_id)
    return formatters.format_patient(resource)


@mcp.tool()
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
async def read_observation(observation_id: str) -> str:
    """
    Fetch a single Observation by FHIR id and return a readable summary.

    Observations are measurements and assertions: vitals, labs, imaging
    findings. The summary shows what was measured, the value, status, and time.
    """
    resource = await fhir_client.read_resource("Observation", observation_id)
    return formatters.format_observation(resource)


@mcp.tool()
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
