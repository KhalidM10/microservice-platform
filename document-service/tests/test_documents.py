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
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_semantic_search_scoped_to_owner():
    with patch("src.core.publisher.publish_document_created", new_callable=AsyncMock):
        async with await _client_for(USER_A_TOKEN) as ac:
            await ac.post("/api/v1/documents", json={"title": "ML Paper", "content": "Deep learning neural networks"})
        async with await _client_for(USER_B_TOKEN) as ac:
            response = await ac.post("/api/v1/documents/search/semantic", json={"query": "deep learning", "limit": 5})
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == []


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
    results = await semantic_search([], "query", 10)
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

    doc2 = MagicMock()
    doc2.id = "d2"
    doc2.title = "Cooking recipes"
    doc2.content = "How to cook pasta"
    doc2.owner_id = "u1"
    doc2.tags = []

    results = await semantic_search([doc1, doc2], "Python programming", 10)
    assert len(results) >= 1
    assert results[0].id == "d1"
