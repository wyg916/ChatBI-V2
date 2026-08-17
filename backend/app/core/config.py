from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ChatBI V2"
    app_version: str = "1.0.0-rc1"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://chatbi_app@127.0.0.1:5432/chatbi_v2"
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
    query_timeout_ms: int = 8000
    query_row_limit: int = 500
    query_concurrency: int = 4
    context_token_budget: int = 6000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHATBI_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
