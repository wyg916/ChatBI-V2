from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class DataSourceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(min_length=1, max_length=255)
    type: Literal["postgresql", "mysql"]
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1)
    username: str = Field(min_length=1)
    password: SecretStr
    ssl: bool = False
    schema_name: str | None = Field(default=None, alias="schema")


class DataSourceUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    host: str | None = Field(default=None, min_length=1)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1)
    username: str | None = Field(default=None, min_length=1)
    password: SecretStr | None = None
    ssl: bool | None = None
    schema_name: str | None = Field(default=None, alias="schema")


class DataSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: str
    name: str
    type: str
    host: str
    port: int
    database: str
    username: str
    ssl: bool
    schema_name: str | None = Field(validation_alias="schema", serialization_alias="schema")
    status: str
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConnectionTestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = "Connection test"
    type: Literal["postgresql", "mysql"]
    host: str
    port: int = Field(ge=1, le=65535)
    database: str
    username: str
    password: SecretStr
    ssl: bool = False
    schema_name: str | None = Field(default=None, alias="schema")


class OperationResult(BaseModel):
    success: bool
    message: str
    schemas: int | None = None
    tables: int | None = None
    columns: int | None = None
    relationships: int | None = None


class SchemaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    qualified_name: str


class TableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    schema_name: str
    name: str
    qualified_name: str
    comment: str | None


class ColumnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    qualified_name: str
    data_type: str
    nullable: bool
    primary_key: bool
    foreign_key: bool
    default: str | None
    comment: str | None
    sample_values: list
