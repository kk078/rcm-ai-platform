#!/usr/bin/env python3
"""
Create the first provider-portal login (house verification account).

Stands up:
  1. A house Practice  ("Aethera Health") so the provider portal has a
     practice to scope data to.  All RCM data (claims, payments, prior-auth,
     charge intake, analytics) is filtered by user.practice_id for provider
     users, so the login is only meaningful when attached to a practice.
  2. A Provider record (Kiran Marr) linked to that practice via the user.
  3. A provider User  (user_type="provider") linked to the practice + provider,
     so it can log in at  rcm.aetherahealthcare.com/portal/  and see the
     account status for that practice.

Idempotent: re-running updates the existing rows instead of duplicating.

Run inside the api container:
  podman exec -e PYTHONPATH=/app rcm-ai-platform-api-1 python scripts/create_provider_login.py
"""

import asyncio
from datetime import datetime, timezone, date

from sqlalchemy import select
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import User, Practice, Provider
from src.infrastructure.auth.service import AuthService

# ── Provider login (distinct from the staff admin login) ─────────────────
PROV_EMAIL    = "kirkmar078+provider@gmail.com"   # plus-addressed -> same inbox
PROV_PASSWORD = "Mykia@0902"                       # temp; forced change on 1st login
PROV_FIRST    = "Kiran"
PROV_LAST     = "Marr"
PROV_ROLE     = "practice_admin"                   # full provider-portal access

# ── House practice (verification; rename when onboarding a real client) ──
PRACTICE_NAME = "Aethera Health"
PRACTICE_TIN  = "00-0000000"                        # placeholder, encrypted at rest
GROUP_NPI     = "1999999990"
PROVIDER_NPI  = "1999999999"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def main() -> None:
    auth = AuthService()

    async with async_session() as s:
        now = _now()

        # 1) Practice ------------------------------------------------------
        practice = (await s.execute(
            select(Practice).where(Practice.practice_name == PRACTICE_NAME)
        )).scalar_one_or_none()

        if practice is None:
            practice = Practice(
                practice_name=PRACTICE_NAME,
                legal_name="Aethera Health LLC",
                tin=PRACTICE_TIN,
                group_npi=GROUP_NPI,
                specialty_primary="Family Medicine",
                status="active",
                timezone="America/New_York",
                intake_method="portal",
                go_live_date=date.today(),
                onboarded_at=now,
                created_at=now,
                updated_at=now,
            )
            s.add(practice)
            await s.flush()
            print(f"[+] Practice created: {practice.practice_name} ({practice.id})")
        else:
            print(f"[=] Practice exists: {practice.practice_name} ({practice.id})")

        # 2) Provider ------------------------------------------------------
        provider = (await s.execute(
            select(Provider).where(Provider.npi == PROVIDER_NPI)
        )).scalar_one_or_none()

        if provider is None:
            provider = Provider(
                npi=PROVIDER_NPI,
                first_name=PROV_FIRST,
                last_name=PROV_LAST,
                credential="MD",
                specialty="Family Medicine",
                is_individual=True,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            s.add(provider)
            await s.flush()
            print(f"[+] Provider created: {provider.first_name} {provider.last_name} ({provider.id})")
        else:
            print(f"[=] Provider exists: {provider.id}")

        # 3) Provider user (login) ----------------------------------------
        user = (await s.execute(
            select(User).where(User.email == PROV_EMAIL)
        )).scalar_one_or_none()

        pwd_hash = auth.hash_password(PROV_PASSWORD)

        if user is None:
            user = User(
                email=PROV_EMAIL,
                password_hash=pwd_hash,
                first_name=PROV_FIRST,
                last_name=PROV_LAST,
                user_type="provider",
                provider_role=PROV_ROLE,
                practice_id=practice.id,
                provider_id=provider.id,
                is_active=True,
                mfa_enabled=False,
                must_change_password=True,
                password_changed_at=now,
                created_at=now,
                updated_at=now,
            )
            s.add(user)
            print(f"[+] Provider login created: {PROV_EMAIL}")
        else:
            user.password_hash = pwd_hash
            user.user_type = "provider"
            user.provider_role = PROV_ROLE
            user.practice_id = practice.id
            user.provider_id = provider.id
            user.is_active = True
            user.must_change_password = True
            user.updated_at = now
            print(f"[=] Provider login updated: {PROV_EMAIL}")

        await s.commit()

    print("\nDone.")
    print(f"  Login URL : https://rcm.aetherahealthcare.com/portal/")
    print(f"  Email     : {PROV_EMAIL}")
    print(f"  Password  : {PROV_PASSWORD}  (you'll be forced to change it on first login)")
    print(f"  Practice  : {PRACTICE_NAME}  (data scopes to this practice)")


if __name__ == "__main__":
    asyncio.run(main())
