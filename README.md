# fhir-mcp-server

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant query
**FHIR R4** healthcare data. Point Claude (or any MCP client) at a FHIR server
and ask natural-language questions about patients, observations, conditions, and
medications — and check medication lists for known interactions.

> **Not for clinical use.** This is an educational/portfolio project that talks
> to public test sandboxes seeded with synthetic patients.

---

## What is FHIR?

**FHIR** (Fast Healthcare Interoperability Resources, pronounced "fire") is the
HL7 standard for exchanging healthcare data. Its core ideas:

| Concept | What it means |
|---|---|
| **Resource** | A typed unit of clinical data — `Patient`, `Observation`, `Condition`, `MedicationRequest`, etc. |
| **RESTful API** | Every resource lives at `/{ResourceType}/{id}`. Read with `GET`, search with query params. |
| **Bundle** | A container returned by search operations, with a list of matching `entry` objects. |
| **LOINC / SNOMED** | Standard coding systems used in `code` elements (e.g. LOINC `8867-4` = heart rate). |

This server targets **FHIR R4** (version 4.0.1), the most widely deployed
version in the US.

## What is MCP?

**MCP** (Model Context Protocol) is an open protocol that lets AI assistants
call tools backed by live data.

```
Claude  ──tool call──▶  fhir-mcp-server  ──HTTP──▶  FHIR R4 server
        ◀──summary─────                  ◀──JSON────
```

This server returns **readable clinical summaries** rather than raw JSON, so the
model spends its context on signal. See [ARCHITECTURE.md](ARCHITECTURE.md) for
the design and [EXAMPLES.md](EXAMPLES.md) for full conversation transcripts.

## Architecture (at a glance)

```
src/fhir_mcp_server/
├── fhir_client.py    ← async HTTP I/O (httpx), pooled connection
├── formatters.py     ← FHIR resource -> readable clinical summary
├── loinc_codes.py    ← friendly names <-> LOINC codes
├── interactions.py   ← local drug-interaction lookup
└── server.py         ← MCP tool definitions (FastMCP)
```

Each layer has one job and a clean boundary, so tests mock at the HTTP layer and
the pure modules (formatters, loinc, interactions) test with no I/O at all.

## Tools

| Tool | FHIR interaction | Key parameters |
|---|---|---|
| `read_patient` | `GET /Patient/{id}` | `patient_id` |
| `search_patients` | `GET /Patient?...` | `name`, `family`, `given`, `birthdate`, `identifier` |
| `read_observation` | `GET /Observation/{id}` | `observation_id` |
| `search_observations` | `GET /Observation?...` | `patient`, `code`*, `category`, `date` |
| `search_conditions` | `GET /Condition?...` | `patient`, `clinical_status` |
| `search_medications` | `GET /MedicationRequest?...` | `patient`, `status` |
| `check_medication_interactions` | *(local, no network)* | `medications: list[str]` |

\* `code` accepts a raw LOINC code (`8867-4`) **or** a friendly name
(`heart_rate`, `glucose`, `hemoglobin_a1c`), resolved via `loinc_codes.py`.

All search tools accept an optional `count` (1–50, default 10).

## Quickstart

**Prerequisites:** Python 3.11+

```bash
pip install -e ".[dev]"   # install package + dev deps
make check                # lint + run tests (no network needed)
fhir-mcp-server           # start the server (stdio transport)
```

The server connects to the **SMART R4 sandbox** (`https://r4.smarthealthit.org`)
by default. Override for any R4 server:

```bash
FHIR_BASE_URL=https://your-fhir-server.example.com/fhir fhir-mcp-server
```

### NixOS / Nix users

A flake provides a reproducible dev shell: a Nix-pinned Python plus a project
venv for the pip deps, and **`ruff` from Nix** (the pip wheel is a dynamically
linked binary that won't run on NixOS):

```bash
nix develop      # Python + venv (.[dev]) + nix-provided ruff, all ready
make check       # lint + tests
```

Do **not** `pip install .[lint]` on NixOS — that pulls the broken ruff wheel.
Let the flake provide ruff instead.

## Claude Desktop integration

Copy [`claude_desktop_config.json`](claude_desktop_config.json) into your Claude
Desktop config (merge the `mcpServers` block):

```json
{
  "mcpServers": {
    "fhir-r4": {
      "command": "fhir-mcp-server",
      "env": { "FHIR_BASE_URL": "https://r4.smarthealthit.org" }
    }
  }
}
```

Then ask Claude things like:
- *"Find patients named Smith and summarize the first one."*
- *"Show recent vital-sign observations for patient <id>."*
- *"List this patient's active conditions and current medications."*
- *"Do warfarin and aspirin interact?"*

## Development

```bash
make install   # editable install with test deps (.[dev])
make test      # pytest
make lint      # ruff check .   (needs ruff on PATH — see below)
make format    # ruff check --fix .
make check     # lint + test (what CI enforces)
```

`ruff` is intentionally **not** in the `dev` extra (its pip wheel won't run on
NixOS). Get it from whichever fits your machine:

- **NixOS:** `nix develop` provides it. Nothing else to do.
- **Other platforms / CI:** `pip install -e ".[dev,lint]"` pulls ruff via pip.

CI (GitHub Actions) runs `ruff check .` and `pytest` on Python 3.11 and 3.12 —
the same `make check` gate, so local green means CI green.

## License

[MIT](LICENSE)
