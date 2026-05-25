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
