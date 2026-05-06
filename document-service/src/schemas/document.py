import json
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal, Optional, List, Any
from datetime import datetime


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=50000)
    tags: Optional[List[str]] = Field(default=None, max_length=20)


class DocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    content: Optional[str] = Field(default=None, min_length=1, max_length=50000)
    file_path: Optional[str] = None
    tags: Optional[List[str]] = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    file_path: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    mime_type: Optional[str]
    owner_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_deleted: bool
    tags: Optional[List[str]]
    word_count: Optional[int] = None
    language: Optional[str] = None
    page_count: Optional[int] = None
    entities: Optional[Any] = None
    category: Optional[str] = None
    sentiment: Optional[str] = None
    processing_status: Optional[str] = "completed"

    @field_validator("entities", mode="before")
    @classmethod
    def _parse_entities(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return None
        return v


class SummarizeRequest(BaseModel):
    max_length: int = Field(default=150, ge=10, le=1000)


class SummarizeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    document_id: str
    original_length: int
    summary: str
    summary_length: int
    model_used: str


class TagSuggestResponse(BaseModel):
    suggested_tags: List[str]
    model_used: str


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class SemanticSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    owner_id: Optional[str]
    similarity_score: float
    tags: Optional[List[str]]


class SemanticSearchResponse(BaseModel):
    results: List[SemanticSearchResult]
    mode: Literal["embedding", "tfidf"]
    total: int
