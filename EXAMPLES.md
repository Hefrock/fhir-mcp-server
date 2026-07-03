# Examples

Real interaction patterns with `fhir-mcp-server` connected to the SMART R4
sandbox (`https://r4.smarthealthit.org`). The sandbox is seeded with synthetic
patients, so exact ids and values vary between runs — the *shape* of the
exchange is what matters.

> The tool results below are the actual text the tools return (see
> `formatters.py`). Each summary leads with the resource id so the assistant can
> chain a follow-up `read_*` call.

## Demo

![Demo of fhir-mcp-server in Claude Desktop](assets/demo.gif)

> _Placeholder._ Record a short screen capture of a conversation in Claude
> Desktop and save it as `assets/demo.gif`. A 15–30s clip showing one
> patient-lookup → vitals → interaction-check flow makes the best portfolio
> asset.

---

## 0. Preflight — confirm the server before running queries

Call `check_connection` first when pointing at a new FHIR endpoint. It hits
`GET /metadata`, reports what the server supports, and immediately flags a
non-R4 endpoint before you send it a real query.

```
You:    Confirm the FHIR server is reachable.

Claude: [calls check_connection()]

        FHIR endpoint at https://r4.smarthealthit.org
          Server: HAPI FHIR Server v5.4.0
          Implementation: SMART R4 Sandbox
          FHIR version: 4.0.1
          Security: SMART-on-FHIR
          Supported resources (145): Patient, Observation, Condition,
          MedicationRequest, AllergyIntolerance, Immunization, ...

        The sandbox is up, speaks R4, and supports the resource types we
        query. Ready.
```

For an authenticated endpoint, set `FHIR_ACCESS_TOKEN` before launching the
server:

```bash
FHIR_BASE_URL=https://api.example.com/fhir \
FHIR_ACCESS_TOKEN=eyJhbGciOi... \
fhir-mcp-server
```

Every outgoing request then carries `Authorization: Bearer <token>`.

## 1. Find a patient, then summarize them

```
You:    Find patients with the family name Smith.

Claude: [calls search_patients(family="Smith")]

        Found 3 result(s) (total reported: 3):
          - [Patient 1a2b] John Smith, male, 41y (DOB 1984-06-15) | MRN=10293
          - [Patient 9f0c] Maria Smith, female, 29y (DOB 1996-02-02)
          - [Patient 7d3e] Alan Smith, male, 67y (DOB 1958-09-30) | MRN=55821

        I found three patients named Smith. Want details on a specific one?

You:    Tell me about the first.

Claude: [calls read_patient(patient_id="1a2b")]

        [Patient 1a2b] John Smith, male, 41y (DOB 1984-06-15) | MRN=10293

        John Smith is a 41-year-old male (MRN 10293). Want his vitals,
        conditions, or medications?
```

## 2. Look up vitals by friendly name

The `code` parameter accepts `heart_rate` and resolves it to LOINC `8867-4`
under the hood — no need to know the code.

```
You:    What are this patient's recent heart rate readings? Patient 1a2b.

Claude: [calls search_observations(patient="1a2b", code="heart_rate", count=5)]

        Found 3 result(s) (total reported: 3):
          - [Observation o-441] Heart rate: 72 beats/minute (final, 2024-11-01)
          - [Observation o-410] Heart rate: 75 beats/minute (final, 2024-08-12)
          - [Observation o-388] Heart rate: 80 beats/minute (final, 2024-05-03)

        His heart rate has been stable in the low-to-mid 70s over the past
        six months — all within normal range.
```

## 3. Problems and medications together

```
You:    Summarize patient 1a2b's active problems and current medications.

Claude: [calls search_conditions(patient="1a2b", clinical_status="active")]

        Found 2 result(s) (total reported: 2):
          - [Condition c-htn] Essential hypertension — clinical: active,
            verification: confirmed, onset: 2019-05-20
          - [Condition c-af] Atrial fibrillation — clinical: active,
            verification: confirmed, onset: 2022-01-11

        [calls search_medications(patient="1a2b", status="active")]

        Found 2 result(s) (total reported: 2):
          - [MedicationRequest m-war] Warfarin 5 mg oral tablet (active,
            ordered 2023-11-02) — Take 5 mg once daily
          - [MedicationRequest m-asa] Aspirin 81 mg oral tablet (active,
            ordered 2023-11-02) — Take 81 mg once daily

        Active problems: hypertension and atrial fibrillation. Current meds:
        warfarin 5 mg daily and aspirin 81 mg daily. Note those two together
        carry a bleeding-risk interaction — want me to check?
```

## 4. Medication interaction check (local, no network)

```
You:    Yes, check warfarin and aspirin for interactions.

Claude: [calls check_medication_interactions(medications=["warfarin", "aspirin"])]

        Found 1 potential interaction(s):
          - [MAJOR] warfarin + aspirin: Additive bleeding risk; concurrent use
            raises hemorrhage risk.
        (Local reference set only — not for clinical use.)

        These two have a MAJOR interaction: combined use raises bleeding risk.
        This is flagged from a local reference set, not clinical decision
        support — confirm with a pharmacist or the prescribing clinician.
```

Brand names work too — `check_medication_interactions(["Coumadin", "ASA"])`
normalizes to the same generics and reports the same interaction.

## 5. No-match and no-interaction cases

```
You:    Any interactions between acetaminophen and loratadine?

Claude: [calls check_medication_interactions(["acetaminophen", "loratadine"])]

        No known interactions found among: acetaminophen, loratadine.
        (Local reference set only — not for clinical use.)
```

Searches that match nothing return a clear message rather than an empty result,
so the assistant can say "no records found" instead of guessing.

## 6. One-shot patient summary

`get_patient_summary` is the flagship tool: a single call fetches demographics,
active conditions, recent vitals, and active medications **concurrently**, then
flags interactions among the real medication list.

```
You:    Give me a full summary of patient 1a2b.

Claude: [calls get_patient_summary(patient_id="1a2b")]

        === Patient Summary ===
        [Patient 1a2b] John Smith, male, 41y (DOB 1984-06-15) | MRN=10293

        Active conditions (2):
          - [Condition c-htn] Essential hypertension — clinical: active,
            verification: confirmed, onset: 2019-05-20
          - [Condition c-af] Atrial fibrillation — clinical: active,
            verification: confirmed, onset: 2022-01-11

        Recent vital signs (1):
          - [Observation o-441] Heart rate: 72 beats/minute (final, 2024-11-01)

        Active medications (2):
          - [MedicationRequest m-war] Warfarin 5 mg oral tablet (active,
            ordered 2023-11-02)
          - [MedicationRequest m-asa] Aspirin 81 mg oral tablet (active,
            ordered 2023-11-02)

        Medication interaction warnings (1):
          - [MAJOR] warfarin + aspirin: Additive bleeding risk; concurrent use
            raises hemorrhage risk.
        (Local reference set only — not for clinical use.)

        This 41-year-old patient has hypertension and atrial fibrillation, both
        active. Vitals look normal. Note the MAJOR interaction between his
        warfarin and aspirin — worth confirming with the prescriber.
```

If any single section can't be retrieved, it shows "none found" and the rest of
the summary still renders — one failed sub-query never blanks the whole report.

## 7. Structured JSON output for downstream agents

Every tool accepts `format="json"` to return a machine-parseable document
instead of a human summary. This is the interface higher layers (patient-state
synthesis, clinical reasoning) consume.

```
You:    (via an L3 patient-state agent, not a human)

Agent:  [calls search_medications(patient="1a2b", status="active", format="json")]

        {
          "total": 2,
          "returned": 2,
          "resources": [
            {
              "id": "m-war",
              "resourceType": "MedicationRequest",
              "drug": "Warfarin 5 mg oral tablet",
              "status": "active",
              "authoredOn": "2023-11-02",
              "dosageText": "Take 5 mg once daily"
            },
            {
              "id": "m-asa",
              "resourceType": "MedicationRequest",
              "drug": "Aspirin 81 mg oral tablet",
              "status": "active",
              "authoredOn": "2023-11-02",
              "dosageText": "Take 81 mg once daily"
            }
          ],
          "nextPage": null
        }

        # The agent iterates, filters by status, joins with interaction data.
        # No regex-parsing prose. No FHIR-JSON traversal.
```

The exact shapes are defined by Pydantic models in
`src/fhir_mcp_server/models.py` and can be exported as JSON Schema
(`PatientJson.model_json_schema()`, etc.) for contract validation on the
consumer side.

`get_patient_summary(patient_id, format="json")` returns the composed shape:

```json
{
  "patient": { "id": "1a2b", "name": "John Smith", ... },
  "activeConditions": [ { "id": "c-htn", "codeDisplay": "Hypertension", ... } ],
  "recentVitals": [ { "id": "o-441", "value": { "quantity": 72, "unit": "beats/minute" }, ... } ],
  "activeMedications": [ ... ],
  "interactionWarnings": [
    { "severity": "MAJOR", "drugA": "warfarin", "drugB": "aspirin",
      "description": "Additive bleeding risk; ..." }
  ]
}
```

Same information as the text summary — different consumer, different shape.
