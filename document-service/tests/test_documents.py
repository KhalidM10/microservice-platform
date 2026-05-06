import io
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone

from src.main import app
from src.core.database import get_db, Base
from src.core.auth import verify_token
from src.schemas.document import DocumentCreate, DocumentUpdate
from src.services import document_service

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(engine_test, expire_on_commit=False)

USER_A_TOKEN = {"sub": "user-a-123", "role": "user", "type": "access"}
USER_B_TOKEN = {"sub": "user-b-456", "role": "user", "type": "access"}


async def _client_for(token_payload):
    """Return a configured AsyncClient for the given token. Must be used as async context manager."""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_token] = lambda: token_payload
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def override_verify_token_a():
    return USER_A_TOKEN

def override_verify_token_b():
    return USER_B_TOKEN


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """Client authenticated as user A."""
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_token] = override_verify_token_a
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    app.dependency_overrides.clear()



@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


# ─── Basic CRUD ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_document_valid(client):
    response = await client.post("/api/v1/documents", json={
        "title": "Test Document",
        "content": "This is test content for the document.",
        "tags": ["test", "python"],
    })
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Document"
    assert data["id"] is not None
    assert data["owner_id"] == USER_A_TOKEN["sub"]


@pytest.mark.asyncio
async def test_create_document_missing_title(client):
    response = await client.post("/api/v1/documents", json={"content": "Content without title"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_document_no_auth():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/documents", json={"title": "T", "content": "C"})
    app.dependency_overrides.clear()
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_documents_only_own():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            await ac.post("/api/v1/documents", json={"title": "A Doc", "content": "owned by A"})
        async with await _client_for(USER_B_TOKEN) as ac:
            await ac.post("/api/v1/documents", json={"title": "B Doc", "content": "owned by B"})
        async with await _client_for(USER_A_TOKEN) as ac:
            resp_a = await ac.get("/api/v1/documents")
        async with await _client_for(USER_B_TOKEN) as ac:
            resp_b = await ac.get("/api/v1/documents")
    app.dependency_overrides.clear()

    titles_a = [d["title"] for d in resp_a.json()]
    titles_b = [d["title"] for d in resp_b.json()]
    assert "A Doc" in titles_a and "B Doc" not in titles_a
    assert "B Doc" in titles_b and "A Doc" not in titles_b


@pytest.mark.asyncio
async def test_get_own_document(client):
    create = await client.post("/api/v1/documents", json={"title": "Fetch Me", "content": "Fetch content"})
    doc_id = create.json()["id"]
    response = await client.get(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200
    assert response.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_get_other_users_document_returns_404():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            doc_id = (await ac.post("/api/v1/documents", json={"title": "Private", "content": "A only"})).json()["id"]
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.get(f"/api/v1/documents/{doc_id}")
    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_nonexistent_document(client):
    response = await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_own_document(client):
    create = await client.post("/api/v1/documents", json={"title": "Old Title", "content": "Old content"})
    doc_id = create.json()["id"]
    response = await client.put(f"/api/v1/documents/{doc_id}", json={"title": "New Title"})
    assert response.status_code == 200
    assert response.json()["title"] == "New Title"


@pytest.mark.asyncio
async def test_update_other_users_document_returns_404():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            doc_id = (await ac.post("/api/v1/documents", json={"title": "A Title", "content": "A content"})).json()["id"]
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.put(f"/api/v1/documents/{doc_id}", json={"title": "Hijacked"})
    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_nonexistent_document(client):
    response = await client.put(
        "/api/v1/documents/00000000-0000-0000-0000-000000000000",
        json={"title": "New Title"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_own_document(client):
    create = await client.post("/api/v1/documents", json={"title": "Delete Me", "content": "Delete content"})
    doc_id = create.json()["id"]
    response = await client.delete(f"/api/v1/documents/{doc_id}")
    assert response.status_code == 200
    get_response = await client.get(f"/api/v1/documents/{doc_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_other_users_document_returns_404():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            doc_id = (await ac.post("/api/v1/documents", json={"title": "A Only", "content": "content"})).json()["id"]
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.delete(f"/api/v1/documents/{doc_id}")
    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_document(client):
    response = await client.delete("/api/v1/documents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_deleted_document_not_in_list(client):
    create = await client.post("/api/v1/documents", json={"title": "Vanish", "content": "Content"})
    doc_id = create.json()["id"]
    await client.delete(f"/api/v1/documents/{doc_id}")
    response = await client.get("/api/v1/documents")
    ids = [d["id"] for d in response.json()]
    assert doc_id not in ids


@pytest.mark.asyncio
async def test_list_documents_pagination(client):
    for i in range(5):
        await client.post("/api/v1/documents", json={"title": f"Doc {i}", "content": f"Content {i}"})
    response = await client.get("/api/v1/documents?skip=0&limit=2")
    assert response.status_code == 200
    assert len(response.json()) == 2


# ─── Search ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_documents(client):
    await client.post("/api/v1/documents", json={"title": "Python Tutorial", "content": "Learn Python basics"})
    await client.post("/api/v1/documents", json={"title": "Java Guide", "content": "Learn Java basics"})
    response = await client.get("/api/v1/documents/search?q=Python")
    assert response.status_code == 200
    results = response.json()
    assert len(results) >= 1
    assert any("Python" in d["title"] or "Python" in d["content"] for d in results)


@pytest.mark.asyncio
async def test_search_does_not_return_other_users_docs():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            await ac.post("/api/v1/documents", json={"title": "Python Tutorial", "content": "Python basics"})
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.get("/api/v1/documents/search?q=Python")
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_search_no_results(client):
    response = await client.get("/api/v1/documents/search?q=xyznotfound")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_document_with_no_tags(client):
    response = await client.post("/api/v1/documents", json={"title": "No Tags", "content": "Content"})
    assert response.status_code == 201
    assert response.json()["tags"] is None


# ─── AI endpoints ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_extractive(client):
    create = await client.post("/api/v1/documents", json={
        "title": "Summary Test",
        "content": "First sentence here. Second sentence follows. Third sentence ends. Fourth sentence extra.",
    })
    doc_id = create.json()["id"]
    response = await client.post(f"/api/v1/documents/{doc_id}/summarize", json={"max_length": 50})
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert data["model_used"] == "extractive-fallback"
    assert data["document_id"] == doc_id


@pytest.mark.asyncio
async def test_summarize_other_users_document_returns_404():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            doc_id = (await ac.post("/api/v1/documents", json={"title": "Private", "content": "Sentence one. Sentence two."})).json()["id"]
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.post(f"/api/v1/documents/{doc_id}/summarize", json={"max_length": 50})
    app.dependency_overrides.clear()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_summarize_not_found(client):
    response = await client.post(
        "/api/v1/documents/00000000-0000-0000-0000-000000000000/summarize",
        json={"max_length": 100},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_semantic_search(client):
    await client.post("/api/v1/documents", json={"title": "Machine Learning", "content": "Deep learning neural networks AI"})
    await client.post("/api/v1/documents", json={"title": "Cooking", "content": "Recipes food ingredients kitchen"})
    response = await client.post("/api/v1/documents/search/semantic", json={"query": "machine learning AI", "limit": 5})
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert "mode" in data
    assert isinstance(data["results"], list)


@pytest.mark.asyncio
async def test_semantic_search_scoped_to_owner():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            await ac.post("/api/v1/documents", json={"title": "ML Paper", "content": "Deep learning neural networks"})
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.post("/api/v1/documents/search/semantic", json={"query": "deep learning", "limit": 5})
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


# ─── Service layer unit tests ─────────────────────────────────

@pytest.mark.asyncio
async def test_service_create_and_get(db_session):
    doc = await document_service.create_document(
        db_session,
        DocumentCreate(title="Svc Test", content="Svc content", tags=["a"]),
        owner_id="owner-1",
    )
    assert doc.id is not None
    fetched = await document_service.get_document(db_session, doc.id, owner_id="owner-1")
    assert fetched is not None
    assert fetched.title == "Svc Test"


@pytest.mark.asyncio
async def test_service_get_wrong_owner_returns_none(db_session):
    doc = await document_service.create_document(
        db_session,
        DocumentCreate(title="Private", content="secret"),
        owner_id="owner-1",
    )
    result = await document_service.get_document(db_session, doc.id, owner_id="owner-2")
    assert result is None


@pytest.mark.asyncio
async def test_service_get_not_found(db_session):
    result = await document_service.get_document(db_session, "nonexistent-id")
    assert result is None


@pytest.mark.asyncio
async def test_service_list_documents_scoped(db_session):
    await document_service.create_document(db_session, DocumentCreate(title="L1", content="C1"), owner_id="u1")
    await document_service.create_document(db_session, DocumentCreate(title="L2", content="C2"), owner_id="u2")
    docs_u1 = await document_service.list_documents(db_session, owner_id="u1", skip=0, limit=10)
    assert len(docs_u1) == 1
    assert docs_u1[0].title == "L1"


@pytest.mark.asyncio
async def test_service_update_document(db_session):
    doc = await document_service.create_document(
        db_session, DocumentCreate(title="Before", content="Old"), owner_id="u1"
    )
    updated = await document_service.update_document(db_session, doc.id, DocumentUpdate(title="After"), owner_id="u1")
    assert updated is not None
    assert updated.title == "After"


@pytest.mark.asyncio
async def test_service_update_wrong_owner_returns_none(db_session):
    doc = await document_service.create_document(
        db_session, DocumentCreate(title="Mine", content="Content"), owner_id="u1"
    )
    result = await document_service.update_document(db_session, doc.id, DocumentUpdate(title="X"), owner_id="u2")
    assert result is None


@pytest.mark.asyncio
async def test_service_update_not_found(db_session):
    result = await document_service.update_document(db_session, "no-such-id", DocumentUpdate(title="X"))
    assert result is None


@pytest.mark.asyncio
async def test_service_soft_delete(db_session):
    doc = await document_service.create_document(
        db_session, DocumentCreate(title="ToDelete", content="Bye"), owner_id="u1"
    )
    deleted = await document_service.soft_delete_document(db_session, doc.id, owner_id="u1")
    assert deleted is not None
    gone = await document_service.get_document(db_session, doc.id, owner_id="u1")
    assert gone is None


@pytest.mark.asyncio
async def test_service_soft_delete_wrong_owner_returns_none(db_session):
    doc = await document_service.create_document(
        db_session, DocumentCreate(title="Mine", content="Content"), owner_id="u1"
    )
    result = await document_service.soft_delete_document(db_session, doc.id, owner_id="u2")
    assert result is None


@pytest.mark.asyncio
async def test_service_soft_delete_not_found(db_session):
    result = await document_service.soft_delete_document(db_session, "no-such-id")
    assert result is None


@pytest.mark.asyncio
async def test_service_search_scoped(db_session):
    await document_service.create_document(
        db_session, DocumentCreate(title="FastAPI guide", content="Learn FastAPI"), owner_id="u1"
    )
    await document_service.create_document(
        db_session, DocumentCreate(title="FastAPI deep dive", content="Advanced FastAPI"), owner_id="u2"
    )
    results_u1 = await document_service.search_documents(db_session, "FastAPI", owner_id="u1")
    assert len(results_u1) == 1
    results_none = await document_service.search_documents(db_session, "xyznothere", owner_id="u1")
    assert results_none == []


# ─── Auth unit tests ──────────────────────────────────────────

def test_verify_token_valid():
    from jose import jwt
    from src.core.config import settings
    from src.core.auth import verify_token as vt
    from fastapi.security import HTTPAuthorizationCredentials

    token = jwt.encode(
        {"sub": "user-1", "role": "user", "type": "access", "exp": 9999999999},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    payload = vt(creds)
    assert payload["sub"] == "user-1"


def test_verify_token_missing():
    from src.core.auth import verify_token as vt
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        vt(None)
    assert exc_info.value.status_code == 401


def test_verify_token_invalid():
    from src.core.auth import verify_token as vt
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token.value")
    with pytest.raises(HTTPException) as exc_info:
        vt(creds)
    assert exc_info.value.status_code == 401


def test_verify_token_wrong_type():
    from jose import jwt
    from src.core.config import settings
    from src.core.auth import verify_token as vt
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    token = jwt.encode(
        {"sub": "user-1", "role": "user", "type": "refresh", "exp": 9999999999},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        vt(creds)
    assert exc_info.value.status_code == 401


# ─── AI service unit tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_service_extractive_summary():
    from src.services.ai_service import summarize_document
    doc = MagicMock()
    doc.id = "test-doc-id"
    doc.content = "First sentence. Second sentence. Third sentence. Fourth sentence beyond limit."
    result = await summarize_document(doc, max_length=20)
    assert result.document_id == "test-doc-id"
    assert result.model_used == "extractive-fallback"
    assert len(result.summary) > 0


@pytest.mark.asyncio
async def test_ai_service_semantic_search_empty():
    from src.services.ai_service import semantic_search
    results, mode = await semantic_search([], "query", 10)
    assert results == []


@pytest.mark.asyncio
async def test_ai_service_semantic_search_results():
    from src.services.ai_service import semantic_search

    doc1 = MagicMock()
    doc1.id = "d1"
    doc1.title = "Python programming"
    doc1.content = "Learn Python with examples"
    doc1.owner_id = "u1"
    doc1.tags = ["python"]
    doc1.embedding = None

    doc2 = MagicMock()
    doc2.id = "d2"
    doc2.title = "Cooking recipes"
    doc2.content = "How to cook pasta"
    doc2.owner_id = "u1"
    doc2.tags = []
    doc2.embedding = None

    results, mode = await semantic_search([doc1, doc2], "Python programming", 10)
    assert mode == "tfidf"
    assert len(results) >= 1
    assert results[0].id == "d1"


# ─── Upload endpoint ─────────────────────────────────────────

@pytest_asyncio.fixture
async def upload_client():
    """Client with OCR, metadata, filesystem, Celery, and publisher all mocked."""
    from src.services.ocr_service import ExtractionResult

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_token] = override_verify_token_a

    mock_file_handle = AsyncMock()
    mock_file_handle.write = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_file_handle)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("src.core.publisher.publish_document_created", new_callable=AsyncMock),
        patch("src.api.routes.documents.extract_text",
              return_value=ExtractionResult(text="Extracted file content here.", page_count=2)),
        patch("src.api.routes.documents.extract_basic_metadata",
              return_value={"word_count": 4, "language": "en"}),
        patch("aiofiles.open", return_value=mock_cm),
        patch("pathlib.Path.mkdir"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upload_document_txt_file(upload_client):
    response = await upload_client.post(
        "/api/v1/documents/upload",
        files={"file": ("report.txt", io.BytesIO(b"Hello world content"), "text/plain")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "report"
    assert data["owner_id"] == USER_A_TOKEN["sub"]
    assert data["content"] == "Extracted file content here."


@pytest.mark.asyncio
async def test_upload_document_custom_title_and_tags(upload_client):
    response = await upload_client.post(
        "/api/v1/documents/upload",
        files={"file": ("notes.txt", io.BytesIO(b"Some notes"), "text/plain")},
        data={"title": "My Custom Title", "tags": "tag1, tag2"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "My Custom Title"
    assert set(data["tags"]) == {"tag1", "tag2"}


@pytest.mark.asyncio
async def test_upload_document_includes_file_metadata(upload_client):
    content = b"File content bytes"
    response = await upload_client.post(
        "/api/v1/documents/upload",
        files={"file": ("document.pdf", io.BytesIO(content), "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["file_name"] == "document.pdf"
    assert data["mime_type"] == "application/pdf"
    assert data["file_size"] == len(content)
    assert data["word_count"] == 4
    assert data["language"] == "en"
    assert data["page_count"] == 2


@pytest.mark.asyncio
async def test_upload_document_too_large_returns_413():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_token] = override_verify_token_a
    big_content = b"x" * (10 * 1024 * 1024 + 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/documents/upload",
            files={"file": ("big.txt", io.BytesIO(big_content), "text/plain")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_upload_document_no_auth_returns_401():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/documents/upload",
            files={"file": ("test.txt", io.BytesIO(b"content"), "text/plain")},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upload_document_scoped_to_owner(upload_client):
    create_resp = await upload_client.post(
        "/api/v1/documents/upload",
        files={"file": ("private.txt", io.BytesIO(b"Private content"), "text/plain")},
    )
    assert create_resp.status_code == 201
    doc_id = create_resp.json()["id"]

    app.dependency_overrides[verify_token] = override_verify_token_b
    response = await upload_client.get(f"/api/v1/documents/{doc_id}")
    app.dependency_overrides[verify_token] = override_verify_token_a
    assert response.status_code == 404


# ─── Processing status endpoint ────────────────────────────────

@pytest.mark.asyncio
async def test_get_processing_status_own_doc(client):
    create = await client.post("/api/v1/documents", json={"title": "Status Test", "content": "Content"})
    doc_id = create.json()["id"]
    response = await client.get(f"/api/v1/documents/{doc_id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == doc_id
    assert "status" in data
    assert "has_embedding" in data
    assert "has_ai_metadata" in data


@pytest.mark.asyncio
async def test_get_processing_status_not_found(client):
    response = await client.get("/api/v1/documents/00000000-0000-0000-0000-000000000000/status")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_processing_status_other_user_404():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            doc_id = (await ac.post("/api/v1/documents", json={"title": "Mine", "content": "Content"})).json()["id"]
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.get(f"/api/v1/documents/{doc_id}/status")
    app.dependency_overrides.clear()
    assert response.status_code == 404


# ─── Tag suggestion endpoint ────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_tags_no_openai_returns_empty(client):
    create = await client.post("/api/v1/documents", json={"title": "Tag Test", "content": "Some content for tagging"})
    doc_id = create.json()["id"]
    response = await client.post(f"/api/v1/documents/{doc_id}/tags/suggest")
    assert response.status_code == 200
    data = response.json()
    assert "suggested_tags" in data
    assert isinstance(data["suggested_tags"], list)


@pytest.mark.asyncio
async def test_suggest_tags_not_found(client):
    response = await client.post("/api/v1/documents/00000000-0000-0000-0000-000000000000/tags/suggest")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_suggest_tags_other_user_404():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            doc_id = (await ac.post("/api/v1/documents", json={"title": "Private", "content": "secret content"})).json()["id"]
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.post(f"/api/v1/documents/{doc_id}/tags/suggest")
    app.dependency_overrides.clear()
    assert response.status_code == 404


# ─── OCR service unit tests ─────────────────────────────────────

def test_ocr_extract_text_plain_utf8():
    from src.services.ocr_service import extract_text
    result = extract_text(b"Hello world from plain text.", "text/plain", "file.txt")
    assert "Hello world" in result.text
    assert result.page_count is None


def test_ocr_extract_text_pdf_mocked():
    from src.services.ocr_service import extract_text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "PDF page content"
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page, mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text(b"%PDF fake bytes", "application/pdf", "doc.pdf")
    assert result.text == "PDF page content\n\nPDF page content"
    assert result.page_count == 2


def test_ocr_extract_text_docx_mocked():
    from src.services.ocr_service import extract_text
    mock_para = MagicMock()
    mock_para.text = "Paragraph text"
    mock_doc = MagicMock()
    mock_doc.paragraphs = [mock_para]
    with patch("docx.Document", return_value=mock_doc):
        result = extract_text(
            b"fake docx bytes",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc.docx",
        )
    assert "Paragraph text" in result.text
    assert result.page_count is None


def test_ocr_extract_text_image_mocked():
    from src.services.ocr_service import extract_text
    with (
        patch("pytesseract.image_to_string", return_value="OCR extracted text"),
        patch("PIL.Image.open", return_value=MagicMock()),
    ):
        result = extract_text(b"fake png bytes", "image/png", "scan.png")
    assert result.text == "OCR extracted text"
    assert result.page_count is None


def test_ocr_extract_text_exception_returns_empty():
    from src.services.ocr_service import extract_text
    with patch("pdfplumber.open", side_effect=Exception("corrupt file")):
        result = extract_text(b"bad bytes", "application/pdf", "broken.pdf")
    assert result.text == ""


def test_ocr_extract_text_unknown_mime_type():
    from src.services.ocr_service import extract_text
    result = extract_text(b"Plain data as unknown mime", "application/x-unknown", "mystery.bin")
    assert "Plain data" in result.text


# ─── Metadata service unit tests ────────────────────────────────

def test_metadata_word_count():
    from src.services.metadata_service import extract_basic_metadata
    result = extract_basic_metadata("one two three four five")
    assert result["word_count"] == 5


def test_metadata_empty_content():
    from src.services.metadata_service import extract_basic_metadata
    result = extract_basic_metadata("")
    assert result["word_count"] == 0
    assert result["language"] is None


def test_metadata_language_detection_mocked():
    from src.services.metadata_service import extract_basic_metadata
    with patch("langdetect.detect", return_value="fr"):
        result = extract_basic_metadata("Bonjour monde ceci est un texte suffisamment long pour la detection")
    assert result["language"] == "fr"


@pytest.mark.asyncio
async def test_metadata_ai_no_key_returns_empty():
    from src.services.metadata_service import extract_ai_metadata
    doc = MagicMock()
    doc.id = "test-id"
    doc.title = "Test"
    doc.content = "Content"
    with patch("src.services.metadata_service.settings") as mock_settings:
        mock_settings.OPENAI_API_KEY = ""
        result = await extract_ai_metadata(doc)
    assert result == {}


# ─── AI service: cosine similarity & embedding tests ───────────

def test_cosine_similarity_identical_vectors():
    from src.services.ai_service import _cosine_similarity
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors():
    from src.services.ai_service import _cosine_similarity
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6


def test_cosine_similarity_zero_vector():
    from src.services.ai_service import _cosine_similarity
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_tfidf_search_returns_best_match():
    from src.services.ai_service import _tfidf_search
    doc1 = MagicMock()
    doc1.id = "d1"; doc1.title = "python guide"; doc1.content = "learn python programming"
    doc1.owner_id = "u1"; doc1.tags = []
    doc2 = MagicMock()
    doc2.id = "d2"; doc2.title = "cooking"; doc2.content = "how to cook pasta"
    doc2.owner_id = "u1"; doc2.tags = []
    results = _tfidf_search([doc1, doc2], "python programming", 5)
    assert len(results) >= 1
    assert results[0].id == "d1"


def test_tfidf_search_empty_corpus():
    from src.services.ai_service import _tfidf_search
    assert _tfidf_search([], "query", 5) == []


@pytest.mark.asyncio
async def test_generate_embedding_no_key_returns_none():
    from src.services.ai_service import generate_embedding
    with patch("src.services.ai_service.settings") as mock_settings:
        mock_settings.OPENAI_API_KEY = ""
        result = await generate_embedding("some text")
    assert result is None


@pytest.mark.asyncio
async def test_generate_embedding_with_key_mocked():
    from src.services.ai_service import generate_embedding
    mock_embedding = [0.1] * 1536
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=mock_embedding)]
    mock_client = AsyncMock()
    mock_client.embeddings.create = AsyncMock(return_value=mock_response)
    with (
        patch("src.services.ai_service.settings") as mock_settings,
        patch("openai.AsyncOpenAI", return_value=mock_client),
    ):
        mock_settings.OPENAI_API_KEY = "sk-fake-key"
        result = await generate_embedding("test text")
    assert result == mock_embedding


# ─── OpenAI-path unit tests (ai_service + metadata_service) ────

def _make_chat_response(text: str):
    """Build a minimal mock of an OpenAI chat completions response."""
    msg = MagicMock()
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    return resp


@pytest.mark.asyncio
async def test_summarize_document_openai_path():
    from src.services.ai_service import summarize_document
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_chat_response("This is an AI summary.")
    )
    doc = MagicMock()
    doc.id = "s1"; doc.title = "Report"; doc.content = "First. Second. Third."
    with (
        patch("src.services.ai_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.ai_service._get_redis", return_value=None),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await summarize_document(doc, max_length=50)
    assert result.summary == "This is an AI summary."
    assert result.model_used != "extractive-fallback"


@pytest.mark.asyncio
async def test_summarize_document_redis_cache_hit():
    import json as _json
    from src.services.ai_service import summarize_document
    from src.schemas.document import SummarizeResponse
    cached_resp = SummarizeResponse(
        document_id="cached-id", summary="Cached summary",
        original_length=10, summary_length=2, model_used="gpt-4o-mini",
    )
    mock_redis = MagicMock()
    mock_redis.get = MagicMock(return_value=_json.dumps(cached_resp.model_dump()))
    doc = MagicMock()
    doc.id = "cached-id"
    with patch("src.services.ai_service._get_redis", return_value=mock_redis):
        result = await summarize_document(doc, max_length=50)
    assert result.summary == "Cached summary"
    assert result.model_used == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_suggest_tags_openai_path():
    import json as _json
    from src.services.ai_service import suggest_tags
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_chat_response('["python", "fastapi", "async"]')
    )
    doc = MagicMock()
    doc.id = "t1"; doc.title = "FastAPI Guide"; doc.content = "Python async web framework guide."
    with (
        patch("src.services.ai_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.ai_service._get_redis", return_value=None),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await suggest_tags(doc)
    assert set(result.suggested_tags) == {"python", "fastapi", "async"}


@pytest.mark.asyncio
async def test_suggest_tags_redis_cache_hit():
    import json as _json
    from src.services.ai_service import suggest_tags
    from src.schemas.document import TagSuggestResponse
    cached = TagSuggestResponse(suggested_tags=["cached", "tag"], model_used="gpt-4o-mini")
    mock_redis = MagicMock()
    mock_redis.get = MagicMock(return_value=_json.dumps(cached.model_dump()))
    doc = MagicMock()
    doc.id = "cache-tag-id"
    with patch("src.services.ai_service._get_redis", return_value=mock_redis):
        result = await suggest_tags(doc)
    assert result.suggested_tags == ["cached", "tag"]


@pytest.mark.asyncio
async def test_embedding_search_with_stored_embeddings():
    import json as _json
    from src.services.ai_service import _embedding_search
    import numpy as np
    v = [1.0, 0.0, 0.0]
    doc = MagicMock()
    doc.id = "emb1"; doc.title = "T"; doc.content = "C"; doc.owner_id = "u1"; doc.tags = []
    doc.embedding = _json.dumps(v)
    results = _embedding_search([doc], v, limit=5)
    assert len(results) == 1
    assert results[0].similarity_score > 0.99


@pytest.mark.asyncio
async def test_semantic_search_uses_embedding_when_available():
    import json as _json
    from src.services.ai_service import semantic_search
    v = [1.0, 0.0, 0.0]
    doc = MagicMock()
    doc.id = "emb2"; doc.title = "Embeddings"; doc.content = "vector search"
    doc.owner_id = "u1"; doc.tags = []; doc.embedding = _json.dumps(v)
    mock_embedding = [1.0, 0.0, 0.0]
    with (
        patch("src.services.ai_service.settings") as ms,
        patch("src.services.ai_service.generate_embedding", new=AsyncMock(return_value=mock_embedding)),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        results, mode = await semantic_search([doc], "vector search", 5)
    assert mode == "embedding"
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_metadata_ai_extraction_with_openai():
    import json as _json
    from src.services.metadata_service import extract_ai_metadata
    expected = {
        "entities": {"people": ["Alice"], "organizations": ["ACME"], "locations": []},
        "category": "report",
        "sentiment": "positive",
    }
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_chat_response(_json.dumps(expected))
    )
    doc = MagicMock()
    doc.id = "meta1"; doc.title = "Report"; doc.content = "Alice from ACME presented results."
    with (
        patch("src.services.metadata_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.metadata_service._get_redis", return_value=None),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await extract_ai_metadata(doc)
    assert result["category"] == "report"
    assert result["sentiment"] == "positive"
    assert result["entities"]["people"] == ["Alice"]


@pytest.mark.asyncio
async def test_metadata_ai_extraction_redis_cache_hit():
    import json as _json
    from src.services.metadata_service import extract_ai_metadata
    cached = {"entities": {}, "category": "note", "sentiment": "neutral"}
    mock_redis = MagicMock()
    mock_redis.get = MagicMock(return_value=_json.dumps(cached))
    doc = MagicMock()
    doc.id = "meta-cached"
    with (
        patch("src.services.metadata_service.settings") as ms,
        patch("src.services.metadata_service._get_redis", return_value=mock_redis),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await extract_ai_metadata(doc)
    assert result["category"] == "note"


# ─── Coverage gap-fillers: _get_redis paths & exception branches ─

def test_ai_service_get_redis_initialises_client():
    from src.services import ai_service
    mock_redis = MagicMock()
    original = ai_service._redis_client
    with patch("redis.Redis.from_url", return_value=mock_redis):
        ai_service._redis_client = None
        result = ai_service._get_redis()
    ai_service._redis_client = original
    assert result is mock_redis


def test_ai_service_get_redis_returns_existing_client():
    from src.services import ai_service
    sentinel = MagicMock()
    original = ai_service._redis_client
    ai_service._redis_client = sentinel
    result = ai_service._get_redis()
    ai_service._redis_client = original
    assert result is sentinel


def test_metadata_get_redis_initialises_client():
    from src.services import metadata_service
    mock_redis = MagicMock()
    original = metadata_service._redis_client
    with patch("redis.Redis.from_url", return_value=mock_redis):
        metadata_service._redis_client = None
        result = metadata_service._get_redis()
    metadata_service._redis_client = original
    assert result is mock_redis


def test_metadata_language_detect_exception_handled():
    from src.services.metadata_service import extract_basic_metadata
    with patch("langdetect.detect", side_effect=Exception("no language")):
        result = extract_basic_metadata("This string is long enough to trigger the language detection code path here")
    assert result["language"] is None
    assert result["word_count"] > 0


@pytest.mark.asyncio
async def test_metadata_ai_extraction_with_redis_cache_write():
    import json as _json
    from src.services.metadata_service import extract_ai_metadata
    expected = {"entities": {}, "category": "article", "sentiment": "neutral"}
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_chat_response(_json.dumps(expected))
    )
    mock_redis = MagicMock()
    mock_redis.get = MagicMock(return_value=None)
    mock_redis.setex = MagicMock()
    doc = MagicMock()
    doc.id = "redis-write-id"; doc.title = "T"; doc.content = "C"
    with (
        patch("src.services.metadata_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.metadata_service._get_redis", return_value=mock_redis),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await extract_ai_metadata(doc)
    assert result["category"] == "article"
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_metadata_ai_extraction_openai_failure_returns_empty():
    from src.services.metadata_service import extract_ai_metadata
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("OpenAI down"))
    doc = MagicMock()
    doc.id = "fail-id"; doc.title = "T"; doc.content = "C"
    with (
        patch("src.services.metadata_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.metadata_service._get_redis", return_value=None),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await extract_ai_metadata(doc)
    assert result == {}


@pytest.mark.asyncio
async def test_summarize_openai_fallback_to_extractive():
    from src.services.ai_service import summarize_document
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("all models failed"))
    doc = MagicMock()
    doc.id = "fallback-id"; doc.title = "T"
    doc.content = "First sentence here. Second sentence follows. Third sentence ends."
    with (
        patch("src.services.ai_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.ai_service._get_redis", return_value=None),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await summarize_document(doc, max_length=30)
    assert result.model_used == "extractive-fallback"


@pytest.mark.asyncio
async def test_suggest_tags_openai_failure_returns_error():
    from src.services.ai_service import suggest_tags
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("model error"))
    doc = MagicMock()
    doc.id = "tag-fail"; doc.title = "T"; doc.content = "C"
    with (
        patch("src.services.ai_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.ai_service._get_redis", return_value=None),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await suggest_tags(doc)
    assert result.suggested_tags == []


@pytest.mark.asyncio
async def test_suggest_tags_redis_cache_write():
    import json as _json
    from src.services.ai_service import suggest_tags
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(
        return_value=_make_chat_response('["ml", "ai", "data"]')
    )
    mock_redis = MagicMock()
    mock_redis.get = MagicMock(return_value=None)
    mock_redis.setex = MagicMock()
    doc = MagicMock()
    doc.id = "tags-redis-write"; doc.title = "AI Paper"; doc.content = "Machine learning content"
    with (
        patch("src.services.ai_service.settings") as ms,
        patch("openai.AsyncOpenAI", return_value=mock_client),
        patch("src.services.ai_service._get_redis", return_value=mock_redis),
    ):
        ms.OPENAI_API_KEY = "sk-fake"
        result = await suggest_tags(doc)
    assert set(result.suggested_tags) == {"ml", "ai", "data"}
    mock_redis.setex.assert_called_once()
