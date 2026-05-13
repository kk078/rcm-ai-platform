"""Tests for background tasks: Celery app configuration, beat schedule,
task registration, and task module imports."""

import os
import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")


# ── Celery App Configuration Tests ─────────────────────────────────────


class TestCeleryAppConfiguration:
    def test_celery_app_exists(self):
        from src.infrastructure.queue.celery_app import celery_app
        assert celery_app is not None
        assert celery_app.main == "medclaim"

    def test_celery_serializer_is_json(self):
        from src.infrastructure.queue.celery_app import celery_app
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.result_serializer == "json"

    def test_celery_time_limits(self):
        from src.infrastructure.queue.celery_app import celery_app
        assert celery_app.conf.task_time_limit == 600  # 10 min
        assert celery_app.conf.task_soft_time_limit == 300  # 5 min

    def test_celery_track_started(self):
        from src.infrastructure.queue.celery_app import celery_app
        assert celery_app.conf.task_track_started is True

    def test_celery_acks_late(self):
        from src.infrastructure.queue.celery_app import celery_app
        assert celery_app.conf.task_acks_late is True

    def test_celery_retry_config(self):
        from src.infrastructure.queue.celery_app import celery_app
        assert celery_app.conf.task_default_retry_delay == 60
        assert celery_app.conf.task_max_retries == 3


# ── Beat Schedule Tests ────────────────────────────────────────────────


class TestBeatSchedule:
    def test_beat_schedule_has_tasks(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert len(schedule) >= 4

    def test_appeal_deadlines_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "check-appeal-deadlines" in schedule
        assert schedule["check-appeal-deadlines"]["task"] == "src.core.denials.tasks.check_appeal_deadlines"
        assert schedule["check-appeal-deadlines"]["schedule"] == 3600.0

    def test_timely_filing_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "check-timely-filing" in schedule
        assert schedule["check-timely-filing"]["task"] == "src.core.billing.tasks.check_timely_filing_deadlines"
        assert schedule["check-timely-filing"]["schedule"] == 86400.0

    def test_denial_patterns_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "denial-pattern-analysis" in schedule
        assert schedule["denial-pattern-analysis"]["task"] == "src.core.denials.tasks.analyze_denial_patterns"
        assert schedule["denial-pattern-analysis"]["schedule"] == 604800.0

    def test_generate_reconciliation_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "generate-reconciliation" in schedule
        assert schedule["generate-reconciliation"]["task"] == "src.core.payments.tasks.daily_reconciliation"
        assert schedule["generate-reconciliation"]["schedule"] == 86400.0


# ── Task Routes Configuration Tests ────────────────────────────────────


class TestTaskRoutes:
    def test_coding_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.coding.*" in routes
        assert routes["src.core.coding.*"]["queue"] == "coding"

    def test_billing_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.billing.*" in routes
        assert routes["src.core.billing.*"]["queue"] == "billing"

    def test_payments_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.payments.*" in routes
        assert routes["src.core.payments.*"]["queue"] == "payments"

    def test_denials_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.denials.*" in routes
        assert routes["src.core.denials.*"]["queue"] == "denials"

    def test_edi_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.services.edi.*" in routes
        assert routes["src.services.edi.*"]["queue"] == "edi"


# ── Task Module Import Tests ────────────────────────────────────────────


class TestTaskModuleImports:
    def test_billing_tasks_import(self):
        from src.core.billing.tasks import check_timely_filing_deadlines
        assert callable(check_timely_filing_deadlines)

    def test_denials_tasks_import(self):
        from src.core.denials.tasks import check_appeal_deadlines, analyze_denial_patterns
        assert callable(check_appeal_deadlines)
        assert callable(analyze_denial_patterns)

    def test_payments_tasks_import(self):
        from src.core.payments.tasks import process_era_file, daily_reconciliation
        assert callable(process_era_file)
        assert callable(daily_reconciliation)

    def test_edi_tasks_import(self):
        from src.services.edi.tasks import generate_edi_837, submit_claim_batch
        assert callable(generate_edi_837)
        assert callable(submit_claim_batch)

    def test_tasks_router_import(self):
        from src.api.routes.tasks import router
        assert router is not None