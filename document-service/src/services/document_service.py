from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from src.models.document import Document
from src.schemas.document import DocumentCreate, DocumentUpdate


async def create_document(db: AsyncSession, data: DocumentCreate, owner_id: Optional[str] = None) -> Document:
    doc = Document(
        title=data.title,
        content=data.content,
        tags=data.tags,
        owner_id=owner_id,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)
    return doc


async def get_document(
    db: AsyncSession,
    doc_id: str,
    owner_id: Optional[str] = None,
) -> Optional[Document]:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.is_deleted == False)
    )
    doc = result.scalar_one_or_none()
    if doc and owner_id and doc.owner_id != owner_id:
        return None
    return doc


async def list_documents(
    db: AsyncSession,
    owner_id: str,
    skip: int = 0,
    limit: int = 10,
) -> List[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.is_deleted == False, Document.owner_id == owner_id)
        .offset(skip)
        .limit(limit)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())


async def update_document(
    db: AsyncSession,
    doc_id: str,
    data: DocumentUpdate,
    owner_id: Optional[str] = None,
) -> Optional[Document]:
    doc = await get_document(db, doc_id, owner_id=owner_id)
    if not doc:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    await db.flush()
    await db.refresh(doc)
    return doc


async def soft_delete_document(
    db: AsyncSession,
    doc_id: str,
    owner_id: Optional[str] = None,
) -> Optional[Document]:
    doc = await get_document(db, doc_id, owner_id=owner_id)
    if not doc:
        return None
    doc.is_deleted = True
    await db.flush()
    await db.refresh(doc)
    return doc


async def search_documents(
    db: AsyncSession,
    query: str,
    owner_id: str,
) -> List[Document]:
    result = await db.execute(
        select(Document).where(
            Document.is_deleted == False,
            Document.owner_id == owner_id,
            or_(
                Document.title.ilike(f"%{query}%"),
                Document.content.ilike(f"%{query}%"),
            ),
        )
    )
    return list(result.scalars().all())
