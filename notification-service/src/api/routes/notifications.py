from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.schemas.notification import NotificationResponse
from src.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    owner_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.list_notifications(db, owner_id=owner_id)


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
):
    notification = await notification_service.mark_as_read(db, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification
