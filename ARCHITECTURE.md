# Architecture

This document explains how `fhir-mcp-server` is put together and *why* the
pieces are split the way they are. If you're reading the code to learn, start
here, then read the modules in the order listed below.

## The big picture

```
┌─────────┐   tool call    ┌───────────────────────────────────┐   HTTPS   ┌────────────┐
│  Claude │ ─────────────▶ │            fhir-mcp-server        │ ────────▶ │  FHIR R4   │
│ (client)│ ◀───────────── │                                   │ ◀──────── │  server    │
└─────────┘  text summary  │  server.py                        │  JSON     └────────────┘
                           │    ├─ formatters.py  (JSON→text)  │
                           │    ├─ loinc_codes.py (names→codes)│
                           │    ├─ interactions.py (local DB)  │
                           │    └─ fhir_client.py (HTTP I/O)   │
                           └───────────────────────────────────┘
```

The client never sees FHIR JSON. It sees compact, readable summaries. That is a
deliberate design choice (see "Readable summaries" below).

## Module responsibilities

Read the code in this order — each layer depends only on the ones below it.

| Module | Responsibility | Depends on |
|---|---|---|
| `loinc_codes.py` | Map friendly names (`heart_rate`) to LOINC codes. Pure data. | — |
| `interactions.py` | Local pairwise drug-interaction lookup. Pure logic. | — |
| `formatters.py` | Turn a FHIR resource/Bundle into a readable summary. Pure logic. | — |
| `fhir_client.py` | All network I/O. Build URLs, GET, parse JSON, raise on error. | `httpx` |
| `server.py` | Define MCP tools; shape inputs, call the client, format outputs. | all of the above |

The arrows only point downward. `fhir_client` knows nothing about MCP;
`formatters` knows nothing about HTTP. That one-directional dependency graph is
what makes each piece independently testable.

## Key design decisions

### 1. Readable summaries, not raw JSON

The tool layer returns text summaries (via `formatters.py`) instead of dumping
FHIR JSON. A single FHIR `Patient` can be hundreds of lines; handing that to an
LLM burns context and buries the signal. Summaries keep responses dense and
scannable.

**Crucial detail:** every summary includes the resource **id** (e.g.
`[Patient example] ...`). Search returns summaries, and the model needs the id
to issue a follow-up `read_*`. Drop the id and you break tool chaining.

### 2. A pooled HTTP client

`fhir_client` keeps one module-level `httpx.AsyncClient` and reuses it across
calls (created lazily on first use). A fresh client per request would open a new
TCP+TLS connection every time — wasteful for a long-running server. Lazy
creation means importing the module never touches the network or an event loop,
which keeps imports cheap and tests fast. `aclose()` exists for clean shutdown.

### 3. Order-independent interaction keys

Interactions are symmetric: warfarin+aspirin == aspirin+warfarin. We key the
lookup table on `frozenset({a, b})`, which is hashable and ignores order, so we
store each interaction once and match it regardless of argument order. A
synonym table normalizes brand names ("Coumadin" → "warfarin") before lookup.

### 4. Defensive parsing

Every FHIR element is optional and may repeat. Formatters never index blindly
(`patient["name"][0]["family"]` crashes on real data); they navigate with
`.get()` and fall back to readable placeholders. A FHIR result value lives in
one of many `value[x]` shapes (`valueQuantity`, `valueCodeableConcept`,
`component`, …), so `format_observation` checks each in turn.

### 5. Friendly code resolution at the boundary

`search_observations` accepts `code="heart_rate"` and resolves it to `8867-4`
via `loinc_codes.resolve()` *before* querying. Unknown values pass through
unchanged, so raw codes still work. Input normalization happens once, at the
edge.

## Data flow: a search request

1. Claude calls `search_observations(patient="x", code="heart_rate")`.
2. `server.py` caps `count`, resolves `heart_rate` → `8867-4`, and builds the
   FHIR query-param dict.
3. `fhir_client.search_resources("Observation", params)` issues the GET and
   returns the parsed Bundle (or raises `HTTPStatusError`).
4. `formatters.format_bundle(bundle)` renders one summary line per entry.
5. The text flows back to Claude as the tool result.

## Testing strategy

- **Pure modules** (`loinc_codes`, `interactions`, `formatters`) test with plain
  function calls — no mocks, no I/O. Fast and exhaustive.
- **HTTP layer** (`fhir_client`) and **tools** (`server`) test with
  [`respx`](https://lundberg.github.io/respx/), which intercepts httpx requests
  at the transport layer. Real client code runs unmodified; no network is hit.
- A shared, autouse fixture resets the pooled client and pins `FHIR_BASE_URL`
  around every test, so the module-level client never leaks state between tests.

Run it all with `make check` (lint + tests) — the same gate CI enforces.
