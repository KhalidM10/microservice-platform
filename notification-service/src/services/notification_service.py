import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models.notification import Notification

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    event_type: str,
    message: str,
    document_id: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> Notification:
    notification = Notification(
        event_type=event_type,
        document_id=document_id,
        owner_id=owner_id,
        message=message,
    )
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    logger.info("Notification saved: %s", document_id)
    return notification


async def list_notifications(db: AsyncSession, owner_id: Optional[str] = None) -> List[Notification]:
    query = select(Notification).order_by(Notification.created_at.desc())
    if owner_id:
        query = query.where(Notification.owner_id == owner_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def mark_as_read(db: AsyncSession, notification_id: str) -> Optional[Notification]:
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notification = result.scalar_one_or_none()
    if not notification:
        return None
    notification.is_read = True
    await db.flush()
    await db.refresh(notification)
    return notification
