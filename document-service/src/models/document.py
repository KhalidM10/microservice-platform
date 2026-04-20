import uuid
import json
from datetime import datetime
from sqlalchemy import String, Text, Boolean, DateTime, func, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TEXT
from src.core.database import Base


class JSONArray(TypeDecorator):
    """Stores list as JSON text — works with both PostgreSQL and SQLite."""
    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        return json.loads(value)


def _uuid_column():
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONArray, nullable=True)
