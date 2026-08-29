from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CatalogSearchResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


class RelationshipRead(BaseModel):
    id: str
    source_schema: str
    source_table: str
    source_columns: list[str]
    target_schema: str | None
    target_table: str
    target_columns: list[str]


class SqlWorkspaceRequest(BaseModel):
    datasource_id: str
    sql: str = Field(min_length=1, max_length=100_000)
    row_limit: int = Field(default=200, ge=1, le=500)


class FormatSqlRequest(BaseModel):
    datasource_id: str
    sql: str = Field(min_length=1, max_length=100_000)


class SqlFormatResponse(BaseModel):
    dialect: str
    formatted_sql: str


class WorkspaceRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    datasource_id: str | None
    operation: str
    sql_text: str
    normalized_sql: str | None
    status: str
    guard: dict[str, Any]
    execution: dict[str, Any]
    oracle: dict[str, Any]
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    verified_answer_id: str | None
    created_at: datetime


class WorkspaceHistoryResponse(BaseModel):
    items: list[WorkspaceRunRead]
    total: int
    page: int
    page_size: int


class SampleResponse(BaseModel):
    datasource_id: str
    schema_name: str
    table_name: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    page: int
    page_size: int
    masked_columns: list[str]
    result_signature: str | None


class VerifyWorkspaceRunRequest(BaseModel):
    owner_name: str = Field(default="当前用户", min_length=1, max_length=128)
    status: Literal["DRAFT", "VERIFIED"] = "VERIFIED"


class VerifyWorkspaceRunResponse(BaseModel):
    run_id: str
    answer_id: str
    status: str
    result_signature: str
