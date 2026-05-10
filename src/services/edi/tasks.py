"""Background tasks for EDI processing — 837 generation and batch submission."""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_edi_837(self, claim_id: str):
    """Generate an EDI 837 file for a claim.

    Args:
        claim_id: UUID of the Claim to generate EDI for.
    """
    import structlog

    logger = structlog.get_logger("edi.tasks")
    logger.info("edi_837_generation_started", claim_id=claim_id)

    # Placeholder: EDI generation is handled by the billing service synchronously.
    # This task exists for future async processing of large batch submissions.
    logger.info("edi_837_generation_complete", claim_id=claim_id)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def submit_claim_batch(self, practice_id: str):
    """Submit all ready claims for a practice to the clearinghouse.

    Args:
        practice_id: UUID of the practice whose claims should be submitted.
    """
    import structlog

    logger = structlog.get_logger("edi.tasks")
    logger.info("claim_batch_submission_started", practice_id=practice_id)

    # Placeholder: batch submission is handled by BillingService.batch_submit.
    # This task exists for future async processing of large batches.
    logger.info("claim_batch_submission_complete", practice_id=practice_id)