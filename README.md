# fhir-mcp-server

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant query
**FHIR R4** healthcare data. Point Claude (or any MCP client) at a FHIR server
and ask natural-language questions about patients, observations, conditions, and
medications — and check medication lists for known interactions.

> **Not for clinical use.** This is an educational/portfolio project that talks
> to public test sandboxes seeded with synthetic patients.

🚀![Demo](assets/demo.gif)

---

## 🔥 What is FHIR?

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

## 🔌 What is MCP?

**MCP** (Model Context Protocol) is an open protocol that lets AI assistants
call tools backed by live data.

```
┌────────────────────────────────────────────────────────────────────────┐
│ HOST APPLICATION (e.g., Claude Desktop / IDE)                          │
│                                                                        │
│  ┌───────────┐          Invokes Tool           ┌────────────┐          │
│  │    LLM    │ ──────────────────────────────> │    MCP     │          │
│  │  (Model)  │ <────────────────────────────── │   Client   │          │
│  └───────────┘        Returns Clean Text       └────────────┘          │
└──────────────────────────────────────────────────────│─────────────────┘
                                                       │
                                            JSON-RPC over Stdio/SSE
                                            (e.g., fhir_search_patient)
                                                       │
                                                       ▼
                                         ┌───────────────────────────┐
                                         │      fhir-mcp-server      │
                                         │       (MCP Server)        │
                                         └───────────────────────────┘
                                                       │
                                            HTTPS REST API Call
                                            (Authorization + JSON)
                                                       │
                                                       ▼
                                         ┌───────────────────────────┐
                                         │      FHIR R4 Server       │
                                         │  (HAPI FHIR, Epic, etc.)  │
                                         └───────────────────────────┘
```

This server returns **readable clinical summaries** rather than raw JSON, so the
model spends its context on signal. See [ARCHITECTURE.md](ARCHITECTURE.md) for
the design and [EXAMPLES.md](EXAMPLES.md) for full conversation transcripts.

## 🏛️ Architecture (at a glance)

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

## 🛠️ Tools

| Tool | FHIR interaction | Key parameters |
|---|---|---|
| `check_connection` | `GET /metadata` | *(none)* |
| `read_patient` | `GET /Patient/{id}` | `patient_id` |
| `search_patients` | `GET /Patient?...` | `name`, `family`, `given`, `birthdate`, `identifier` |
| `read_observation` | `GET /Observation/{id}` | `observation_id` |
| `search_observations` | `GET /Observation?...` | `patient`, `code`*, `category`, `date` |
| `search_conditions` | `GET /Condition?...` | `patient`, `clinical_status` |
| `search_medications` | `GET /MedicationRequest?...` | `patient`, `status` |
| `read_encounter` | `GET /Encounter/{id}` | `encounter_id` |
| `search_encounters` | `GET /Encounter?...` | `patient`, `status`, `date` |
| `read_allergy_intolerance` | `GET /AllergyIntolerance/{id}` | `allergy_id` |
| `search_allergy_intolerances` | `GET /AllergyIntolerance?...` | `patient`, `clinical_status`, `category`, `criticality` |
| `read_diagnostic_report` | `GET /DiagnosticReport/{id}` | `report_id` |
| `search_diagnostic_reports` | `GET /DiagnosticReport?...` | `patient`, `category`, `code`*, `status`, `date` |
| `read_immunization` | `GET /Immunization/{id}` | `immunization_id` |
| `search_immunizations` | `GET /Immunization?...` | `patient`, `status`, `date` |
| `check_medication_interactions` | *(local, no network)* | `medications: list[str]` |
| `get_patient_summary` | *(4 calls, concurrent)* | `patient_id` |

\* `code` accepts a raw LOINC code (`8867-4`) **or** a friendly name
(`heart_rate`, `glucose`, `hemoglobin_a1c`), resolved via `loinc_codes.py`.

All search tools accept an optional `count` (1–50, default 10).

**Structured JSON output.** Every tool accepts an optional `format` parameter:
`"text"` (default, human-readable summary) or `"json"` (structured document
consumable by downstream agents). The JSON shapes are defined by Pydantic
models in `src/fhir_mcp_server/models.py` and their schemas can be exported
with `PatientJson.model_json_schema()` etc. for contract validation.

## ⏱️ Quickstart

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

For FHIR servers that require authentication (Epic, Cerner, Meditech sandboxes,
production endpoints), pass a bearer token via `FHIR_ACCESS_TOKEN`:

```bash
FHIR_BASE_URL=https://api.example.com/fhir \
FHIR_ACCESS_TOKEN=eyJhbGciOi... \
fhir-mcp-server
```

When set, every outgoing request carries an `Authorization: Bearer <token>`
header. Full SMART-on-FHIR OAuth flow is out of scope for this transport layer
— obtain the token externally and pass it in.

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

## 🚡 Connect it to an MCP client

The server speaks MCP over stdio, so any MCP client can launch it. Easiest
first.

### Claude Code (recommended — works on Linux/NixOS/macOS/Windows)

This repo ships a project-scoped [`.mcp.json`](.mcp.json). Clone the repo, set
up the environment, and run Claude Code **from the project directory with the
environment active** so `python` resolves to the one that has the package:

```bash
git clone https://github.com/Hefrock/fhir-mcp-server.git
cd fhir-mcp-server
nix develop                 # or: python -m venv .venv && source .venv/bin/activate && pip install -e .
claude                      # Claude Code auto-detects .mcp.json
```

`.mcp.json` launches the server with `python -m fhir_mcp_server`, which works
from any environment where the package is importable (no reliance on a console
script being on `PATH`).

### Claude Desktop (macOS / Windows — no official Linux build)

Merge the `mcpServers` block from
[`claude_desktop_config.json`](claude_desktop_config.json) into your Claude
Desktop config. Desktop launches servers with its own environment, so use an
**absolute path** to the project venv's Python:

```json
{
  "mcpServers": {
    "fhir-r4": {
      "command": "/ABSOLUTE/PATH/TO/fhir-mcp-server/.venv/bin/python",
      "args": ["-m", "fhir_mcp_server"],
      "env": { "FHIR_BASE_URL": "https://r4.smarthealthit.org" }
    }
  }
}
```

### Try it

Once connected, ask:
- *"Give me a full summary of patient \<id\>."* (uses `get_patient_summary`)
- *"Find patients named Smith and summarize the first one."*
- *"List this patient's active conditions and current medications."*
- *"Does this patient have any medications that interacte with each other?"*

## ✍️ Development

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

## 👏 Acknowledgments

This project draws inspiration from two efforts that focus on helping patients
better understand and engage with their own clinical data:

- **[Open Record](https://github.com/Fan-Pier-Labs/openrecord)** by Ryan Hughes / Fan Pier Labs
- **[OpenKP](https://github.com/hugooc/OpenKP)** by Hugo Campos

Both projects share a conviction that drives home that clinical data is more
useful — and more humane — when patients can understand i!

The code itself is independently written against the public FHIR R4 specification
and the SMART Health IT sandbox.

## ⚖️ License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal, educational, and
noncommercial use. See the [PolyForm Project](https://polyformproject.org/licenses/noncommercial/1.0.0/)
for the full terms.
