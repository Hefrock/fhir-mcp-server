"""
Typed output models for structured JSON tool responses.

Every MCP tool accepts a ``format`` parameter. When set to ``"json"`` the tool
returns a JSON document whose shape is defined here. These models are the
CONTRACT this server exposes to downstream consumers (L2 terminology agents,
L3 patient-state synthesizers, etc.). Keep them narrow: the goal is a clean,
composable representation of what the tool computed, NOT a full FHIR resource
projection. Consumers that need the raw FHIR JSON can call the source server
directly.

Pydantic v2 is used for two reasons:

1. Runtime validation catches construction bugs immediately.
2. ``.model_json_schema()`` exports a machine-readable contract that downstream
   agents can validate against without importing this package.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    """
    Common config:
      - populate_by_name=True lets construction accept EITHER the snake_case
        field name OR its camelCase alias, so we can build models with Python
        keyword args and still emit camelCase JSON via ``by_alias=True``.
      - extra="ignore" so a caller can safely add ad-hoc fields.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ---------------------------------------------------------------------------
# Resource summaries
# ---------------------------------------------------------------------------


class IdentifierJson(_Base):
    type: str
    value: str


class PatientJson(_Base):
    id: str
    resource_type: str = Field(default="Patient", alias="resourceType")
    name: str
    gender: Optional[str] = None
    birth_date: Optional[str] = Field(default=None, alias="birthDate")
    age_years: Optional[int] = Field(default=None, alias="ageYears")
    identifiers: list[IdentifierJson] = Field(default_factory=list)


class ObservationValueJson(_Base):
    """
    Value carried by an Observation.

    Only one of ``quantity``, ``coded``, ``string``, or ``components`` will be
    populated for a given observation, matching FHIR's ``value[x]`` choice type.
    ``components`` covers multi-value observations like blood pressure.
    """

    quantity: Optional[float] = None
    unit: Optional[str] = None
    coded: Optional[str] = None
    string: Optional[str] = None
    components: list["ObservationComponentJson"] = Field(default_factory=list)


class ObservationComponentJson(_Base):
    label: str
    quantity: Optional[float] = None
    unit: Optional[str] = None


class ObservationJson(_Base):
    id: str
    resource_type: str = Field(default="Observation", alias="resourceType")
    code_display: str = Field(alias="codeDisplay")
    status: Optional[str] = None
    effective_date: Optional[str] = Field(default=None, alias="effectiveDate")
    value: ObservationValueJson
    interpretation: Optional[str] = None


class ConditionJson(_Base):
    id: str
    resource_type: str = Field(default="Condition", alias="resourceType")
    code_display: str = Field(alias="codeDisplay")
    clinical_status: Optional[str] = Field(default=None, alias="clinicalStatus")
    verification_status: Optional[str] = Field(default=None, alias="verificationStatus")
    onset: Optional[str] = None


class MedicationRequestJson(_Base):
    id: str
    resource_type: str = Field(default="MedicationRequest", alias="resourceType")
    drug: str
    status: Optional[str] = None
    authored_on: Optional[str] = Field(default=None, alias="authoredOn")
    dosage_text: Optional[str] = Field(default=None, alias="dosageText")


# ---------------------------------------------------------------------------
# Bundle envelope for search results
# ---------------------------------------------------------------------------


class BundleJson(_Base):
    """A search-set envelope: what came back, from where, and how to keep going."""

    total: int = 0
    returned: int
    resources: list[dict[str, Any]] = Field(default_factory=list)
    next_page: Optional[str] = Field(default=None, alias="nextPage")


# ---------------------------------------------------------------------------
# Non-resource outputs
# ---------------------------------------------------------------------------


class CapabilityJson(_Base):
    """Preflight summary from GET /metadata."""

    base_url: str = Field(alias="baseUrl")
    fhir_version: str = Field(alias="fhirVersion")
    is_r4: bool = Field(alias="isR4")
    server_name: Optional[str] = Field(default=None, alias="serverName")
    server_version: Optional[str] = Field(default=None, alias="serverVersion")
    implementation: Optional[str] = None
    security_services: list[str] = Field(default_factory=list, alias="securityServices")
    resources: list[str] = Field(default_factory=list)


class InteractionFindingJson(_Base):
    severity: str
    drug_a: str = Field(alias="drugA")
    drug_b: str = Field(alias="drugB")
    description: str


class InteractionCheckJson(_Base):
    medications: list[str]
    findings: list[InteractionFindingJson] = Field(default_factory=list)


class PatientSummaryJson(_Base):
    """The composed clinical snapshot returned by get_patient_summary."""

    patient: PatientJson
    active_conditions: list[ConditionJson] = Field(alias="activeConditions")
    recent_vitals: list[ObservationJson] = Field(alias="recentVitals")
    active_medications: list[MedicationRequestJson] = Field(alias="activeMedications")
    interaction_warnings: list[InteractionFindingJson] = Field(
        default_factory=list, alias="interactionWarnings"
    )


# Forward-ref: ObservationValueJson.components -> ObservationComponentJson.
ObservationValueJson.model_rebuild()
