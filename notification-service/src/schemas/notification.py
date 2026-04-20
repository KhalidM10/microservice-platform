from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_type: str
    document_id: Optional[str]
    owner_id: Optional[str]
    message: str
    is_read: bool
    created_at: datetime
