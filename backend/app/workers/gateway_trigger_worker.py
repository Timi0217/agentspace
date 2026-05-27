"""
Gateway Trigger Worker

Handles scheduled trigger execution based on cron patterns.
Also handles event-based and manual triggers.
"""

import asyncio
import logging
from datetime import datetime
from croniter import croniter
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.gateway_models import Trigger, TriggerType
from app.gateway_services import TriggerService

logger = logging.getLogger(__name__)


class TriggerWorker:
    """
    Worker that executes scheduled triggers.

    Flow:
    1. Load all active triggers
    2. For each scheduled trigger, check if it's time to execute
    3. If time matches cron pattern, execute the trigger
    4. Create room with target agents
    5. Send initial message from initiator agent
    6. Log execution in TriggerExecution table
    """

    def __init__(self, db: Session = None, poll_interval: int = 60):
        self.db = db or SessionLocal()
        self.poll_interval = poll_interval  # Check every minute

    async def start(self):
        """Start the trigger worker loop."""
        logger.info("Starting TriggerWorker")

        while True:
            try:
                await self.check_triggers()
            except Exception as e:
                logger.error(f"Error in trigger worker: {e}", exc_info=True)

            await asyncio.sleep(self.poll_interval)

    async def check_triggers(self):
        """Check all scheduled triggers and execute if needed."""
        # Get all active scheduled triggers
        triggers = self.db.query(Trigger).filter(
            Trigger.is_active == True,
            Trigger.trigger_type == TriggerType.schedule
        ).all()

        now = datetime.utcnow()

        for trigger in triggers:
            try:
                if self._should_execute(trigger, now):
                    logger.info(f"Executing trigger {trigger.id}: {trigger.name}")
                    await self._execute_trigger(trigger)
            except Exception as e:
                logger.error(f"Error executing trigger {trigger.id}: {e}", exc_info=True)

    def _should_execute(self, trigger: Trigger, now: datetime) -> bool:
        """
        Check if a trigger should execute based on cron pattern.

        Uses croniter to parse cron expression and check if current time matches.
        """
        if not trigger.schedule:
            return False

        try:
            # Check if max run count exceeded
            if trigger.max_run_count and trigger.run_count >= trigger.max_run_count:
                logger.info(f"Trigger {trigger.id} reached max run count")
                return False

            # Use croniter to check if now matches the cron schedule
            cron = croniter(trigger.schedule, trigger.last_executed_at or now)
            next_run = cron.get_next(datetime)

            # Check if we're within 1 minute of the scheduled time (tolerance for polling)
            time_diff = abs((now - next_run).total_seconds())
            if time_diff < 60:  # Within 1 minute
                logger.info(f"Trigger {trigger.id} should execute")
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking cron pattern {trigger.schedule}: {e}")
            return False

    async def _execute_trigger(self, trigger: Trigger):
        """Execute a trigger."""
        service = TriggerService(self.db)
        try:
            room = await service.execute_trigger(trigger.id)
            logger.info(f"Trigger {trigger.id} executed, created room {room.id}")
        except Exception as e:
            logger.error(f"Failed to execute trigger {trigger.id}: {e}")


async def start_trigger_worker():
    """Start the trigger worker as a background task."""
    worker = TriggerWorker()
    await worker.start()


# Wrapper for FastAPI startup
def create_trigger_worker_task():
    """Create a background task for the trigger worker."""
    return asyncio.create_task(start_trigger_worker())
