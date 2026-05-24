# fhir-mcp-server

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant query
**FHIR R4** healthcare data. Point Claude (or any MCP client) at a FHIR server
and ask natural-language questions about patients and observations.

---

## What is FHIR?

**FHIR** (Fast Healthcare Interoperability Resources, pronounced "fire") is the
HL7 standard for exchanging healthcare data. Its core ideas:

| Concept | What it means |
|---|---|
| **Resource** | A typed, self-describing unit of clinical data — `Patient`, `Observation`, `Condition`, `MedicationRequest`, etc. |
| **RESTful API** | Every resource lives at `/{ResourceType}/{id}`. Read with `GET`, search with query params. |
| **Bundle** | A container returned by search operations, with a list of matching `entry` objects. |
| **LOINC / SNOMED** | Standard coding systems used in `code` elements to name observations (e.g. LOINC `8867-4` = heart rate). |

This server targets **FHIR R4** (version 4.0.1), the most widely deployed
version in the US and required for ONC / USCDI compliance.

## What is MCP?

**MCP** (Model Context Protocol) is an open protocol that lets AI assistants
call tools backed by live data. The assistant describes what it wants, the MCP
server fetches it, and the result flows back into the conversation.

```
Claude  ──tool call──▶  fhir-mcp-server  ──HTTP──▶  FHIR R4 server
        ◀──result──────                  ◀──JSON────
```

## Architecture

```
src/fhir_mcp_server/
├── fhir_client.py   ← all async HTTP I/O (httpx)
└── server.py        ← MCP tool definitions (FastMCP)
```

The two-layer split keeps a clean boundary: `fhir_client` knows about HTTP and
FHIR URLs; `server` knows about MCP and tool schemas. Tests can mock at the HTTP
layer without touching MCP internals.

## Tools

| Tool | FHIR interaction | Key parameters |
|---|---|---|
| `read_patient` | `GET /Patient/{id}` | `patient_id` |
| `search_patients` | `GET /Patient?...` | `name`, `family`, `given`, `birthdate`, `identifier` |
| `read_observation` | `GET /Observation/{id}` | `observation_id` |
| `search_observations` | `GET /Observation?...` | `patient`, `code`, `category`, `date` |

All search tools accept an optional `count` parameter (max 50) and return a
FHIR `Bundle` of type `searchset`.

## Quickstart

**Prerequisites:** Python 3.11+

```bash
# Install the package and dev dependencies
pip install -e ".[dev]"

# Run tests (no network required — all HTTP is mocked)
pytest

# Start the MCP server (stdio transport, default for Claude Desktop)
fhir-mcp-server
```

The server connects to the public HAPI FHIR R4 test instance by default.
Override with an environment variable:

```bash
FHIR_BASE_URL=https://your-fhir-server.example.com/fhir fhir-mcp-server
```

## Claude Desktop integration

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "fhir": {
      "command": "fhir-mcp-server"
    }
  }
}
```

Then ask Claude things like:
- *"Find patients named Smith born after 1980"*
- *"Get all vital-sign observations for patient 592"*
- *"What is the heart rate in observation obs-hr-1?"*

## Example conversation

```
You:    Find a patient named James Chalmers and show me their recent vitals.

Claude: [calls search_patients(name="James Chalmers")]
        Found Patient/592 — James T. Chalmers, born 1965-03-22.

        [calls search_observations(patient="592", category="vital-signs", count=5)]
        Recent vitals:
          • Heart rate: 78 bpm (2024-11-01)
          • Blood pressure: 122/78 mmHg (2024-11-01)
          • SpO₂: 98% (2024-10-28)
```

## Development

```bash
# Run the full test suite
pytest -v

# Type-check
pyright src/

# Lint
ruff check src/ tests/
```

## License

MIT
