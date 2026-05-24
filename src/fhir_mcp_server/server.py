"""
FHIR R4 MCP Server.

MCP (Model Context Protocol) lets an AI assistant call tools that reach
live data sources. Each @mcp.tool() function below becomes a callable
tool that Claude (or any MCP client) can invoke by name.

The four tools here map directly onto two FHIR REST interactions:
  - read   → GET /{ResourceType}/{id}
  - search → GET /{ResourceType}?param=value&...

Results are returned as pretty-printed JSON strings so the model can
reason over the raw FHIR structure without any lossy summarisation.
"""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import fhir_client

mcp = FastMCP(
    "FHIR R4",
    instructions=(
        "Query Patient and Observation resources from a FHIR R4 server. "
        "Use search tools to find resources by demographic or clinical criteria, "
        "then use read tools to retrieve full resource details by ID."
    ),
)


# ---------------------------------------------------------------------------
# Patient tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def read_patient(patient_id: str) -> str:
    """
    Fetch a single Patient resource by its FHIR ID.

    Returns the full Patient JSON including name, birthDate, gender,
    identifiers (MRN, SSN), address, and telecom.
    """
    resource = await fhir_client.read_resource("Patient", patient_id)
    return json.dumps(resource, indent=2)


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
    Search for Patient resources.

    Parameters map to standard FHIR search params:
      - name      : any part of the patient's name (family or given)
      - family    : family / last name
      - given     : given / first name
      - birthdate : ISO-8601 date (YYYY-MM-DD), supports prefixes like ge1990-01-01
      - identifier: system|value pair, e.g. "http://hospital.org/mrn|12345"
      - count     : max results to return (default 10, max 50)

    Returns a FHIR Bundle of type 'searchset'.
    """
    params: dict[str, str] = {"_count": str(min(count, 50))}
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
    return json.dumps(bundle, indent=2)


# ---------------------------------------------------------------------------
# Observation tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def read_observation(observation_id: str) -> str:
    """
    Fetch a single Observation resource by its FHIR ID.

    Observations represent measurements and simple assertions: vitals,
    lab results, imaging findings, and more. The 'code' element (usually
    LOINC) identifies what was measured; the 'value' element holds the result.
    """
    resource = await fhir_client.read_resource("Observation", observation_id)
    return json.dumps(resource, indent=2)


@mcp.tool()
async def search_observations(
    patient: Optional[str] = None,
    code: Optional[str] = None,
    category: Optional[str] = None,
    date: Optional[str] = None,
    count: int = 10,
) -> str:
    """
    Search for Observation resources.

    Parameters map to standard FHIR search params:
      - patient  : patient ID (or Patient/{id}) to filter by subject
      - code     : LOINC or SNOMED code, e.g. "8867-4" for heart rate
      - category : clinical category — "vital-signs", "laboratory", "imaging"
      - date     : ISO-8601 date or range, e.g. "ge2024-01-01"
      - count    : max results to return (default 10, max 50)

    Returns a FHIR Bundle of type 'searchset'.
    """
    params: dict[str, str] = {"_count": str(min(count, 50))}
    for key, value in {
        "patient": patient,
        "code": code,
        "category": category,
        "date": date,
    }.items():
        if value is not None:
            params[key] = value

    bundle = await fhir_client.search_resources("Observation", params)
    return json.dumps(bundle, indent=2)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
