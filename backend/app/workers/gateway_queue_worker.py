"""
Gateway Message Queue Worker

Handles async webhook delivery to agents for messages.
Processes messages from MessageQueue table with retry logic.
"""

import asyncio
import httpx
import logging
import uuid
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.gateway_models import (
    Message, MessageQueue, MessageStatus, GatewayAgent, DeferredResponse
)

logger = logging.getLogger(__name__)


class MessageQueueWorker:
    """
    Worker that polls the message queue and delivers messages to agents via webhooks.

    Flow:
    1. Poll for unprocessed messages in queue
    2. Fetch agent webhook URL
    3. POST message to webhook
    4. Handle response:
       - Immediate response: update message status to "responded"
       - Deferred response: create DeferredResponse record, set to "acknowledged"
       - Failure: retry with exponential backoff
    """

    def __init__(self, db: Session = None, poll_interval: int = 5):
        self.db = db or SessionLocal()
        self.poll_interval = poll_interval
        self.http_client = None

    async def start(self):
        """Start the worker loop."""
        logger.info("Starting MessageQueueWorker")
        async with httpx.AsyncClient(timeout=10.0) as client:
            self.http_client = client
            while True:
                try:
                    await self.process_queue()
                except Exception as e:
                    logger.error(f"Error in queue worker: {e}", exc_info=True)

                await asyncio.sleep(self.poll_interval)

    async def process_queue(self):
        """Process all pending messages in queue."""
        # Get messages that need processing
        pending = self.db.query(MessageQueue).filter(
            MessageQueue.processed_at == None,
            MessageQueue.retry_count < MessageQueue.max_retries
        ).all()

        # Also get retryable messages
        now = datetime.utcnow()
        retryable = self.db.query(MessageQueue).filter(
            MessageQueue.next_retry_at != None,
            MessageQueue.next_retry_at <= now,
            MessageQueue.retry_count < MessageQueue.max_retries
        ).all()

        for queue_entry in pending + retryable:
            await self.process_message(queue_entry)

    async def process_message(self, queue_entry: MessageQueue):
        """Process a single message delivery."""
        try:
            # Get the message
            message = self.db.query(Message).filter(Message.id == queue_entry.message_id).first()
            if not message:
                logger.warning(f"Message {queue_entry.message_id} not found")
                queue_entry.processed_at = datetime.utcnow()
                self.db.commit()
                return

            # Get recipient agent
            to_agent = self.db.query(GatewayAgent).filter(
                GatewayAgent.id == message.to_agent_id
            ).first()
            if not to_agent:
                logger.warning(f"Agent {message.to_agent_id} not found")
                message.status = MessageStatus.failed
                queue_entry.webhook_error = "Recipient agent not found"
                queue_entry.processed_at = datetime.utcnow()
                self.db.commit()
                return

            # Prepare webhook payload
            payload = {
                "message_id": str(message.id),
                "room_id": str(message.room_id),
                "from_agent": str(message.from_agent_id),
                "intent": message.intent.value,
                "body": message.body,
                "tags": message.tags,
                "requires_response": message.requires_response,
                "response_deadline": message.response_deadline.isoformat() if message.response_deadline else None
            }

            # Send webhook
            logger.info(f"Sending message {message.id} to {to_agent.handle} via {to_agent.webhook_url}")

            response = await self.http_client.post(
                to_agent.webhook_url,
                json=payload
            )
            queue_entry.webhook_status_code = response.status_code

            if response.status_code == 200:
                response_data = response.json()

                # Check if agent provided immediate response
                if response_data.get("response_body"):
                    # Immediate response
                    message.status = MessageStatus.responded
                    message.processed_at = datetime.utcnow()
                    logger.info(f"Message {message.id} received immediate response")

                elif response_data.get("status") in ["acknowledged", "processing"]:
                    # Deferred response
                    message.status = MessageStatus.acknowledged
                    message.delivered_at = datetime.utcnow()

                    # Create deferred response record
                    deferred = DeferredResponse(
                        id=str(uuid.uuid4()),
                        message_id=message.id,
                        task_id=response_data.get("task_id", str(uuid.uuid4())),
                        status=response_data.get("status", "acknowledged"),
                        estimated_completion=response_data.get("estimated_completion")
                    )
                    self.db.add(deferred)
                    logger.info(f"Message {message.id} deferred with task_id {deferred.task_id}")

                else:
                    # Unknown response format
                    message.status = MessageStatus.delivered
                    message.delivered_at = datetime.utcnow()

                queue_entry.webhook_response = response_data
                queue_entry.processed_at = datetime.utcnow()
                queue_entry.retry_count = 0

                self.db.commit()

            else:
                # HTTP error - retry
                await self._schedule_retry(queue_entry, f"HTTP {response.status_code}")

        except httpx.TimeoutException as e:
            logger.warning(f"Timeout delivering message {queue_entry.message_id}")
            await self._schedule_retry(queue_entry, f"Timeout: {str(e)}")
        except Exception as e:
            logger.error(f"Error processing message {queue_entry.message_id}: {e}")
            await self._schedule_retry(queue_entry, str(e))

    async def _schedule_retry(self, queue_entry: MessageQueue, error_msg: str):
        """Schedule a message for retry with exponential backoff."""
        queue_entry.retry_count += 1
        queue_entry.webhook_error = error_msg

        if queue_entry.retry_count < queue_entry.max_retries:
            # Exponential backoff: 30s, 2m, 8m, 30m
            backoff_seconds = [30, 120, 480, 1800]
            if queue_entry.retry_count <= len(backoff_seconds):
                delay = backoff_seconds[queue_entry.retry_count - 1]
                queue_entry.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                logger.info(f"Scheduling retry for message {queue_entry.message_id} in {delay}s")
            else:
                queue_entry.next_retry_at = datetime.utcnow() + timedelta(hours=1)
        else:
            # Max retries exceeded
            message = self.db.query(Message).filter(Message.id == queue_entry.message_id).first()
            if message:
                message.status = MessageStatus.failed
                # Notify from_agent that delivery failed?
            queue_entry.processed_at = datetime.utcnow()
            logger.error(f"Message {queue_entry.message_id} failed after {queue_entry.max_retries} retries")

        self.db.commit()


async def start_queue_worker():
    """Start the message queue worker as a background task."""
    worker = MessageQueueWorker()
    await worker.start()


# Wrapper for FastAPI startup
def create_queue_worker_task():
    """Create a background task for the queue worker."""
    import uuid  # Import here to avoid circular imports
    return asyncio.create_task(start_queue_worker())
