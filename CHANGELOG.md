# Changelog

All notable changes to `fhir-mcp-server` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-07-04

The initial stable release. `fhir-mcp-server` is now **feature-complete for
Layer 1** of the modular clinical-AI architecture: a FastMCP server that
turns any FHIR R4 endpoint into clean, AI-callable tools with a dual
text/JSON output contract, ready to serve as a stable dependency for
downstream synthesis and reasoning agents.

### 18 MCP Tools

**Preflight and connection**
- `check_connection` — confirms the endpoint is reachable, speaks R4, and
  reports its capabilities

**Read + search across 8 FHIR resource types**
- `Patient` — `read_patient`, `search_patients`
- `Observation` — `read_observation`, `search_observations`
- `Condition` — `search_conditions`
- `MedicationRequest` — `search_medications`
- `Encounter` — `read_encounter`, `search_encounters`
- `AllergyIntolerance` — `read_allergy_intolerance`, `search_allergy_intolerances`
- `DiagnosticReport` — `read_diagnostic_report`, `search_diagnostic_reports`
- `Immunization` — `read_immunization`, `search_immunizations`

**Composite and utility**
- `get_patient_summary` — concurrent snapshot: demographics + active
  conditions + recent vitals + active medications + drug interaction check
- `check_medication_interactions` — local reference set, no network
- `get_next_page` — SSRF-safe pagination for any search bundle

### Highlights

- **Dual-mode output.** Every tool accepts `format="text"` (default,
  human/LLM-readable summary) or `format="json"` (structured document
  shaped by Pydantic models in `src/fhir_mcp_server/models.py`).
  Downstream agents get typed data; humans get clean prose.
- **Pointable at any R4 endpoint.** Configuration via three env vars:
  `FHIR_BASE_URL`, optional `FHIR_ACCESS_TOKEN` for bearer auth (Epic,
  Cerner, Meditech sandboxes and production endpoints), optional
  `FHIR_SERVER_LABEL` for backend identity.
- **Multi-backend by composition.** Register the server multiple times
  under different names in the MCP client config, each with its own
  endpoint and label — Claude sees them side-by-side and routes by name.
- **Friendly LOINC resolution.** `search_observations(code="heart_rate")`
  and `search_diagnostic_reports(code="hemoglobin_a1c")` transparently
  resolve to LOINC codes.
- **Robust error handling.** A single `@fhir_tool` decorator converts
  every httpx exception, HTTP status error, connection failure, and
  timeout into a friendly string the AI can reason about. No stack
  traces reach the model.
- **SSRF-safe pagination.** `get_next_page` validates that the URL
  starts with the configured `FHIR_BASE_URL` before fetching.
- **Defensive parsing throughout.** Every FHIR field access uses `.get()`
  with graceful fallbacks — real EHR data is inconsistent, and formatters
  never crash on missing fields.
- **Concurrent composite calls.** `get_patient_summary` fires four FHIR
  requests in parallel via `asyncio.gather(return_exceptions=True)`,
  degrading individual sections gracefully if a sub-query fails.

### Engineering

- **140+ unit tests**, ~4 seconds, zero network I/O (via `respx`
  transport-layer mocks)
- **10 smoke tests** in `tests_synthea/`, exercised nightly by a
  dedicated GitHub Actions workflow against a real HAPI FHIR server
  loaded with reproducible Synthea patients (via the sibling
  [`fhir-synthea-lab`](https://github.com/Hefrock/fhir-synthea-lab))
- **CI matrix**: Python 3.11 and 3.12, `ruff` lint + `pytest`
- **NixOS-native dev shell** via pinned `flake.lock`
- **Async throughout** with a pooled, lazily-initialised
  `httpx.AsyncClient`
- **PolyForm Noncommercial 1.0.0** license — free for personal,
  educational, and noncommercial use

### Documentation

- [`README.md`](README.md) — quickstart, tool table, multi-backend
  configuration guide
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module responsibilities,
  design decisions, testing strategy, position within the larger
  layered clinical-AI plan
- [`EXAMPLES.md`](EXAMPLES.md) — twelve annotated conversation
  transcripts covering the full tool surface
- [`assets/demo.gif`](assets/demo.gif) — live-session recording

### Acknowledgments

Inspired by [Open Record](https://github.com/Fan-Pier-Labs/openrecord)
(Ryan Hughes / Fan Pier Labs) and
[OpenKP](https://github.com/hugooc/OpenKP) (Hugo Campos) — two efforts
that focus on helping patients better understand and engage with their
own clinical data.

[1.0.0]: https://github.com/Hefrock/fhir-mcp-server/releases/tag/v1.0.0
