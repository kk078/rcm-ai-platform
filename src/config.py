"""
Application configuration loaded from environment variables.
Uses pydantic-settings for validation and type coercion.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

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
    database_echo: bool = False

    # ── Redis ────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_db: int = 1
    redis_celery_db: int = 2

    # ── Celery ───────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/2"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_always_eager: bool = False

    # ── Vector DB ────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection_coding_guidelines: str = "icd10_guidelines"
    qdrant_collection_payer_policies: str = "payer_policies"
    qdrant_collection_appeal_templates: str = "appeal_templates"

    # ── AI / LLM (Ollama Cloud) ──────────────────────────────
    ollama_api_key: str = ""
    ollama_model: str = "qwen3-coder:480b-cloud"
    ollama_fallback_model: str = "deepseek-v3.1:671-cloud"
    ollama_temperature: float = 0.1

    # ── Embeddings ───────────────────────────────────────────
    embedding_provider: str = "voyageai"
    voyageai_api_key: str = ""
    voyageai_model: str = "voyage-large-2"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1024

    # ── S3 / Object Storage ──────────────────────────────────
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_documents: str = "medclaim-documents"
    s3_bucket_era_files: str = "medclaim-era-files"
    s3_bucket_appeals: str = "medclaim-appeals"
    s3_bucket_audit_archive: str = "medclaim-audit-archive"
    s3_encryption: str = "AES256"
    s3_region: str = "us-east-1"

    # ── Auth ─────────────────────────────────────────────────
    jwt_secret_key: str = "CHANGE_ME"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"
    mfa_issuer: str = "MedClaim AI"
    password_min_length: int = 12
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30

    # ── Clearinghouse ────────────────────────────────────────
    clearinghouse_provider: str = "availity"
    clearinghouse_api_url: str = ""
    clearinghouse_api_key: str = ""
    clearinghouse_sender_id: str = ""
    clearinghouse_receiver_id: str = ""
    edi_interchange_sender_id: str = ""
    edi_interchange_receiver_id: str = ""

    # ── FHIR ─────────────────────────────────────────────────
    fhir_server_url: str = ""
    fhir_client_id: str = ""
    fhir_client_secret: str = ""
    fhir_auth_type: str = "oauth2"
    fhir_scope: str = "patient/*.read encounter/*.read"

    # ── Encryption ───────────────────────────────────────────
    phi_encryption_key: str = "CHANGE_ME"
    field_encryption_key: str = "CHANGE_ME"

    # ── HIPAA ────────────────────────────────────────────────
    audit_log_retention_years: int = 7
    session_timeout_minutes: int = 15
    phi_redaction_enabled: bool = True

    # ── Monitoring ───────────────────────────────────────────
    sentry_dsn: str = ""
    prometheus_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "json"

    # ── Rate Limiting ────────────────────────────────────────
    rate_limit_default: str = "100/minute"
    rate_limit_ai_endpoints: str = "30/minute"
    rate_limit_bulk_operations: str = "10/minute"

    # ── Cloudflare Tunnel ────────────────────────────────────
    tunnel_token: str = ""

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
