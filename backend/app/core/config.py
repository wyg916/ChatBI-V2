from functools import lru_cache
from pathlib import Path
from tempfile import gettempdir

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ChatBI V2"
    app_version: str = "1.1.0"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2"
    meta_password: SecretStr = SecretStr("")
    datasource_secret_key: str = ""
    seed_demo_semantic_model: bool = False
    demo_postgres_host: str = "127.0.0.1"
    demo_postgres_port: int = 5432
    demo_postgres_database: str = "chatbi_v2"
    demo_postgres_schema: str = "demo_business"
    demo_postgres_username: str = "chatbi_reader"
    demo_postgres_password: str = ""
    demo_mysql_host: str = "127.0.0.1"
    demo_mysql_port: int = 3306
    demo_mysql_database: str = "chatbi_demo_business"
    demo_mysql_username: str = "chatbi_reader"
    demo_mysql_password: str = ""
    model_provider: str = "deterministic"
    model_base_url: str = ""
    model_api_key: str = ""
    model_name: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_api_key: SecretStr = SecretStr("")
    kimi_model_name: str = "kimi-k2.6"
    mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    mimo_api_key: SecretStr = SecretStr("")
    mimo_model_name: str = "mimo-v2.5"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model_name: str = "deepseek-v4-flash"
    query_timeout_ms: int = 30000
    query_row_limit: int = 500
    query_concurrency: int = 4
    context_token_budget: int = 6000
    semantic_runtime_mode: Literal["wren", "local"] = "wren"
    rag_mode: Literal["off", "shadow", "canary", "on"] = "on"
    agent_mode: Literal["off", "shadow", "canary", "on"] = "on"
    agent_allowed_routes: str = "COMPLEX_ANALYSIS"
    rag_fallback_enabled: bool = True
    agent_fallback_enabled: bool = True
    legacy_rag_base_url: str = "http://127.0.0.1:8001"
    legacy_rag_bearer_token: SecretStr = SecretStr("")
    rag_shared_secret: SecretStr = SecretStr("")
    rag_retry_count: int = 1
    rag_health_timeout_ms: int = 1500
    legacy_rag_require_workspace_echo: bool = True
    legacy_agent_base_url: str = ""
    legacy_agent_bearer_token: SecretStr = SecretStr("")
    agent_timeout_ms: int = 30000
    agent_max_steps: int = 8
    agent_max_tool_calls: int = 12
    agent_max_replan: int = 2
    agent_max_depth: int = 2
    agent_token_budget: int = 6000
    bootstrap_admin_password: SecretStr = SecretStr("")
    bootstrap_analyst_password: SecretStr = SecretStr("")
    session_cookie_name: str = "chatbi_session"
    session_ttl_minutes: int = 480
    remember_session_ttl_days: int = 30
    session_cookie_secure: bool = False
    login_max_failures: int = 8
    login_window_minutes: int = 15
    attachment_storage_dir: str = str(Path(gettempdir()) / "chatbi-v2-attachments")
    attachment_max_bytes: int = 25 * 1024 * 1024
    attachment_max_rows: int = 100_000
    attachment_text_max_chars: int = 200_000
    attachment_ttl_hours: int = 24
    chat_recent_message_limit: int = 20
    general_model_provider: str = "auto"
    vision_model_provider: str = "auto"
    vision_model_name: str = ""

    @property
    def agent_route_allowlist(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.agent_allowed_routes.split(",") if item.strip())

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHATBI_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
