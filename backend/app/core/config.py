from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ChatBI V2"
    app_version: str = "0.1.0-day1"
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="CHATBI_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
