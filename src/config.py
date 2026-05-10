"""
Application configuration loaded from environment variables.
Uses pydantic-settings for validation and type coercion.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    # ── App ──────────────────────────────────────────────────
    app_name: str = "medclaim-ai"
    app_env: str = "development"
    app_debug: bool = False
    app_port: int = 8000
    app_secret_key: str = "CHANGE_ME"
    app_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # ── Database ─────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://medclaim:password@localhost:5432/medclaim_db"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # ── Redis ────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_db: int = 1
    redis_celery_db: int = 2

    # ── Celery ───────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/2"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Vector DB ────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # ── AI / LLM ─────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"
    anthropic_max_tokens: int = 4096
    anthropic_temperature: float = 0.1

    # ── Embeddings ───────────────────────────────────────────
    embedding_provider: str = "voyageai"
    voyageai_api_key: str = ""
    embedding_dimensions: int = 1024

    # ── S3 / Object Storage ──────────────────────────────────
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_documents: str = "medclaim-documents"
    s3_bucket_era_files: str = "medclaim-era-files"
    s3_bucket_appeals: str = "medclaim-appeals"
    s3_region: str = "us-east-1"

    # ── Auth ─────────────────────────────────────────────────
    jwt_secret_key: str = "CHANGE_ME"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30

    # ── Clearinghouse ────────────────────────────────────────
    clearinghouse_provider: str = "availity"
    clearinghouse_api_url: str = ""
    clearinghouse_api_key: str = ""

    # ── FHIR ─────────────────────────────────────────────────
    fhir_server_url: str = ""
    fhir_client_id: str = ""
    fhir_client_secret: str = ""

    # ── Encryption ───────────────────────────────────────────
    phi_encryption_key: str = "CHANGE_ME"
    field_encryption_key: str = "CHANGE_ME"

    # ── HIPAA ────────────────────────────────────────────────
    audit_log_retention_years: int = 7
    session_timeout_minutes: int = 15
    phi_redaction_enabled: bool = True

    # ── Monitoring ───────────────────────────────────────────
    sentry_dsn: str = ""
    log_level: str = "INFO"
    log_format: str = "json"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
