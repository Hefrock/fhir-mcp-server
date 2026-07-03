# Architecture

This document explains how `fhir-mcp-server` is put together and *why* the
pieces are split the way they are. If you're reading the code to learn, start
here, then read the modules in the order listed below.

## The big picture

```
┌─────────┐   tool call    ┌───────────────────────────────────┐   HTTPS   ┌────────────┐
│  Claude │ ─────────────▶ │            fhir-mcp-server        │ ────────▶ │  FHIR R4   │
│ (client)│ ◀───────────── │                                   │ ◀──────── │  server    │
└─────────┘  text or JSON  │  server.py                        │  FHIR JSON└────────────┘
                           │    ├─ formatters.py  (JSON→text)  │
                           │    ├─ models.py      (JSON shape) │
                           │    ├─ loinc_codes.py (names→codes)│
                           │    ├─ interactions.py (local DB)  │
                           │    └─ fhir_client.py (HTTP I/O)   │
                           └───────────────────────────────────┘
```

The client can request one of two output shapes:

- **`format="text"`** (default) — compact, readable summaries that fit an LLM's
  context budget. Best for a human-in-the-loop conversation.
- **`format="json"`** — structured documents shaped by Pydantic models in
  `models.py`. Best for programmatic consumers (L2/L3 agents, pipelines).

In neither mode does the client see raw FHIR JSON: this server *is* the layer
that turns FHIR into something usable.

## Where this repo sits in the larger plan

The long-term architecture is layered, with each layer swappable and testable
in isolation:

```
L4  Clinical reasoning (LLM orchestrator, care recommendations)
L3  Patient state synthesis (problem list, care gaps, timeline)
L2  Semantic enrichment (terminology, guidelines, reference ranges)
L1  FHIR data access   ← this repo
L0  FHIR server        (SMART sandbox, Synthea Lab, real EHR)
```

`fhir-mcp-server` is deliberately **L1 only**. It exposes FHIR as clean tools;
it does not interpret findings, synthesize problem lists, or make clinical
recommendations. Those responsibilities live in higher layers so each layer can
be updated on its own cadence and audited independently — a design principle
that becomes non-negotiable once anything touches clinical decision-making.

The MECE test for anything added here: *"Does this feature help **access**
FHIR data, or **interpret** it?"* Access stays; interpretation goes elsewhere.

## Module responsibilities

Read the code in this order — each layer depends only on the ones below it.

| Module | Responsibility | Depends on |
|---|---|---|
| `loinc_codes.py` | Map friendly names (`heart_rate`) to LOINC codes. Pure data. | — |
| `interactions.py` | Local pairwise drug-interaction lookup. Pure logic. | — |
| `models.py` | Pydantic models defining the structured JSON output contract. | `pydantic` |
| `formatters.py` | Turn a FHIR resource/Bundle into a summary — text OR structured JSON. | `models` |
| `fhir_client.py` | All network I/O. Build URLs, GET, parse JSON, raise on error. | `httpx` |
| `server.py` | Define MCP tools; shape inputs, call the client, format outputs. | all of the above |

The arrows only point downward. `fhir_client` knows nothing about MCP;
`formatters` knows nothing about HTTP. That one-directional dependency graph is
what makes each piece independently testable.

## Key design decisions

### 1. Dual-mode output: text for humans, JSON for programs

Every tool accepts `format="text"` (default) or `format="json"`. Both modes
carry the same information; they differ in shape.

- **Text mode** returns a compact summary string. A single FHIR `Patient` can
  be hundreds of lines of JSON; the summary is one line. LLMs read this
  directly and spend their context on reasoning, not JSON traversal.
- **JSON mode** returns a JSON document whose shape is validated by Pydantic
  models in `models.py`. Downstream agents (L2/L3) consume this in code —
  filter, join, aggregate — without having to re-parse prose.

**Crucial detail:** every summary and every JSON document includes the
resource **id**. Search returns summaries, and the model (or agent) needs the
id to issue a follow-up `read_*`. Drop the id and you break tool chaining.

### 2. A pooled HTTP client with optional bearer auth

`fhir_client` keeps one module-level `httpx.AsyncClient` and reuses it across
calls (created lazily on first use). A fresh client per request would open a
new TCP+TLS connection every time — wasteful for a long-running server. Lazy
creation means importing the module never touches the network or an event loop,
which keeps imports cheap and tests fast. `aclose()` exists for clean shutdown.

For authenticated endpoints (Epic, Cerner, Meditech sandboxes, production
servers), setting the `FHIR_ACCESS_TOKEN` env var attaches an
`Authorization: Bearer <token>` header to every outgoing request. Full
SMART-on-FHIR OAuth is deliberately out of scope for this transport layer —
obtain the token externally and pass it in.

### 3. Preflight with `check_connection`

The `check_connection` tool hits `GET /metadata`, parses the server's
`CapabilityStatement`, and returns a summary of what the endpoint supports:
FHIR version, software identification, security services, and available
resource types. A non-R4 `fhirVersion` is flagged so a user pointed at an
STU3 or R5 endpoint learns immediately instead of hitting cryptic 404s on the
first clinical query. Call this first when pointing at a new server.

### 4. Order-independent interaction keys

Interactions are symmetric: warfarin+aspirin == aspirin+warfarin. We key the
lookup table on `frozenset({a, b})`, which is hashable and ignores order, so we
store each interaction once and match it regardless of argument order. A
synonym table normalizes brand names ("Coumadin" → "warfarin") before lookup.

### 5. Defensive parsing

Every FHIR element is optional and may repeat. Formatters never index blindly
(`patient["name"][0]["family"]` crashes on real data); they navigate with
`.get()` and fall back to readable placeholders. A FHIR result value lives in
one of many `value[x]` shapes (`valueQuantity`, `valueCodeableConcept`,
`component`, …), so `format_observation` checks each in turn.

### 6. Friendly code resolution at the boundary

`search_observations` accepts `code="heart_rate"` and resolves it to `8867-4`
via `loinc_codes.resolve()` *before* querying. Unknown values pass through
unchanged, so raw codes still work. Input normalization happens once, at the
edge.

### 7. Concurrent composite tools

`get_patient_summary` issues four FHIR calls (patient, conditions, vitals,
medications) with `asyncio.gather(..., return_exceptions=True)`. Two payoffs:

- **Latency:** the calls run in parallel, so total time is the slowest single
  request, not the sum of all four.
- **Resilience:** `return_exceptions=True` turns a failed sub-query into a
  *value* we inspect, rather than an exception that aborts the summary. The
  patient read is treated as mandatory; the other three degrade to
  "none found" if they fail.

The tool also demonstrates module composition: it extracts drug names from the
fetched medications (`interactions.extract_known_drugs`) and runs them back
through the interaction checker — `interactions` never knows about FHIR, yet
the summary connects the two.

## Data flow: a search request

1. Claude calls `search_observations(patient="x", code="heart_rate", format="text")`.
2. `server.py` validates `format`, caps `count`, resolves `heart_rate` →
   `8867-4`, and builds the FHIR query-param dict.
3. `fhir_client.search_resources("Observation", params)` issues the GET and
   returns the parsed Bundle (or raises `HTTPStatusError`).
4. `formatters.format_bundle(bundle)` renders one summary line per entry
   (text mode) *or* `formatters.bundle_to_json(bundle)` builds a validated
   envelope of typed records (JSON mode).
5. The result flows back to Claude as the tool response.

## Testing strategy

- **Pure modules** (`loinc_codes`, `interactions`, `formatters`, `models`)
  test with plain function calls — no mocks, no I/O. Fast and exhaustive.
- **HTTP layer** (`fhir_client`) and **tools** (`server`) test with
  [`respx`](https://lundberg.github.io/respx/), which intercepts httpx requests
  at the transport layer. Real client code runs unmodified; no network is hit.
- **JSON output contracts** have their own test file (`test_json_output.py`)
  that asserts on the *shape* of each tool's structured response — the actual
  contract downstream consumers rely on, not incidental prose.
- A shared, autouse fixture resets the pooled client and pins `FHIR_BASE_URL`
  and `FHIR_ACCESS_TOKEN` around every test, so module-level state never leaks
  between tests.

Run it all with `make check` (lint + tests) — the same gate CI enforces.
