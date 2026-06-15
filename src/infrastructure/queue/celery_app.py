"""
Celery configuration for background task processing.
Separate queues for each domain to enable independent scaling.
"""

from celery import Celery
from celery.schedules import crontab
from src.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aethera",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,       # 10 min hard limit
    task_soft_time_limit=300,  # 5 min soft limit
    worker_prefetch_multiplier=1,
    task_acks_late=True,

    # Route tasks to dedicated queues for independent scaling
    task_routes={
        "src.core.coding.*": {"queue": "coding"},
        "src.core.billing.*": {"queue": "billing"},
        "src.core.payments.*": {"queue": "payments"},
        "src.core.denials.*": {"queue": "denials"},
        "src.services.edi.*": {"queue": "edi"},
        "src.core.ai_dispatch.*": {"queue": "ai_dispatch"},
    },

    # Retry configuration
    task_default_retry_delay=60,
    task_max_retries=3,

    # Beat schedule for periodic tasks
    beat_schedule={
        "check-appeal-deadlines": {
            "task": "src.core.denials.tasks.check_appeal_deadlines",
            "schedule": 3600.0,  # Every hour
        },
        "check-timely-filing": {
            "task": "src.core.billing.tasks.check_timely_filing_deadlines",
            "schedule": 86400.0,  # Daily
        },
        "generate-reconciliation": {
            "task": "src.core.payments.tasks.daily_reconciliation",
            "schedule": 86400.0,  # Daily
        },
        "denial-pattern-analysis": {
            "task": "src.core.denials.tasks.analyze_denial_patterns",
            "schedule": 604800.0,  # Weekly
        },
        "sftp-file-watcher": {
            "task": "src.core.ehr_integration.tasks.sftp_file_watcher",
            "schedule": crontab(minute="*/15"),  # every 15 minutes
        },
        "fhir-sync-all-practices": {
            "task": "src.core.ehr_integration.tasks.sync_fhir_all_practices",
            "schedule": crontab(hour="*/6"),  # every 6 hours
        },
        "auto-close-resolved-denials": {
            "task": "src.core.ehr_integration.tasks.auto_close_resolved_denials",
            "schedule": crontab(minute="*/30"),  # every 30 minutes
        },
        "generate-patient-statements": {
            "task": "src.core.ehr_integration.tasks.generate_patient_statements",
            "schedule": crontab(hour="3", minute="0"),  # daily at 3am
        },
        "sla-breach-notifications": {
            "task": "src.core.notifications.tasks.send_sla_breach_notifications",
            "schedule": crontab(minute="*/30"),  # every 30 minutes
        },
        "denial-deadline-alerts": {
            "task": "src.core.notifications.tasks.send_denial_deadline_alerts",
            "schedule": crontab(hour="8", minute="0"),  # daily at 8am
        },
        "dispatch-pending-ai-items": {
            "task": "src.core.ai_dispatch.tasks.dispatch_pending_ai_items",
            "schedule": 300.0,  # Every 5 minutes
        },
        "triage-open-ar": {
            "task": "src.core.ar_intake.tasks.triage_open_ar",
            "schedule": 600.0,  # Every 10 minutes — throttled AI AR follow-up triage
        },
    },
)

celery_app.autodiscover_tasks([
    "src.core.coding",
    "src.core.billing",
    "src.core.payments",
    "src.core.denials",
    "src.core.queues",
    "src.core.client_billing",
    "src.core.ehr_integration",
    "src.core.notifications",
    "src.services.edi",
    "src.core.error_intelligence",  # AI auto-debugging
    "src.core.ai_dispatch",         # Autonomous AI queue processing
    "src.core.document_intake",     # Background upload ingestion (OCR + classify)
    "src.core.ar_intake",           # AI triage of imported open AR
])
