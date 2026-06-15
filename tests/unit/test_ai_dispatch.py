"""
Comprehensive unit tests for the AI Dispatch module.

Covers:
  - QUEUE_TYPE_TO_AGENT mapping (all 11 types + aliases)
  - DISPATCHABLE_QUEUE_TYPES completeness and consistency
  - AGENT_TYPE_LABEL completeness
  - DispatchResult dataclass
  - dispatch_item() routing, threshold logic, error handling
  - _build_item_data() base fields and enrichment dispatch
  - All 5 entity fetchers (charge_entry, coding_session, claim, denial, payment_batch)
  - _ITEM_TYPE_FETCHERS registration
  - dispatch_pending_ai_items() fan-out guard (ai_agent_enabled=False)
  - dispatch_work_item_to_ai() guard (ai_agent_enabled=False)
"""

from __future__ import annotations

import os
import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# ── Env stubs (must precede src imports) ────────────────────────────────────
os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine in the default event loop (test helper)."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_item(
    *,
    queue_type: str = "coding",
    item_type: str = "charge_entry",
    item_id: str | None = None,
    status: str = "pending",
    priority: int = 5,
    sla_breached: bool = False,
    notes: str = "",
    practice_id: str | None = None,
    assigned_to: str | None = None,
    due_date=None,
) -> Mock:
    """Build a lightweight mock WorkQueueItem."""
    item = Mock()
    item.id = uuid.uuid4()
    item.queue_type = queue_type
    item.item_type = item_type
    item.item_id = item_id or uuid.uuid4()
    item.status = status
    item.priority = priority
    item.sla_breached = sla_breached
    item.notes = notes
    item.practice_id = practice_id
    item.assigned_to = assigned_to
    item.due_date = due_date
    item.started_at = None
    item.updated_at = None
    item.completed_at = None
    return item


# ===========================================================================
# 1.  QUEUE_TYPE_TO_AGENT
# ===========================================================================

class TestQueueTypeToAgent:
    """Validate every entry in the mapping dictionary."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from src.core.ai_dispatch.dispatcher import QUEUE_TYPE_TO_AGENT, AGENT_TYPE_LABEL
        self.mapping = QUEUE_TYPE_TO_AGENT
        self.labels = AGENT_TYPE_LABEL

    # --- canonical types -------------------------------------------------------

    def test_coding_maps_to_coding(self):
        assert self.mapping["coding"] == "coding"

    def test_billing_maps_to_billing(self):
        assert self.mapping["billing"] == "billing"

    def test_posting_maps_to_payment_posting(self):
        assert self.mapping["posting"] == "payment_posting"

    def test_denial_maps_to_ar_denial(self):
        assert self.mapping["denial"] == "ar_denial"

    def test_follow_up_maps_to_ar_denial(self):
        assert self.mapping["follow_up"] == "ar_denial"

    def test_prior_auth_maps_to_prior_auth(self):
        assert self.mapping["prior_auth"] == "prior_auth"

    def test_eligibility_maps_to_eligibility(self):
        assert self.mapping["eligibility"] == "eligibility"

    def test_patient_intake_maps_to_patient_intake(self):
        assert self.mapping["patient_intake"] == "patient_intake"

    # --- aliases ---------------------------------------------------------------

    def test_intake_alias_maps_to_patient_intake_not_coding(self):
        """Regression: 'intake' was wrongly mapped to 'coding' before the fix."""
        assert self.mapping["intake"] == "patient_intake"
        assert self.mapping["intake"] != "coding"

    def test_authorization_alias_maps_to_prior_auth(self):
        assert self.mapping["authorization"] == "prior_auth"

    def test_verification_alias_maps_to_eligibility(self):
        assert self.mapping["verification"] == "eligibility"

    # --- structural ------------------------------------------------------------

    def test_all_values_are_known_agent_types(self):
        known = {"coding", "billing", "payment_posting", "ar_denial",
                 "prior_auth", "eligibility", "patient_intake"}
        for k, v in self.mapping.items():
            assert v in known, f"queue_type='{k}' maps to unknown agent '{v}'"

    def test_no_unknown_agent_types_in_labels(self):
        """Every label key must be a valid agent type value."""
        agent_values = set(self.mapping.values())
        for agent_type in self.labels:
            assert agent_type in agent_values, \
                f"AGENT_TYPE_LABEL has key '{agent_type}' not in QUEUE_TYPE_TO_AGENT values"

    def test_all_agent_type_values_have_labels(self):
        """Every distinct agent type used in the mapping has a human-readable label."""
        for agent_type in set(self.mapping.values()):
            assert agent_type in self.labels, \
                f"Agent type '{agent_type}' missing from AGENT_TYPE_LABEL"


# ===========================================================================
# 2.  DISPATCHABLE_QUEUE_TYPES
# ===========================================================================

class TestDispatchableQueueTypes:
    """All 11 queue types are present; set is consistent with dispatcher mapping."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from src.core.ai_dispatch.tasks import DISPATCHABLE_QUEUE_TYPES
        from src.core.ai_dispatch.dispatcher import QUEUE_TYPE_TO_AGENT
        self.dqt = DISPATCHABLE_QUEUE_TYPES
        self.mapping = QUEUE_TYPE_TO_AGENT

    def test_is_frozenset(self):
        assert isinstance(self.dqt, frozenset)

    def test_contains_all_11_types(self):
        expected = {
            "coding", "billing", "posting", "denial", "follow_up",
            "intake", "prior_auth", "authorization", "eligibility",
            "verification", "patient_intake",
        }
        assert self.dqt == expected

    def test_every_dispatchable_type_has_agent_mapping(self):
        for qt in self.dqt:
            assert qt in self.mapping, \
                f"Dispatchable queue_type '{qt}' has no entry in QUEUE_TYPE_TO_AGENT"

    def test_immutable(self):
        with pytest.raises(AttributeError):
            self.dqt.add("new_type")  # type: ignore[attr-defined]


# ===========================================================================
# 3.  DispatchResult dataclass
# ===========================================================================

class TestDispatchResult:

    @pytest.fixture(autouse=True)
    def _import(self):
        from src.core.ai_dispatch.dispatcher import DispatchResult
        self.DR = DispatchResult

    def test_required_fields(self):
        dr = self.DR(success=True, confidence=0.9, escalate=False, agent_type="coding")
        assert dr.success is True
        assert dr.confidence == 0.9
        assert dr.escalate is False
        assert dr.agent_type == "coding"

    def test_default_fields(self):
        dr = self.DR(success=True, confidence=0.8, escalate=False, agent_type="billing")
        assert dr.result == {}
        assert dr.notes == ""
        assert dr.error == ""

    def test_optional_fields_set(self):
        dr = self.DR(
            success=False, confidence=0.3, escalate=True,
            agent_type="ar_denial",
            result={"action": "appeal"},
            notes="Low confidence",
            error="Timeout",
        )
        assert dr.result == {"action": "appeal"}
        assert dr.notes == "Low confidence"
        assert dr.error == "Timeout"


# ===========================================================================
# 4.  dispatch_item() — routing and threshold logic
# ===========================================================================

class TestDispatchItemRouting:
    """Tests for the async dispatch_item() function."""

    # --- unknown queue type ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_unknown_queue_type_escalates(self):
        from src.core.ai_dispatch.dispatcher import dispatch_item
        result = await dispatch_item("nonexistent_type", {"id": "x"})
        assert result.success is False
        assert result.escalate is True
        assert result.agent_type == "unknown"
        assert "nonexistent_type" in result.notes

    # --- agent service call ----------------------------------------------------

    @pytest.mark.asyncio
    async def test_successful_dispatch_high_confidence(self):
        """High-confidence agent response → not escalated."""
        from src.core.ai_dispatch.dispatcher import dispatch_item

        mock_response = {
            "success": True,
            "confidence": 0.95,
            "escalate": False,
            "result": {"cpt_codes": ["99213"]},
            "notes": "codes assigned",
        }
        with patch(
            "src.core.ai_dispatch.dispatcher.call_agent_service",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await dispatch_item("coding", {"id": "abc"})

        assert result.success is True
        assert result.confidence == 0.95
        assert result.escalate is False
        assert result.agent_type == "coding"
        assert result.result == {"cpt_codes": ["99213"]}

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_escalation(self):
        """Confidence below threshold (0.7) → escalate regardless of agent flag."""
        from src.core.ai_dispatch.dispatcher import dispatch_item

        mock_response = {
            "success": True,
            "confidence": 0.50,
            "escalate": False,
            "result": {},
            "notes": "",
        }
        with patch(
            "src.core.ai_dispatch.dispatcher.call_agent_service",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await dispatch_item("billing", {"id": "xyz"})

        assert result.escalate is True
        assert result.confidence == 0.50

    @pytest.mark.asyncio
    async def test_agent_requested_escalation_honoured(self):
        """Agent sets escalate=True even with high confidence → still escalated."""
        from src.core.ai_dispatch.dispatcher import dispatch_item

        mock_response = {
            "success": True,
            "confidence": 0.88,
            "escalate": True,
            "result": {},
            "notes": "ambiguous clinical context",
        }
        with patch(
            "src.core.ai_dispatch.dispatcher.call_agent_service",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await dispatch_item("denial", {"id": "d1"})

        assert result.escalate is True

    @pytest.mark.asyncio
    async def test_agent_service_exception_returns_escalated_result(self):
        """Transport failure → success=False, escalate=True, error populated."""
        from src.core.ai_dispatch.dispatcher import dispatch_item

        with patch(
            "src.core.ai_dispatch.dispatcher.call_agent_service",
            new_callable=AsyncMock,
            side_effect=ConnectionError("service unreachable"),
        ):
            result = await dispatch_item("posting", {"id": "p1"})

        assert result.success is False
        assert result.escalate is True
        assert "service unreachable" in result.error

    # --- all 11 queue types route to a known agent ----------------------------

    @pytest.mark.asyncio
    @pytest.mark.parametrize("queue_type", [
        "coding", "billing", "posting", "denial", "follow_up",
        "intake", "prior_auth", "authorization",
        "eligibility", "verification", "patient_intake",
    ])
    async def test_all_dispatchable_types_reach_an_agent(self, queue_type):
        from src.core.ai_dispatch.dispatcher import dispatch_item, QUEUE_TYPE_TO_AGENT

        mock_response = {"success": True, "confidence": 0.9, "escalate": False}
        with patch(
            "src.core.ai_dispatch.dispatcher.call_agent_service",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await dispatch_item(queue_type, {"id": "t1"})

        expected_agent = QUEUE_TYPE_TO_AGENT[queue_type]
        assert result.agent_type == expected_agent


# ===========================================================================
# 5.  _build_item_data() — base fields + fetcher dispatch
# ===========================================================================

class TestBuildItemData:
    """Tests for the async _build_item_data() helper."""

    @pytest.mark.asyncio
    async def test_base_fields_present(self):
        from src.core.ai_dispatch.tasks import _build_item_data

        item = _make_item(queue_type="billing", item_type="claim")
        # Patch the fetcher to return nothing (focus on base fields only)
        with patch(
            "src.core.ai_dispatch.tasks._ITEM_TYPE_FETCHERS",
            new={}
        ):
            db = AsyncMock()
            data = await _build_item_data(db, item)

        assert data["id"] == str(item.id)
        assert data["queue_type"] == "billing"
        assert data["item_type"] == "claim"
        assert data["priority"] == 5
        assert data["sla_breached"] is False
        assert "notes" in data

    @pytest.mark.asyncio
    async def test_fetcher_enrichment_merged(self):
        """When a matching fetcher exists, its output is merged into base."""
        from src.core.ai_dispatch.tasks import _build_item_data

        item = _make_item(queue_type="coding", item_type="charge_entry")
        fetcher_mock = AsyncMock(return_value={"charge_entry_id": "ce-123", "diagnosis_codes": ["J18.9"]})

        with patch(
            "src.core.ai_dispatch.tasks._ITEM_TYPE_FETCHERS",
            new={"charge_entry": fetcher_mock},
        ):
            db = AsyncMock()
            data = await _build_item_data(db, item)

        assert data["charge_entry_id"] == "ce-123"
        assert data["diagnosis_codes"] == ["J18.9"]
        assert data["queue_type"] == "coding"  # base still present

    @pytest.mark.asyncio
    async def test_missing_fetcher_graceful(self):
        """Unknown item_type → no enrichment, but base fields still returned."""
        from src.core.ai_dispatch.tasks import _build_item_data

        item = _make_item(queue_type="billing", item_type="unknown_entity")
        db = AsyncMock()
        data = await _build_item_data(db, item)

        assert data["id"] == str(item.id)
        assert "unknown_field" not in data

    @pytest.mark.asyncio
    async def test_fetcher_exception_does_not_raise(self):
        """If enrichment fetcher throws, _build_item_data returns base gracefully."""
        from src.core.ai_dispatch.tasks import _build_item_data

        item = _make_item(queue_type="denial", item_type="denial")
        fetcher_mock = AsyncMock(side_effect=RuntimeError("db dead"))

        with patch(
            "src.core.ai_dispatch.tasks._ITEM_TYPE_FETCHERS",
            new={"denial": fetcher_mock},
        ):
            db = AsyncMock()
            data = await _build_item_data(db, item)  # must not raise

        assert data["id"] == str(item.id)

    @pytest.mark.asyncio
    async def test_no_item_id_skips_fetcher(self):
        """item_id=None → fetcher not called."""
        from src.core.ai_dispatch.tasks import _build_item_data

        item = _make_item(queue_type="billing", item_type="claim", item_id=None)
        item.item_id = None
        fetcher_mock = AsyncMock(return_value={"claim_id": "c-1"})

        with patch(
            "src.core.ai_dispatch.tasks._ITEM_TYPE_FETCHERS",
            new={"claim": fetcher_mock},
        ):
            db = AsyncMock()
            await _build_item_data(db, item)

        fetcher_mock.assert_not_awaited()


# ===========================================================================
# 6.  Individual entity fetchers
# ===========================================================================

def _make_async_result(value):
    """Return an AsyncMock that yields a scalar result."""
    r = AsyncMock()
    r.scalar_one_or_none = MagicMock(return_value=value)
    r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    r.fetchall = MagicMock(return_value=[])
    return r


def _make_db(results: list):
    """db.execute() yields successive results from the list."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=results)
    return db


class TestFetchChargeEntryData:

    @pytest.mark.asyncio
    async def test_returns_empty_when_not_found(self):
        from src.core.ai_dispatch.tasks import _fetch_charge_entry_data
        db = _make_db([_make_async_result(None)])
        result = await _fetch_charge_entry_data(db, str(uuid.uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_charge_fields(self):
        from src.core.ai_dispatch.tasks import _fetch_charge_entry_data

        charge = Mock()
        charge.id = uuid.uuid4()
        charge.patient_id = uuid.uuid4()
        charge.primary_payer_id = uuid.uuid4()
        charge.service_date = None
        charge.rendering_provider_id = None
        charge.diagnosis_codes = ["Z00.00"]
        charge.procedure_codes = {"99213": 1}
        charge.clinical_notes = "Annual wellness"
        charge.member_id = "MBR001"
        charge.authorization_number = "AUTH999"

        patient = Mock()
        patient.date_of_birth = None

        payer = Mock()
        payer.payer_name = "BlueCross"

        db = _make_db([
            _make_async_result(charge),
            _make_async_result(patient),
            _make_async_result(payer),
        ])

        result = await _fetch_charge_entry_data(db, str(charge.id))

        assert result["charge_entry_id"] == str(charge.id)
        assert result["diagnosis_codes"] == ["Z00.00"]
        assert result["member_id"] == "MBR001"
        assert result["payer_name"] == "BlueCross"


class TestFetchCodingSessionData:

    @pytest.mark.asyncio
    async def test_returns_empty_when_not_found(self):
        from src.core.ai_dispatch.tasks import _fetch_coding_session_data
        db = _make_db([_make_async_result(None)])
        result = await _fetch_coding_session_data(db, str(uuid.uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_session_fields(self):
        from src.core.ai_dispatch.tasks import _fetch_coding_session_data

        session = Mock()
        session.id = uuid.uuid4()
        session.encounter_id = uuid.uuid4()
        session.suggested_codes = ["99213"]
        session.final_codes = ["99213"]
        session.nlp_extraction = {"entities": []}
        session.ai_model_version = "claude-3-5-sonnet"

        encounter = Mock()
        encounter.id = uuid.uuid4()
        encounter.encounter_type = "outpatient"
        encounter.encounter_date = None
        encounter.provider_id = None
        encounter.notes = "Routine visit"
        encounter.prior_auth_number = ""

        db = _make_db([
            _make_async_result(session),
            _make_async_result(encounter),
        ])

        result = await _fetch_coding_session_data(db, str(session.id))

        assert result["coding_session_id"] == str(session.id)
        assert result["suggested_codes"] == ["99213"]
        assert result["encounter_type"] == "outpatient"

    @pytest.mark.asyncio
    async def test_no_encounter_still_returns_session(self):
        from src.core.ai_dispatch.tasks import _fetch_coding_session_data

        session = Mock()
        session.id = uuid.uuid4()
        session.encounter_id = None
        session.suggested_codes = []
        session.final_codes = []
        session.nlp_extraction = {}
        session.ai_model_version = ""

        db = _make_db([_make_async_result(session)])

        result = await _fetch_coding_session_data(db, str(session.id))

        assert result["coding_session_id"] == str(session.id)
        assert "encounter_type" not in result


class TestFetchClaimData:

    @pytest.mark.asyncio
    async def test_returns_empty_when_not_found(self):
        from src.core.ai_dispatch.tasks import _fetch_claim_data
        db = _make_db([_make_async_result(None)])
        result = await _fetch_claim_data(db, str(uuid.uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_claim_fields_with_lines_and_diagnoses(self):
        from src.core.ai_dispatch.tasks import _fetch_claim_data

        claim = Mock()
        claim.id = uuid.uuid4()
        claim.claim_number = "CLM-2024-001"
        claim.status = "submitted"
        claim.total_charge = 250.00
        claim.payer_id = uuid.uuid4()
        claim.coverage_id = None

        payer = Mock()
        payer.payer_name = "Aetna"

        line1 = Mock()
        line1.cpt_code = "99213"
        line1.modifiers = []
        line1.icd_pointers = [1]
        line1.charge_amount = 150.00

        dx1 = Mock()
        dx1.icd10_code = "J06.9"
        dx1.sequence_number = 1
        dx1.is_principal = True

        # db.execute calls: claim, lines, diagnoses, payer
        lines_result = AsyncMock()
        lines_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[line1])))

        dx_result = AsyncMock()
        dx_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[dx1])))

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _make_async_result(claim),
            lines_result,
            dx_result,
            _make_async_result(payer),
        ])

        result = await _fetch_claim_data(db, str(claim.id))

        assert result["claim_id"] == str(claim.id)
        assert result["claim_number"] == "CLM-2024-001"
        assert result["payer_name"] == "Aetna"
        assert len(result["claim_lines"]) == 1
        assert result["claim_lines"][0]["cpt_code"] == "99213"
        assert len(result["diagnoses"]) == 1
        assert result["diagnoses"][0]["icd10_code"] == "J06.9"


class TestFetchDenialData:

    @pytest.mark.asyncio
    async def test_returns_empty_when_not_found(self):
        from src.core.ai_dispatch.tasks import _fetch_denial_data
        db = _make_db([_make_async_result(None)])
        result = await _fetch_denial_data(db, str(uuid.uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_denial_fields(self):
        from src.core.ai_dispatch.tasks import _fetch_denial_data

        denial = Mock()
        denial.id = uuid.uuid4()
        denial.reason_code = "CO-4"
        denial.remark_codes = ["N362"]
        denial.denial_amount = 120.00
        denial.category = "coverage"
        denial.root_cause = "pre-auth missing"
        denial.appeal_deadline = None
        denial.payer_id = uuid.uuid4()

        payer = Mock()
        payer.payer_name = "UnitedHealth"

        db = _make_db([
            _make_async_result(denial),
            _make_async_result(payer),
        ])

        result = await _fetch_denial_data(db, str(denial.id))

        assert result["denial_id"] == str(denial.id)
        assert result["reason_code"] == "CO-4"
        assert result["remark_codes"] == ["N362"]
        assert result["payer_name"] == "UnitedHealth"
        assert result["root_cause"] == "pre-auth missing"


class TestFetchPaymentBatchData:

    @pytest.mark.asyncio
    async def test_returns_empty_when_not_found(self):
        from src.core.ai_dispatch.tasks import _fetch_payment_batch_data
        db = _make_db([_make_async_result(None)])
        result = await _fetch_payment_batch_data(db, str(uuid.uuid4()))
        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_batch_fields(self):
        from src.core.ai_dispatch.tasks import _fetch_payment_batch_data

        batch = Mock(spec=["id", "payment_date", "total_payment", "check_number", "payer_id", "era_835_data"])
        batch.id = uuid.uuid4()
        batch.payment_date = None
        batch.total_payment = 5000.00
        batch.check_number = "CHK-00123"
        batch.payer_id = uuid.uuid4()
        batch.era_835_data = {"clm01": "A12345"}

        db = _make_db([_make_async_result(batch)])

        result = await _fetch_payment_batch_data(db, str(batch.id))

        assert result["payment_batch_id"] == str(batch.id)
        assert result["total_payment"] == 5000.00
        assert result["check_number"] == "CHK-00123"
        assert result["era_835_data"] == {"clm01": "A12345"}


# ===========================================================================
# 7.  _ITEM_TYPE_FETCHERS registration
# ===========================================================================

class TestItemTypeFetchers:

    @pytest.fixture(autouse=True)
    def _import(self):
        from src.core.ai_dispatch.tasks import _ITEM_TYPE_FETCHERS
        self.fetchers = _ITEM_TYPE_FETCHERS

    def test_all_five_fetchers_registered(self):
        expected = {
            "charge_entry", "coding_session", "claim", "denial", "payment_batch"
        }
        assert set(self.fetchers.keys()) == expected

    def test_fetchers_are_callable(self):
        for name, fn in self.fetchers.items():
            assert callable(fn), f"Fetcher '{name}' is not callable"

    def test_fetchers_are_coroutine_functions(self):
        import asyncio
        for name, fn in self.fetchers.items():
            assert asyncio.iscoroutinefunction(fn), \
                f"Fetcher '{name}' is not an async function"


# ===========================================================================
# 8.  Fan-out task guard (ai_agent_enabled=False)
# ===========================================================================

class TestFanOutGuard:

    def test_dispatch_pending_skipped_when_disabled(self):
        """When ai_agent_enabled=False, fan-out returns {dispatched:0} immediately."""
        from src.core.ai_dispatch.tasks import dispatch_pending_ai_items

        with patch("src.core.ai_dispatch.tasks.settings") as mock_settings:
            mock_settings.ai_agent_enabled = False
            result = dispatch_pending_ai_items()

        assert result == {"dispatched": 0}

    def test_dispatch_single_item_skipped_when_disabled(self):
        """When ai_agent_enabled=False, single-item task returns skipped=True."""
        from src.core.ai_dispatch.tasks import dispatch_work_item_to_ai

        with patch("src.core.ai_dispatch.tasks.settings") as mock_settings:
            mock_settings.ai_agent_enabled = False
            result = dispatch_work_item_to_ai(str(uuid.uuid4()))

        assert result["skipped"] is True


# ===========================================================================
# 9.  Consistency: DISPATCHABLE_QUEUE_TYPES ↔ QUEUE_TYPE_TO_AGENT
# ===========================================================================

class TestCrossModuleConsistency:
    """Ensure tasks.py and dispatcher.py stay in sync."""

    def test_all_dispatchable_types_have_agent_mappings(self):
        from src.core.ai_dispatch.tasks import DISPATCHABLE_QUEUE_TYPES
        from src.core.ai_dispatch.dispatcher import QUEUE_TYPE_TO_AGENT

        for qt in DISPATCHABLE_QUEUE_TYPES:
            assert qt in QUEUE_TYPE_TO_AGENT, \
                f"DISPATCHABLE_QUEUE_TYPES contains '{qt}' but QUEUE_TYPE_TO_AGENT does not"

    def test_dispatcher_keys_are_subset_of_dispatchable(self):
        from src.core.ai_dispatch.tasks import DISPATCHABLE_QUEUE_TYPES
        from src.core.ai_dispatch.dispatcher import QUEUE_TYPE_TO_AGENT

        for qt in QUEUE_TYPE_TO_AGENT:
            assert qt in DISPATCHABLE_QUEUE_TYPES, \
                f"QUEUE_TYPE_TO_AGENT has '{qt}' not in DISPATCHABLE_QUEUE_TYPES"
