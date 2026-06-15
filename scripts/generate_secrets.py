#!/usr/bin/env python3
"""Generate cryptographically secure secrets for Aethera AI production deployment.

Usage:
    python scripts/generate_secrets.py

Prints all secrets in .env format — paste them into your .env file.
Does NOT write any file automatically so you can review before committing.
"""

import secrets
import sys


def generate_fernet_key() -> str:
    """Generate a URL-safe base64-encoded 32-byte Fernet key.

    Uses only stdlib so the script works before dependencies are installed.
    Falls back to a stdlib-only implementation when cryptography is not available.
    """
    try:
        from cryptography.fernet import Fernet  # type: ignore[import]
        return Fernet.generate_key().decode()
    except ImportError:
        import base64
        # Fernet keys are 32 random bytes, URL-safe base64-encoded with padding
        raw = secrets.token_bytes(32)
        return base64.urlsafe_b64encode(raw).decode()


def main() -> None:
    print("=" * 62)
    print("  Aethera AI — Production Secrets Generator")
    print("=" * 62)
    print()
    print("Copy the block below into your .env file.")
    print()

    db_password    = secrets.token_urlsafe(20)
    minio_password = secrets.token_urlsafe(20)

    generated = {
        "APP_SECRET_KEY":      secrets.token_hex(32),
        "JWT_SECRET_KEY":      secrets.token_hex(32),
        "PHI_ENCRYPTION_KEY":  generate_fernet_key(),
        "FIELD_ENCRYPTION_KEY": generate_fernet_key(),
        "POSTGRES_PASSWORD":   db_password,
        "MINIO_ROOT_PASSWORD": minio_password,
    }

    # ── Print in .env format ──────────────────────────────────────────────────
    print("# ── Generated secrets — paste into .env ──────────────────────────")
    for key, value in generated.items():
        print(f"{key}={value}")
    print()

    # ── Print convenience DATABASE_URL and other derived values ──────────────
    print("# ── Derived connection strings (update DB user/host if needed) ───")
    print(f"DATABASE_URL=postgresql+asyncpg://aethera:{db_password}@postgres:5432/aethera_db")
    print(f"REDIS_URL=redis://redis:6379/0")
    print(f"CELERY_BROKER_URL=redis://redis:6379/2")
    print(f"CELERY_RESULT_BACKEND=redis://redis:6379/2")
    print(f"MINIO_ROOT_USER=aethera_minio")
    print(f"MINIO_ROOT_PASSWORD={minio_password}")
    print()

    # ── Remind about manually-obtained values ─────────────────────────────────
    print("# ── Fill in manually ─────────────────────────────────────────────")
    print("OLLAMA_API_KEY=          # https://ollama.com → account → API keys")
    print("TUNNEL_TOKEN=            # Cloudflare Zero Trust → Networks → Tunnels")
    print()

    print("-" * 62)
    print("Next steps:")
    print("  1. Paste the generated block above into your .env file.")
    print("  2. Set OLLAMA_API_KEY and TUNNEL_TOKEN.")
    print("  3. Run: chmod +x scripts/deploy.sh && ./scripts/deploy.sh")
    print("-" * 62)

    # Sanity check: ensure no secret is empty
    for key, value in generated.items():
        if not value:
            print(f"ERROR: {key} is empty — generation failed.", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
