from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    service: str = Field(min_length=1, max_length=120)
    symptoms: str = Field(min_length=3, max_length=8000)
    infrastructure: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("service")
    @classmethod
    def normalize_service(cls, value: str) -> str:
        return "-".join(value.lower().split())

    @field_validator("infrastructure")
    @classmethod
    def bound_infrastructure(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(str(value)) > 8000:
            raise ValueError("infrastructure context is too large")
        return value


class IncidentRead(IncidentCreate):
    id: str
    status: str
    resolution: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ResolutionRequest(BaseModel):
    resolution: str = Field(min_length=3, max_length=8000)
    outcome: str = Field(min_length=3, max_length=8000)
    notes: str | None = Field(default=None, max_length=4000)

    model_config = ConfigDict(str_strip_whitespace=True)


class MemoryRead(BaseModel):
    id: str
    incident_id: str
    kind: str
    content: str
    metadata_json: dict[str, Any]
    score: float | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class MemoryEvidence(BaseModel):
    memory_id: str
    incident_id: str
    kind: str
    content: str
    metadata_json: dict[str, Any]
    created_at: datetime | None = None


class Recommendation(BaseModel):
    incident_id: str
    title: str
    service: str
    status: str
    relevance: float
    resolution: str | None
    outcome: str | None
    matched_memory: list[str]
    evidence: list[MemoryEvidence]


class MemoryAudit(BaseModel):
    source_incident_id: str
    tool: Literal["select_query"] = "select_query"
    status: Literal["completed", "failed"]
    text: str = ""
    structured_content: Any = None


class ToolExecution(BaseModel):
    name: str
    purpose: str
    status: Literal["used", "fallback", "skipped", "failed"]
    detail: str | None = None


class AgentResponse(BaseModel):
    incident_id: str
    summary: str
    recommendations: list[Recommendation]
    provider: str
    memory_audits: list[MemoryAudit] = Field(default_factory=list)
    tools_used: list[ToolExecution] = Field(default_factory=list)
