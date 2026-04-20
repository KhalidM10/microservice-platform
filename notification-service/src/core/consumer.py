import asyncio
import json
import logging
from typing import Optional
import aio_pika
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.services.notification_service import create_notification

logger = logging.getLogger(__name__)


async def handle_document_created(message: aio_pika.IncomingMessage):
    async with message.process():
        try:
            payload = json.loads(message.body.decode())
            document_id = payload.get("document_id")
            title = payload.get("title", "Untitled")
            owner_id = payload.get("owner_id")

            async with AsyncSessionLocal() as db:
                try:
                    await create_notification(
                        db,
                        event_type="document.created",
                        message=f"Document '{title}' was created.",
                        document_id=document_id,
                        owner_id=owner_id,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception as exc:
            logger.error("Failed to process document.created message: %s", exc)


async def start_consumer() -> Optional[aio_pika.RobustConnection]:
    try:
        connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
        channel = await connection.channel()
        queue = await channel.declare_queue("document.created", durable=True)
        await queue.consume(handle_document_created)
        logger.info("RabbitMQ consumer started on queue 'document.created'")
        return connection
    except Exception as exc:
        logger.warning("RabbitMQ not available, consumer not started: %s", exc)
        return None
