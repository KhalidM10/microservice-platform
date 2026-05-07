import asyncio
import json
import logging

from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.core.celery_app import celery_app
from src.core.config import settings
from src.models.document import Document
from src.services.ai_service import generate_embedding
from src.services.metadata_service import extract_ai_metadata

logger = get_task_logger(__name__)


def _make_session_factory():
    """Create a fresh engine + session factory bound to the current event loop."""
    kwargs = {"echo": False, "pool_pre_ping": True}
    if not settings.DATABASE_URL.startswith("sqlite"):
        kwargs["pool_size"] = 2
        kwargs["max_overflow"] = 2
    engine = create_async_engine(settings.DATABASE_URL, **kwargs)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=15, name="process_document_ai")
def process_document_ai(self, doc_id: str) -> dict:
    """Generate embedding + AI metadata for a document in the background."""
    try:
        asyncio.run(_process(doc_id))
        return {"status": "completed", "doc_id": doc_id}
    except Exception as exc:
        logger.error("AI processing failed for doc %s: %s", doc_id, exc)
        try:
            asyncio.run(_set_status(doc_id, "failed"))
        except Exception:
            pass
        raise self.retry(exc=exc)


async def _process(doc_id: str) -> None:
    SessionLocal = _make_session_factory()
    async with SessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id == doc_id))
        doc = result.scalar_one_or_none()
        if not doc or doc.is_deleted:
            return

        doc.processing_status = "processing"
        await db.flush()

        embedding = await generate_embedding(f"{doc.title}\n\n{doc.content[:6000]}")
        if embedding:
            doc.embedding = json.dumps(embedding)

        ai_meta = await extract_ai_metadata(doc)
        if ai_meta:
            doc.entities  = json.dumps(ai_meta["entities"]) if ai_meta.get("entities") else None
            doc.category  = ai_meta.get("category")
            doc.sentiment = ai_meta.get("sentiment")

        doc.processing_status = "completed"
        await db.commit()
        logger.info("AI processing completed for doc %s", doc_id)


async def _set_status(doc_id: str, status: str) -> None:
    try:
        SessionLocal = _make_session_factory()
        async with SessionLocal() as db:
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if doc:
                doc.processing_status = status
                await db.commit()
    except Exception as exc:
        logger.error("Failed to set status %s for doc %s: %s", status, doc_id, exc)
