from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.auth import verify_token
from src.schemas.notification import NotificationResponse
from src.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    return await notification_service.list_notifications(db, owner_id=owner_id)


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    notification = await notification_service.get_notification(db, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.owner_id != token["sub"]:
        raise HTTPException(status_code=403, detail="Not your notification")
    updated = await notification_service.mark_as_read(db, notification_id)
    return updated
