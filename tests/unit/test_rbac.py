"""Unit tests for RBAC (super-admin gate + agent-area scoping)."""
from src.core.rbac import (
    AGENT_AREAS,
    is_super_admin,
    user_agent_areas,
    can_access_area,
)


def _user(role="coder", user_type="internal"):
    return {"user_type": user_type, "internal_role": role}


class TestSuperAdmin:
    def test_company_admin_is_super(self):
        assert is_super_admin(_user("company_admin")) is True

    def test_specialist_is_not_super(self):
        assert is_super_admin(_user("coder")) is False

    def test_provider_company_admin_is_not_super(self):
        assert is_super_admin(_user("company_admin", user_type="provider")) is False

    def test_none_safe(self):
        assert is_super_admin({}) is False


class TestAgentAreas:
    def test_super_admin_gets_all_areas(self):
        assert user_agent_areas(_user("company_admin")) == set(AGENT_AREAS)

    def test_coder_areas(self):
        assert user_agent_areas(_user("coder")) == {"coding", "charge_capture"}

    def test_denial_analyst_areas(self):
        assert user_agent_areas(_user("denial_analyst")) == {"denials"}

    def test_assignment_roles_add_areas(self):
        areas = user_agent_areas(_user("coder"), assignment_roles=["denial_analyst", "eligibility_specialist"])
        assert {"coding", "denials", "eligibility"}.issubset(areas)

    def test_unknown_role_no_areas(self):
        assert user_agent_areas(_user("mystery")) == set()


class TestCanAccessArea:
    def test_super_admin_any_area(self):
        assert can_access_area(_user("company_admin"), "credentialing") is True

    def test_specialist_only_own_area(self):
        assert can_access_area(_user("coder"), "coding") is True
        assert can_access_area(_user("coder"), "denials") is False
