"""
Celery configuration for background task processing.
Separate queues for each domain to enable independent scaling.
"""

from celery import Celery
from src.config import get_settings

settings = get_settings()

celery_app = Celery(
    "medclaim",
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
        "src.core.payment_posting.*": {"queue": "payments"},
        "src.core.denial_management.*": {"queue": "denials"},
        "src.services.edi.*": {"queue": "edi"},
    },

    # Retry configuration
    task_default_retry_delay=60,
    task_max_retries=3,

    # Beat schedule for periodic tasks
    beat_schedule={
        "check-appeal-deadlines": {
            "task": "src.core.denial_management.tasks.check_appeal_deadlines",
            "schedule": 3600.0,  # Every hour
        },
        "check-timely-filing": {
            "task": "src.core.billing.tasks.check_timely_filing_deadlines",
            "schedule": 86400.0,  # Daily
        },
        "sync-payer-policies": {
            "task": "src.services.payer_intelligence.tasks.sync_policies",
            "schedule": 86400.0,  # Daily
        },
        "generate-reconciliation": {
            "task": "src.core.payment_posting.tasks.daily_reconciliation",
            "schedule": 86400.0,  # Daily
        },
        "denial-pattern-analysis": {
            "task": "src.core.denial_management.tasks.analyze_patterns",
            "schedule": 604800.0,  # Weekly
        },
    },
)

celery_app.autodiscover_tasks([
    "src.core.coding",
    "src.core.billing",
    "src.core.payment_posting",
    "src.core.denial_management",
    "src.services.edi",
    "src.services.payer_intelligence",
])
