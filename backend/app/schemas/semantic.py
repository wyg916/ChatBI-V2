from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SemanticStatus = Literal["DRAFT", "PUBLISHED", "DEPRECATED"]


class SemanticModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    datasource_id: str


class SemanticModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    datasource_id: str | None = None
    status: SemanticStatus | None = None


class SemanticEntityCreate(BaseModel):
    name: str
    source_table: str
    primary_key: str
    time_dimension: str | None = None


class MetricCreate(BaseModel):
    name: str
    label: str
    description: str | None = None
    expression: str
    aggregation: Literal["SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"]
    filters: list[dict] = Field(default_factory=list)


class DimensionCreate(BaseModel):
    name: str
    label: str
    source_column: str
    type: Literal["STRING", "NUMBER", "BOOLEAN", "DATE", "DATETIME", "TIME"]


class JoinKey(BaseModel):
    left: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    right: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class SemanticRelationCreate(BaseModel):
    left_entity: str
    right_entity: str
    join_type: Literal["INNER", "LEFT", "RIGHT", "FULL"] = "LEFT"
    join_keys: list[JoinKey]
    cardinality: Literal["ONE_TO_ONE", "ONE_TO_MANY", "MANY_TO_ONE", "MANY_TO_MANY"]

    @model_validator(mode="after")
    def validate_join_keys(self):
        if not self.join_keys:
            raise ValueError("join_keys must contain at least one key mapping")
        return self


class BusinessTermCreate(BaseModel):
    term: str
    synonyms: list[str] = Field(default_factory=list)
    definition: str
    mapped_object: str


class EntityRead(SemanticEntityCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class MetricRead(MetricCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class DimensionRead(DimensionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class RelationRead(SemanticRelationCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class BusinessTermRead(BusinessTermCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class SemanticModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    datasource_id: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class SemanticModelDetail(SemanticModelRead):
    entities: list[EntityRead]
    metrics: list[MetricRead]
    dimensions: list[DimensionRead]
    relationships: list[RelationRead]
    business_terms: list[BusinessTermRead]


class PublishResult(BaseModel):
    success: bool
    message: str
    status: str
    version: int


class SemanticVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    semantic_model_id: str
    version: int
    snapshot: dict
    published_at: datetime
    is_current: bool = False
