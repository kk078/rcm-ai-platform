"""
Test provider portal endpoints with a properly structured JWT.
Run: docker compose -f docker-compose.prod.yml exec -T api python /app/scripts/test_endpoints.py
"""
import asyncio
import json
import sys
import time
import urllib.request
import urllib.error
import uuid as uuid_mod
import datetime

async def get_user_id():
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session
    from src.infrastructure.database.models import User
    async with async_session() as db:
        result = await db.execute(
            select(User.id, User.email, User.practice_id)
            .where(User.email == "kirkmar078@gmail.com")
        )
        row = result.first()
        if row:
            return str(row.id), str(row.practice_id) if row.practice_id else None
        return None, None

async def main():
    sys.path.insert(0, "/app")

    # Get actual user UUID from DB
    user_id, practice_id = await get_user_id()
    if not user_id:
        print("ERROR: User kirkmar078@gmail.com not found in database")
        sys.exit(1)

    print(f"User ID: {user_id}")
    print(f"Practice ID from DB: {practice_id}")

    # Use known practice ID if DB didn't have it
    if not practice_id:
        practice_id = "9430a396-1a3f-42a4-bdac-d066c3c16c21"
        print(f"Using hardcoded practice_id: {practice_id}")

    # Generate properly structured JWT
    import jwt
    SECRET = "7a7db173c6ba39e9a662f9cfd6d992d4ed2644d6f9951419bf0587f8a3eb4c4a"
    now = datetime.datetime.now(datetime.timezone.utc)
    token = jwt.encode(
        {
            "sub": user_id,
            "type": "access",
            "practice_id": practice_id,
            "role": "provider",
            "jti": str(uuid_mod.uuid4()),
            "iat": now,
            "exp": now + datetime.timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )
    print(f"JWT: {token[:60]}...\n")

    endpoints = [
        ("GET", "http://localhost:8000/api/v1/portal/dashboard", "Dashboard"),
        ("GET", "http://localhost:8000/api/v1/portal/claims?page_size=3", "Claims"),
        ("GET", "http://localhost:8000/api/v1/portal/denials?page_size=3", "Denials"),
        ("GET", "http://localhost:8000/api/v1/portal/invoices", "Invoices"),
        ("GET", "http://localhost:8000/api/v1/provider-analytics/summary?period_days=30", "Analytics Summary"),
        ("GET", "http://localhost:8000/api/v1/provider-analytics/denial-breakdown?period_days=30", "Analytics Denials"),
    ]

    for method, url, name in endpoints:
        try:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                print(f"[{name}] HTTP 200 OK")
                preview = json.dumps(data)[:200]
                print(f"  {preview}\n")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            print(f"[{name}] HTTP {e.code} ERROR")
            print(f"  {body[:400]}\n")
        except Exception as e:
            print(f"[{name}] FAILED: {e}\n")

    print("=== Done ===")

if __name__ == "__main__":
    asyncio.run(main())
