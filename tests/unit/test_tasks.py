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
    def test_beat_schedule_has_six_tasks(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert len(schedule) == 6

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

    def test_sla_breaches_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "check-sla-breaches" in schedule
        assert schedule["check-sla-breaches"]["task"] == "src.core.queues.tasks.check_sla_breaches"
        assert schedule["check-sla-breaches"]["schedule"] == 1800.0

    def test_auto_assign_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "auto-assign-queue-items" in schedule
        assert schedule["auto-assign-queue-items"]["task"] == "src.core.queues.tasks.auto_assign_pending_items"
        assert schedule["auto-assign-queue-items"]["schedule"] == 600.0

    def test_overdue_invoices_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "mark-overdue-invoices" in schedule
        assert schedule["mark-overdue-invoices"]["task"] == "src.core.client_billing.tasks.mark_overdue_invoices"
        assert schedule["mark-overdue-invoices"]["schedule"] == 86400.0

    def test_denial_patterns_task(self):
        from src.infrastructure.queue.celery_app import celery_app
        schedule = celery_app.conf.beat_schedule
        assert "denial-pattern-analysis" in schedule
        assert schedule["denial-pattern-analysis"]["task"] == "src.core.denials.tasks.analyze_denial_patterns"
        assert schedule["denial-pattern-analysis"]["schedule"] == 604800.0


# ── Task Routes Configuration Tests ────────────────────────────────────


class TestTaskRoutes:
    def test_coding_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.coding.tasks.*" in routes
        assert routes["src.core.coding.tasks.*"]["queue"] == "coding"

    def test_billing_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.billing.tasks.*" in routes
        assert routes["src.core.billing.tasks.*"]["queue"] == "billing"

    def test_payments_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.payments.tasks.*" in routes
        assert routes["src.core.payments.tasks.*"]["queue"] == "payments"

    def test_denials_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.denials.tasks.*" in routes
        assert routes["src.core.denials.tasks.*"]["queue"] == "denials"

    def test_queues_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.core.queues.tasks.*" in routes

    def test_edi_queue_routing(self):
        from src.infrastructure.queue.celery_app import celery_app
        routes = celery_app.conf.task_routes
        assert "src.services.edi.tasks.*" in routes
        assert routes["src.services.edi.tasks.*"]["queue"] == "edi"


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

    def test_queues_tasks_import(self):
        from src.core.queues.tasks import check_sla_breaches, auto_assign_pending_items
        assert callable(check_sla_breaches)
        assert callable(auto_assign_pending_items)

    def test_coding_tasks_import(self):
        from src.core.coding.tasks import process_coding_session, batch_process_coding_sessions
        assert callable(process_coding_session)
        assert callable(batch_process_coding_sessions)

    def test_client_billing_tasks_import(self):
        from src.core.client_billing.tasks import mark_overdue_invoices, generate_monthly_invoices
        assert callable(mark_overdue_invoices)
        assert callable(generate_monthly_invoices)

    def test_edi_tasks_import(self):
        from src.services.edi.tasks import generate_edi_837, submit_claim_batch
        assert callable(generate_edi_837)
        assert callable(submit_claim_batch)

    def test_tasks_router_import(self):
        from src.api.routes.tasks import router
        assert router is not None