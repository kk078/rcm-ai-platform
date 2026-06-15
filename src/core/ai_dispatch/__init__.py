"""
AI Dispatch module — autonomous work-queue processing via Python agent service.

Exports the public interface used by Celery tasks and the queue layer.
"""

from .dispatcher import DispatchResult, dispatch_item, QUEUE_TYPE_TO_AGENT

__all__ = ["DispatchResult", "dispatch_item", "QUEUE_TYPE_TO_AGENT"]
