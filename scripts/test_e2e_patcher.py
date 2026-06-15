#!/usr/bin/env python3
"""
E2E test for AI Auto-Debugger (Task #134 / sub-task #147)

Run INSIDE the Docker container:
    docker exec -e PYTHONPATH=/app rcm-ai-platform-api-1 \
        python /app/scripts/test_e2e_patcher.py

Pipeline exercised:
    asyncpg INSERT → Celery .delay() → AI analyzer → auto-patcher → patch columns
    Then verifies via the REST API with a real JWT (generated from app secret).

Security:  No credentials are printed.  JWT uses create_access_token() which
           reads jwt_secret_key from the container environment.
"""

import asyncio
import json
import sys
import time
import uuid
import urllib.request
import urllib.error

# These imports work because PYTHONPATH=/app is set when the script is invoked.
from src.config import get_settings
from src.infrastructure.auth.jwt_handler import create_access_token
from src.infrastructure.auth.schemas import TokenData

BASE_URL = "http://localhost:8000"
TEST_EMAIL = "kirkmar078@gmail.com"
POLL_INTERVAL = 5    # seconds between API polls
TIMEOUT = 180         # max seconds to wait for analysis completion


# ── DB helpers ─────────────────────────────────────────────────────────────

async def _get_db_url() -> str:
    settings = get_settings()
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def fetch_user(db_url: str):
    """Return (user_id_str, user_type, internal_role) for the test account."""
    import asyncpg
    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow(
            "SELECT id, user_type, internal_role FROM users WHERE email = $1",
            TEST_EMAIL,
        )
        if not row:
            raise RuntimeError(f"User '{TEST_EMAIL}' not found in DB")
        return str(row["id"]), row["user_type"], row["internal_role"]
    finally:
        await conn.close()


async def insert_error_row(db_url: str, user_id: str) -> str:
    """
    Insert a synthetic critical Python error directly and return its UUID.
    Using asyncpg INSERT rather than /capture so we control severity and
    get the ID back (the /capture endpoint returns {"status":"captured"} only).
    The id column has no DEFAULT so we generate and supply the UUID explicitly.
    """
    import asyncpg

    new_id = str(uuid.uuid4())
    stack_trace = (
        "Traceback (most recent call last):\n"
        '  File "/app/src/services/billing_service.py", line 42, in calculate_copay\n'
        "    copay = total_charge / insurance_coverage\n"
        "ZeroDivisionError: division by zero\n"
    )

    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO error_logs (
                id, error_type, message, stack_trace,
                request_path, request_method,
                severity, analysis_status,
                user_id, occurrence_count,
                resolved, created_at, updated_at
            ) VALUES (
                $1::uuid, $2, $3, $4, $5, 'POST',
                'critical', 'analyzing',
                $6::uuid, 1,
                false, now(), now()
            )
            RETURNING id::text
            """,
            new_id,
            "ZeroDivisionError",
            "[E2E-TEST] division by zero in calculate_copay — insurance_coverage=0",
            stack_trace,
            "/api/v1/billing/calculate",
            user_id,
        )
        if not row:
            raise RuntimeError("INSERT returned no row")
        return row["id"]
    finally:
        await conn.close()


# ── Celery helper ──────────────────────────────────────────────────────────

def queue_analysis_task(error_log_id: str, user_id: str) -> str:
    """
    Send record_and_analyze_error to the Celery broker.
    Returns the Celery AsyncResult task ID.
    """
    from src.core.error_intelligence.tasks import record_and_analyze_error

    result = record_and_analyze_error.delay(
        error_log_id=error_log_id,
        error_type="ZeroDivisionError",
        message="[E2E-TEST] division by zero in calculate_copay — insurance_coverage=0",
        stack_trace=(
            "Traceback (most recent call last):\n"
            '  File "/app/src/services/billing_service.py", line 42, in calculate_copay\n'
            "    copay = total_charge / insurance_coverage\n"
            "ZeroDivisionError: division by zero\n"
        ),
        request_path="/api/v1/billing/calculate",
        request_method="POST",
        status_code=500,
        user_id=user_id,
    )
    return result.id


# ── JWT helper ─────────────────────────────────────────────────────────────

def generate_token(user_id: str, user_type: str, internal_role: str) -> str:
    """
    Generate a valid JWT using the app's own create_access_token().
    The secret is read from settings (container env) — never hardcoded here.
    """
    token_data = TokenData(
        user_id=uuid.UUID(user_id),
        email=TEST_EMAIL,
        user_type=user_type,
        internal_role=internal_role,
        provider_role=None,
        practice_id=None,
        assigned_practice_ids=[],
    )
    return create_access_token(token_data)


# ── API helpers ────────────────────────────────────────────────────────────

def api_get(path: str, token: str) -> dict:
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# ── Main test ──────────────────────────────────────────────────────────────

async def run():
    settings = get_settings()
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    print()
    print("╔══════════════════════════════════════════╗")
    print("║   AI Auto-Debugger E2E Test (#134/#147)  ║")
    print("╚══════════════════════════════════════════╝")
    print()

    # ── Step 1: Fetch test user ─────────────────────────────────────────────
    print("[1/7] Fetching test user from DB...")
    user_id, user_type, internal_role = await fetch_user(db_url)
    print(f"      user_id=...{user_id[-8:]}  user_type={user_type}  role={internal_role}")

    # ── Step 2: Generate JWT ────────────────────────────────────────────────
    print("[2/7] Generating JWT (via app create_access_token — no hardcoded secret)...")
    token = generate_token(user_id, user_type, internal_role)
    print("      JWT generated OK")

    # ── Step 3: Verify API is reachable ────────────────────────────────────
    print("[3/7] Checking API health...")
    try:
        stats_before = api_get("/api/v1/errors/stats", token)
        total_before = stats_before.get("total", "?")
        print(f"      API reachable — error_logs total before test: {total_before}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"      [✗] API returned HTTP {e.code}: {body[:120]}")
        print("      Aborting — check that the API container is running on port 8000")
        sys.exit(1)
    except Exception as e:
        print(f"      [✗] Cannot reach API: {e}")
        sys.exit(1)

    # ── Step 4: Insert synthetic critical error ─────────────────────────────
    print("[4/7] Inserting synthetic critical ZeroDivisionError into error_logs...")
    error_id = await insert_error_row(db_url, user_id)
    print(f"      error_id={error_id}")

    # ── Step 5: Queue Celery task ────────────────────────────────────────────
    print("[5/7] Queueing Celery record_and_analyze_error task...")
    try:
        celery_id = queue_analysis_task(error_id, user_id)
        print(f"      Celery task_id={celery_id}")
    except Exception as e:
        print(f"      [!] Celery queue failed: {e}")
        print("      Continuing poll — worker may not be reachable from this container.")

    # ── Step 6: Poll API until analysis completes ───────────────────────────
    print(f"\n[6/7] Polling GET /api/v1/errors/{error_id[:8]}...  (max {TIMEOUT}s)")
    elapsed = 0
    final = None

    while elapsed < TIMEOUT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        try:
            record = api_get(f"/api/v1/errors/{error_id}", token)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:80]
            print(f"  [{elapsed:>4}s] HTTP {e.code} — {msg}")
            continue
        except Exception as e:
            print(f"  [{elapsed:>4}s] poll error: {e}")
            continue

        a_status  = record.get("analysis_status", "?")
        severity  = record.get("severity", "?")
        patched   = record.get("patch_applied", False)
        pat_err   = "yes" if record.get("patch_error") else "no"

        print(
            f"  [{elapsed:>4}s]  analysis_status={a_status:<10s}  "
            f"severity={severity:<9s}  patch_applied={patched}  "
            f"patch_error={pat_err}"
        )

        if a_status in ("complete", "failed", "error"):
            final = record
            break

    if final is None:
        print(f"\n  [✗] Timed out after {TIMEOUT}s — analysis never completed")
        sys.exit(1)

    # ── Step 7: Verify patch columns ────────────────────────────────────────
    print("\n[7/7] Patch column verification:")
    patch_cols = [
        ("patch_applied",     final.get("patch_applied")),
        ("patch_applied_at",  final.get("patch_applied_at")),
        ("patch_backup_path", final.get("patch_backup_path")),
        ("patch_diff",        final.get("patch_diff")),
        ("patch_error",       final.get("patch_error")),
    ]
    for col, val in patch_cols:
        icon = "✓" if val not in (None, False, "") else "·"
        display = str(val)[:100] if val not in (None, False, "") else "(null/false)"
        print(f"  [{icon}] {col:<20s}: {display}")

    # AI analysis details
    ai = final.get("ai_analysis") or {}
    if ai:
        print("\n  AI analysis output:")
        print(f"    severity    = {ai.get('severity', '?')}")
        print(f"    confidence  = {ai.get('confidence', '?')}")
        print(f"    is_security = {ai.get('is_security_related', '?')}")
        root_cause = str(ai.get("root_cause", "")).strip()
        if root_cause:
            print(f"    root_cause  = {root_cause[:120]}")

    # Post-test stats
    print()
    try:
        stats_after = api_get("/api/v1/errors/stats", token)
        print(f"  Error stats (after test):")
        print(f"    total={stats_after.get('total')}  "
              f"critical={stats_after.get('critical')}  "
              f"auto_patched={stats_after.get('auto_patched')}")
    except Exception as e:
        print(f"  Stats fetch failed: {e}")

    # ── Final verdict ───────────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════╗")
    if final.get("patch_applied") is True:
        print("║  ✓  PASS — patch was applied             ║")
        bp = final.get("patch_backup_path") or ""
        print(f"║  backup: ...{bp[-30:]:<30s}  ║")
    elif final.get("patch_error"):
        err = (final.get("patch_error") or "")[:38]
        print("║  ~  PARTIAL — analysis OK, patch failed  ║")
        print(f"║  error: {err:<38s}║")
    elif final.get("analysis_status") == "complete":
        ai_sev   = (final.get("ai_analysis") or {}).get("severity", "?")
        ai_conf  = (final.get("ai_analysis") or {}).get("confidence", "?")
        ai_sec   = (final.get("ai_analysis") or {}).get("is_security_related", "?")
        print("║  ~  PARTIAL — analysis complete          ║")
        print(f"║  AI: severity={ai_sev}, conf={ai_conf}, sec={ai_sec}  ║")
        print("║  Patch gate: needs critical/high,        ║")
        print("║  confidence=high/medium, not security    ║")
    else:
        print("║  ✗  FAIL — analysis did not complete     ║")
    print("╚══════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    asyncio.run(run())
