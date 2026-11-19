from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

EntityType = Literal[
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "PHONE",
    "EMAIL",
    "ID_CARD",
    "BANK_ACCOUNT",
    "IP_ADDRESS",
]
RedactionMode = Literal["placeholder", "mask", "blackout"]
ReviewStatus = Literal["pending", "confirmed", "excluded"]

ENTITY_LABELS: dict[str, str] = {
    "PERSON": "人名",
    "ORGANIZATION": "机构",
    "LOCATION": "地名",
    "PHONE": "电话",
    "EMAIL": "邮箱",
    "ID_CARD": "身份证号",
    "BANK_ACCOUNT": "银行卡号",
    "IP_ADDRESS": "IP地址",
}

ALL_ENTITY_TYPES: tuple[EntityType, ...] = (
    "PERSON",
    "ORGANIZATION",
    "LOCATION",
    "PHONE",
    "EMAIL",
    "ID_CARD",
    "BANK_ACCOUNT",
    "IP_ADDRESS",
)


class EntitySpan(BaseModel):
    """A single detected or manually added sensitive entity span."""

    id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    original_text: str
    entity_type: EntityType
    placeholder: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = "modelscope-raner"
    status: ReviewStatus = "pending"
    manual: bool = False


class DocumentSession(BaseModel):
    """A locally stored redaction job with its entities and reversible mapping."""

    session_id: str
    title: str
    filename: str = "untitled.txt"
    format: Literal["txt", "md", "docx"] = "txt"
    mode: RedactionMode = "placeholder"
    enabled_types: list[EntityType] = Field(default_factory=lambda: list(ALL_ENTITY_TYPES))
    source_text: str
    redacted_text: str = ""
    entities: list[EntitySpan] = Field(default_factory=list)
    mapping: dict[str, str] = Field(default_factory=dict)
    engine: str = "modelscope-raner+basic-regex"
    model_id: str = "iic/nlp_raner_named-entity-recognition_chinese-base-news"
    elapsed_ms: int = 0
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    title: str = "未命名文稿"
    filename: str = "document.txt"
    mode: RedactionMode = "placeholder"
    enabled_types: list[EntityType] = Field(default_factory=lambda: list(ALL_ENTITY_TYPES))


class UpdateSessionRequest(BaseModel):
    mode: RedactionMode | None = None
    enabled_types: list[EntityType] | None = None
    entities: list[EntitySpan] | None = None


class AddManualEntityRequest(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    entity_type: EntityType = "PERSON"


class RestoreRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)
    strict: bool = True


class RestoreResponse(BaseModel):
    ok: bool
    restored_text: str | None = None
    replaced_count: int = 0
    unmatched_placeholders: list[str] = Field(default_factory=list)
    error: str | None = None
