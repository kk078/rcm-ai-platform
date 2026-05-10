#!/usr/bin/env python3
"""Generate cryptographically secure secrets for production deployment."""

import secrets
import base64
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def generate_secrets() -> dict[str, str]:
    """Generate all required secret values."""
    return {
        "APP_SECRET_KEY": secrets.token_hex(32),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "PHI_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "FIELD_ENCRYPTION_KEY": base64.b64encode(secrets.token_bytes(32)).decode(),
        "POSTGRES_PASSWORD": secrets.token_hex(16),
        "REDIS_PASSWORD": secrets.token_hex(16),
        "MINIO_PASSWORD": secrets.token_hex(16),
    }


def create_env_prod(secrets: dict[str, str]) -> None:
    """Create .env.prod from .env.example with generated secrets."""
    example_path = PROJECT_ROOT / ".env.example"
    env_prod_path = PROJECT_ROOT / ".env.prod"

    if not example_path.exists():
        print(f"ERROR: {example_path} not found")
        return

    content = example_path.read_text(encoding="utf-8")

    # Replace secret placeholders with generated values
    content = content.replace("CHANGE_ME_TO_RANDOM_64_CHAR_STRING", secrets["APP_SECRET_KEY"])
    content = content.replace("CHANGE_ME_ANOTHER_RANDOM_STRING", secrets["JWT_SECRET_KEY"])
    # Handle both encryption key placeholders (PHI first, then FIELD)
    content = content.replace(
        "CHANGE_ME_32_BYTE_BASE64_KEY   # AES-256 key for PHI fields",
        secrets["PHI_ENCRYPTION_KEY"] + "   # AES-256 key for PHI fields",
    )
    content = content.replace(
        "CHANGE_ME_32_BYTE_BASE64_KEY  # Separate key for field-level encryption",
        secrets["FIELD_ENCRYPTION_KEY"] + "  # Separate key for field-level encryption",
    )
    # Fallback in case the exact comments don't match
    if "CHANGE_ME_32_BYTE_BASE64_KEY" in content:
        content = content.replace("CHANGE_ME_32_BYTE_BASE64_KEY", secrets["FIELD_ENCRYPTION_KEY"])

    # Override production settings
    lines = content.splitlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("APP_ENV="):
            new_lines.append("APP_ENV=production")
        elif stripped.startswith("APP_DEBUG="):
            new_lines.append("APP_DEBUG=false")
        elif stripped.startswith("APP_URL="):
            new_lines.append("APP_URL=https://rcm.aetheraonline.com")
        elif stripped.startswith("FRONTEND_URL="):
            new_lines.append("FRONTEND_URL=https://rcm.aetheraonline.com")
        elif stripped.startswith("DATABASE_URL="):
            new_lines.append(
                f"DATABASE_URL=postgresql+asyncpg://medclaim:{secrets['POSTGRES_PASSWORD']}@postgres:5432/medclaim_db"
            )
        elif stripped.startswith("REDIS_URL="):
            new_lines.append(f"REDIS_URL=redis://default:{secrets['REDIS_PASSWORD']}@redis:6379/0")
        elif stripped.startswith("CELERY_BROKER_URL="):
            new_lines.append(f"CELERY_BROKER_URL=redis://default:{secrets['REDIS_PASSWORD']}@redis:6379/2")
        elif stripped.startswith("CELERY_RESULT_BACKEND="):
            new_lines.append(f"CELERY_RESULT_BACKEND=redis://default:{secrets['REDIS_PASSWORD']}@redis:6379/2")
        elif stripped.startswith("QDRANT_URL="):
            new_lines.append("QDRANT_URL=http://qdrant:6333")
        elif stripped.startswith("S3_ENDPOINT="):
            new_lines.append("S3_ENDPOINT=http://minio:9000")
        elif stripped.startswith("S3_ACCESS_KEY="):
            new_lines.append("S3_ACCESS_KEY=medclaim_minio")
        elif stripped.startswith("S3_SECRET_KEY="):
            new_lines.append(f"S3_SECRET_KEY={secrets['MINIO_PASSWORD']}")
        else:
            new_lines.append(line)

    # Append Ollama and tunnel config
    new_lines.append("")
    new_lines.append("# ── Ollama Cloud API ────────────────────────────────────────")
    new_lines.append("# Get your API key from https://ollama.com → account settings → API keys")
    new_lines.append("OLLAMA_API_KEY=")
    new_lines.append("OLLAMA_MODEL=qwen3-coder:480b-cloud")
    new_lines.append("OLLAMA_FALLBACK_MODEL=deepseek-v3.1:671-cloud")
    new_lines.append("OLLAMA_TEMPERATURE=0.1")
    new_lines.append("")
    new_lines.append("# ── Cloudflare Tunnel ────────────────────────────────────────")
    new_lines.append("# Get from Cloudflare Zero Trust → Networks → Tunnels")
    new_lines.append("TUNNEL_TOKEN=")

    content = "\n".join(new_lines)
    env_prod_path.write_text(content, encoding="utf-8")
    print(f"Created {env_prod_path}")


def main() -> None:
    print("=" * 60)
    print("MedClaim AI — Generating Production Secrets")
    print("=" * 60)
    print()

    secrets = generate_secrets()

    print("Generated secrets:")
    for key, value in secrets.items():
        display = value[:12] + "..." if len(value) > 20 else value
        print(f"  {key}={display}")
    print()

    create_env_prod(secrets)

    print()
    print("IMPORTANT: Edit .env.prod and fill in:")
    print("  1. OLLAMA_API_KEY — your Ollama Cloud API key from https://ollama.com")
    print("  2. TUNNEL_TOKEN — from Cloudflare Tunnel dashboard")
    print()


if __name__ == "__main__":
    main()