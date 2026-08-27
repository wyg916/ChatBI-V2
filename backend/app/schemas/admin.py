from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QuerySecuritySettings(BaseModel):
    query_timeout_ms: int = Field(default=8000, ge=1000, le=120000)
    max_rows: int = Field(default=500, ge=1, le=5000)
    read_only_query: bool = True
    dangerous_sql_block: bool = True
    result_verification: bool = True
    sql_guard_policy: Literal["STRICT", "STANDARD"] = "STRICT"
    allowed_schemas: list[str] = Field(default_factory=list, max_length=100)
    blocked_schemas: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("read_only_query", "dangerous_sql_block", "result_verification")
    @classmethod
    def mandatory_guards(cls, value: bool) -> bool:
        if not value:
            raise ValueError("V1 safety controls cannot be disabled")
        return value


class WorkspaceConfigSettings(BaseModel):
    workspace_name: str = Field(default="", min_length=1, max_length=255)
    default_datasource_id: str | None = None
    default_semantic_model_id: str | None = None
    status: Literal["ACTIVE", "READ_ONLY"] = "ACTIVE"


class AppearanceSettings(BaseModel):
    product_name: str = Field(default="ChatBI V2", min_length=1, max_length=64)
    brand_tagline: str = Field(default="让每个业务问题都有可验证的数据答案", max_length=160)
    logo_url: str = Field(default="", max_length=2048)
    primary_color: str = Field(default="#2563EB", pattern=r"^#[0-9A-Fa-f]{6}$")
    theme: Literal["LIGHT", "SYSTEM"] = "LIGHT"


class SettingsPatch(BaseModel):
    query_security: QuerySecuritySettings | None = None
    workspace: WorkspaceConfigSettings | None = None
    appearance: AppearanceSettings | None = None
    expected_version: int | None = Field(default=None, ge=1)


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    member_count: int
    roles: dict[str, int]
    status: str
    isolation: str
    datasources: list[dict]
    semantic_models: list[dict]


class SettingsRead(BaseModel):
    query_security: QuerySecuritySettings
    workspace: WorkspaceConfigSettings
    appearance: AppearanceSettings
    workspace_summary: WorkspaceSummary
    version: int
    updated_at: datetime | None = None


class ProviderPatch(BaseModel):
    enabled: bool


class ProviderStatus(BaseModel):
    id: str
    provider_id: str
    model_id: str | None
    model_name: str | None
    display_name: str
    configured: bool
    enabled: bool
    active: bool
    healthy: bool | None
    health_message: str
    last_checked_at: datetime | None
    capabilities: list[str]
    priority: int
    cost_policy: str
    credential_source: str
    protocol: str
    external_model: bool
    structured_output: bool = True


class ProviderCatalog(BaseModel):
    active_provider: str
    selection_strategy: str
    secrets_exposed: bool = False
    items: list[ProviderStatus]


class SystemInformation(BaseModel):
    app_version: str
    git_sha: str
    release_version: str
    backend_health: str
    frontend_build: str
    database_status: str
    migration_head: str
    rag_status: str
    sandbox_status: str
    model_gateway_status: str
