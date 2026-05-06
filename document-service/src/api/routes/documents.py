import json
import logging
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
import aiofiles
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.database import get_db
from src.core.auth import verify_token
from src.models.document import Document
from src.schemas.document import DocumentCreate, DocumentUpdate, DocumentResponse, SummarizeRequest, SummarizeResponse, SemanticSearchRequest, SemanticSearchResponse, TagSuggestResponse
from src.services import document_service
from src.services.ai_service import summarize_document, semantic_search, suggest_tags
from src.services.metadata_service import extract_basic_metadata
from src.services.ocr_service import extract_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    data: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.create_document(db, data, owner_id=owner_id)

    basic = extract_basic_metadata(doc.content)
    doc.word_count = basic.get("word_count")
    doc.language   = basic.get("language")
    doc.processing_status = "pending"

    await db.commit()
    await db.refresh(doc)

    from src.core.publisher import publish_document_created
    await publish_document_created(doc)

    try:
        from src.tasks.document_tasks import process_document_ai
        process_document_ai.delay(doc.id)
    except Exception as exc:
        logger.warning("Celery unavailable, skipping background AI processing: %s", exc)

    return doc


@router.get("", response_model=List[DocumentResponse])
async def list_documents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    return await document_service.list_documents(db, owner_id=owner_id, skip=skip, limit=limit)


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    file_bytes = await file.read()

    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    mime_type = file.content_type or "application/octet-stream"
    filename = file.filename or "untitled"
    doc_title = title.strip() if (title and title.strip()) else Path(filename).stem

    extracted = extract_text(file_bytes, mime_type, filename)
    content = extracted.text
    if not content.strip():
        content = f"[File uploaded: {filename} — automatic text extraction was not available]"

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
    dest = upload_dir / f"{uuid.uuid4()}_{safe_name}"
    async with aiofiles.open(dest, "wb") as f:
        await f.write(file_bytes)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    basic = extract_basic_metadata(content)
    doc = Document(
        title=doc_title,
        content=content[:50000],
        file_path=str(dest),
        file_name=filename,
        file_size=len(file_bytes),
        mime_type=mime_type,
        page_count=extracted.page_count,
        word_count=basic.get("word_count"),
        language=basic.get("language"),
        processing_status="pending",
        tags=tag_list,
        owner_id=owner_id,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    await db.commit()
    await db.refresh(doc)

    from src.core.publisher import publish_document_created
    await publish_document_created(doc)

    try:
        from src.tasks.document_tasks import process_document_ai
        process_document_ai.delay(doc.id)
    except Exception as exc:
        logger.warning("Celery unavailable, skipping background AI processing: %s", exc)

    return doc


@router.get("/search", response_model=List[DocumentResponse])
async def search_documents(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    return await document_service.search_documents(db, q, owner_id=owner_id)


@router.post("/search/semantic", response_model=SemanticSearchResponse)
async def semantic_search_endpoint(
    data: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    docs = await document_service.list_documents(db, owner_id=owner_id, skip=0, limit=1000)
    results, mode = await semantic_search(docs, data.query, data.limit)
    return SemanticSearchResponse(results=results, mode=mode, total=len(results))


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.get_document(db, doc_id, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{doc_id}/status")
async def get_processing_status(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.get_document(db, doc_id, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "document_id": doc_id,
        "status": doc.processing_status or "completed",
        "has_embedding": doc.embedding is not None,
        "has_ai_metadata": doc.category is not None,
    }


@router.put("/{doc_id}", response_model=DocumentResponse)
async def update_document(
    doc_id: str,
    data: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.update_document(db, doc_id, data, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if data.title is not None or data.content is not None:
        doc.processing_status = "pending"
        try:
            from src.tasks.document_tasks import process_document_ai
            process_document_ai.delay(doc.id)
        except Exception as exc:
            logger.warning("Celery unavailable for re-indexing doc %s: %s", doc_id, exc)

    return doc


@router.delete("/{doc_id}", response_model=DocumentResponse)
async def delete_document(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.soft_delete_document(db, doc_id, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/{doc_id}/summarize", response_model=SummarizeResponse)
async def summarize(
    doc_id: str,
    data: SummarizeRequest,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.get_document(db, doc_id, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await summarize_document(doc, data.max_length)


@router.post("/{doc_id}/tags/suggest", response_model=TagSuggestResponse)
async def suggest_document_tags(
    doc_id: str,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    doc = await document_service.get_document(db, doc_id, owner_id=owner_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await suggest_tags(doc)
