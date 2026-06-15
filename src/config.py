"""
Aethera AI -- Application configuration.
All settings are loaded from environment variables (or .env file).
Uses pydantic-settings for validation, type coercion, and fail-fast on missing secrets.
"""

from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "aethera-ai"
    app_title: str = "Aethera AI"
    app_env: str = "development"
    app_debug: bool = False
    app_port: int = 8000
    app_secret_key: str = "CHANGE_ME"
    app_url: str = "https://rcm.aetherahealthcare.com"
    frontend_url: str = "https://rcm.aetherahealthcare.com"

    # Database
    database_url: str = "postgresql+asyncpg://aethera:password@postgres:5432/aethera_db"
    database_pool_size: int = 30
    database_max_overflow: int = 20
    database_pool_pre_ping: bool = True
    database_echo: bool = False

    # Redis
    redis_url: str = "redis://redis:6379/0"
    redis_cache_db: int = 1
    redis_celery_db: int = 2
    redis_mfa_db: int = 3
    redis_mfa_url: str = "redis://redis:6379/3"

    # Celery
    celery_broker_url: str = "redis://redis:6379/2"
    celery_result_backend: str = "redis://redis:6379/2"
    celery_task_always_eager: bool = False
    celery_worker_concurrency: int = 8

    # Vector DB
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection_coding_guidelines: str = "icd10_guidelines"
    qdrant_collection_payer_policies: str = "payer_policies"
    qdrant_collection_appeal_templates: str = "appeal_templates"

    # AI provider selection: "ollama" (default, cheaper) or "anthropic"
    ai_provider: str = "ollama"

    # AI / LLM (Anthropic Claude)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"          # primary — fast, cost-effective
    anthropic_model_heavy: str = "claude-opus-4-6"       # heavy tasks — appeals, complex coding
    anthropic_temperature: float = 0.1
    anthropic_timeout: int = 120
    anthropic_max_retries: int = 3
    anthropic_max_concurrent: int = 50                   # semaphore for burst concurrency
    anthropic_max_tokens: int = 4096

    # AI / LLM (Ollama Cloud — kept as fallback)
    ollama_base_url: str = "https://ollama.com"
    ollama_api_key: str = ""
    ollama_model: str = "qwen3-coder:480b-cloud"
    ollama_fallback_model: str = "deepseek-v3.1:671-cloud"
    ollama_temperature: float = 0.1
    ollama_timeout: int = 120
    ollama_max_retries: int = 3

    # Embeddings
    embedding_provider: str = "voyageai"
    voyageai_api_key: str = ""
    voyageai_model: str = "voyage-large-2"
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1024

    # S3 / Object Storage
    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket_documents: str = "aethera-documents"
    s3_bucket_era_files: str = "aethera-era-files"
    s3_bucket_appeals: str = "aethera-appeals"
    s3_bucket_audit_archive: str = "aethera-audit-archive"
    s3_encryption: str = "AES256"
    s3_region: str = "us-east-1"

    # Auth / JWT
    jwt_secret_key: str = "CHANGE_ME"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"
    mfa_issuer: str = "Aethera AI"
    mfa_backup_codes_count: int = 10
    password_min_length: int = 12
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30
    session_timeout_minutes: int = 15

    # Clearinghouse
    clearinghouse_provider: str = "availity"
    clearinghouse_api_url: str = ""
    clearinghouse_api_key: str = ""
    clearinghouse_sender_id: str = ""
    clearinghouse_receiver_id: str = ""
    edi_interchange_sender_id: str = ""
    edi_interchange_receiver_id: str = ""

    # FHIR
    fhir_server_url: str = ""
    fhir_client_id: str = ""
    fhir_client_secret: str = ""
    fhir_auth_type: str = "oauth2"
    fhir_scope: str = "patient/*.read encounter/*.read"

    # Encryption
    phi_encryption_key: str = "CHANGE_ME"
    field_encryption_key: str = "CHANGE_ME"

    # HIPAA
    audit_log_retention_years: int = 7
    phi_redaction_enabled: bool = True

    # Monitoring
    sentry_dsn: str = ""
    prometheus_enabled: bool = True
    log_level: str = "INFO"
    log_format: str = "json"

    # Rate Limiting (SlowAPI)
    rate_limit_default: str = "200/minute"
    rate_limit_auth: str = "20/minute"
    rate_limit_ai_endpoints: str = "60/minute"
    rate_limit_bulk_operations: str = "20/minute"

    # Cloudflare Tunnel
    tunnel_token: str = ""
    domain: str = "rcm.aetherahealthcare.com"

    # AI Agent Service (autonomous queue processing)
    ai_agent_service_url: str = "http://ai-agents:8001"
    ai_agent_service_api_key: str = ""
    ai_agent_confidence_threshold: float = 0.7
    ai_agent_enabled: bool = True

    # CORS
    cors_origins: str = "https://rcm.aetherahealthcare.com,https://agents.aetherahealthcare.com,http://localhost:5173,http://localhost:5174,http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
