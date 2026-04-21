import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.auth import verify_token
from src.schemas.document import DocumentCreate, DocumentUpdate, DocumentResponse, SummarizeRequest, SummarizeResponse, SemanticSearchRequest, TagSuggestResponse
from src.services import document_service
from src.services.ai_service import summarize_document, semantic_search, suggest_tags

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
    # Commit before responding so a subsequent list request always sees the new doc
    await db.commit()
    await db.refresh(doc)

    from src.core.publisher import publish_document_created
    await publish_document_created(doc)

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


@router.get("/search", response_model=List[DocumentResponse])
async def search_documents(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    return await document_service.search_documents(db, q, owner_id=owner_id)


@router.post("/search/semantic")
async def semantic_search_endpoint(
    data: SemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
    token: dict = Depends(verify_token),
):
    owner_id = token["sub"]
    docs = await document_service.list_documents(db, owner_id=owner_id, skip=0, limit=1000)
    return await semantic_search(docs, data.query, data.limit)


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
