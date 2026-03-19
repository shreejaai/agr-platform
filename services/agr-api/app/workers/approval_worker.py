"""Temporal worker for AGR approval workflows.

Run as a standalone process alongside the FastAPI app:
    python -m app.workers.approval_worker

Requires TEMPORAL_HOST (and optionally TEMPORAL_NAMESPACE) to be set.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Allow running as `python -m app.workers.approval_worker` from the service root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import settings
from app.workflows.approval_workflow import ApprovalWorkflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TASK_QUEUE = "agr-approvals"


async def main() -> None:
    if not settings.temporal_host:
        logger.error("TEMPORAL_HOST is not set. Exiting.")
        sys.exit(1)

    logger.info("Connecting to Temporal at %s (namespace=%s)", settings.temporal_host, settings.temporal_namespace)
    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)

    logger.info("Starting AGR approval worker on task queue '%s'", TASK_QUEUE)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ApprovalWorkflow],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
