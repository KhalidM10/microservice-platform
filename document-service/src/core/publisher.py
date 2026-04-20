import json
import logging
import aio_pika
from src.core.config import settings

logger = logging.getLogger(__name__)

_connection = None
_channel = None


async def get_channel():
    global _connection, _channel
    if _connection is None or _connection.is_closed:
        _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
    if _channel is None or _channel.is_closed:
        _channel = await _connection.channel()
    return _channel


async def publish_document_created(document) -> None:
    payload = {
        "event": "document.created",
        "document_id": str(document.id),
        "title": document.title,
        "owner_id": document.owner_id,
        "timestamp": document.created_at.isoformat(),
    }
    try:
        channel = await get_channel()
        await channel.declare_queue("document.created", durable=True)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key="document.created",
        )
        logger.info("Published document.created event for %s", document.id)
    except Exception as exc:
        logger.warning("Failed to publish document.created event: %s", exc)
