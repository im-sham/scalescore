"""Readiness boundary for canonical and one-release legacy ControlRef transport."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from scalescore.contracts.control_ref import (
    ControlRefEnvelope as GeneratedControlRefEnvelope,
)


class CanonicalControlRefEnvelope(GeneratedControlRefEnvelope):
    """Generated ControlRef with schema-exact optional-pin handling.

    The generated binding models optional pins as nullable Python fields. JSON Schema
    permits omission but not explicit null, so this consumer boundary closes that
    transport-only gap and preserves the producer's omission shape.

    Its nested ``workflow_ref`` is immutable historical ControlRef alignment
    metadata, not the standalone canonical WorkflowRef V0.1 envelope.
    """

    @model_validator(mode="after")
    def reject_explicit_null_pins(self) -> CanonicalControlRefEnvelope:
        ref = self.ref
        for field_name in ("snapshot_id", "version"):
            if field_name in ref.model_fields_set and getattr(ref, field_name) is None:
                raise ValueError(f"ref.{field_name} must be omitted rather than null")

        workflow_ref = ref.workflow_ref.ref
        for field_name in ("snapshot_id", "version"):
            if (
                field_name in workflow_ref.model_fields_set
                and getattr(workflow_ref, field_name) is None
            ):
                raise ValueError(
                    f"ref.workflow_ref.ref.{field_name} must be omitted rather than null"
                )
        return self

    @model_serializer
    def preserve_pin_omission(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "contract_name": self.contract_name,
            "producer_capability": self.producer_capability,
            "producer_system": self.producer_system,
            "canonical_owner": self.canonical_owner,
            "issued_at": self.issued_at,
            "cache_policy": self.cache_policy,
            "ref": self.ref.model_dump(exclude_unset=True),
        }


class LegacyControlRef(BaseModel):
    """Exact repository-local ControlRef accepted for one release only."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    ref_id: str
    ref_type: Literal["control"] = "control"
    source_capability: Literal["workflow_context"] = "workflow_context"
    organization_id: str
    environment_id: str = "production"
    external_uri: str | None = None
    snapshot_id: str | None = None
    version: str | None = None
    created_at: datetime | str
    updated_at: datetime | str
    summary: str
    control_assignment_id: str
    control_id: str
    control_key: str
    control_family: str
    control_statement: str
    implementation_status: str
    evidence_status: str
    owner: str | None = None
    workflow_id: str
    required_evidence_types: list[str] = Field(default_factory=list)


class LegacyControlRefEnvelope(BaseModel):
    """Historical envelope retained unchanged for inbound and stored readback."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    contract_version: Literal["proofhouse-shared-contracts/v0.1"] = (
        "proofhouse-shared-contracts/v0.1"
    )
    contract_name: Literal["ControlRef"] = "ControlRef"
    producer_capability: Literal["workflow_context"] = "workflow_context"
    producer_system: Literal["proofhouse-workflow-context"] = "proofhouse-workflow-context"
    canonical_owner: Literal["workflow_context"] = "workflow_context"
    issued_at: datetime | str
    cache_policy: Literal[
        "ref_only",
        "summary_snapshot",
        "digest_snapshot",
        "owner_dereference_required",
    ] = "summary_snapshot"
    ref: LegacyControlRef


ControlRefEnvelope = CanonicalControlRefEnvelope | LegacyControlRefEnvelope
