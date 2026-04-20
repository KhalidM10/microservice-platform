import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import get_db, Base
from src.services import notification_service

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine_test = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(engine_test, expire_on_commit=False)


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


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_session():
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest.mark.asyncio
async def test_list_notifications_empty(client):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_notifications_with_data(client, db_session):
    await notification_service.create_notification(
        db_session, event_type="document.created",
        message="Doc created", document_id="doc-1", owner_id="user-1",
    )
    await db_session.commit()

    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_list_notifications_filter_by_owner(client, db_session):
    await notification_service.create_notification(
        db_session, event_type="document.created", message="Msg 1", owner_id="user-1"
    )
    await notification_service.create_notification(
        db_session, event_type="document.created", message="Msg 2", owner_id="user-2"
    )
    await db_session.commit()

    resp = await client.get("/api/v1/notifications?owner_id=user-1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["owner_id"] == "user-1"


@pytest.mark.asyncio
async def test_mark_as_read(client, db_session):
    notification = await notification_service.create_notification(
        db_session, event_type="document.created", message="Test"
    )
    await db_session.commit()

    resp = await client.put(f"/api/v1/notifications/{notification.id}/read")
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True


@pytest.mark.asyncio
async def test_mark_as_read_not_found(client):
    resp = await client.put("/api/v1/notifications/nonexistent-id/read")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# --- Service layer unit tests ---

@pytest.mark.asyncio
async def test_service_create_notification(db_session):
    n = await notification_service.create_notification(
        db_session, event_type="document.created",
        message="Hello", document_id="doc-1", owner_id="user-1"
    )
    assert n.id is not None
    assert n.is_read is False


@pytest.mark.asyncio
async def test_service_list_notifications(db_session):
    await notification_service.create_notification(db_session, event_type="e", message="m1")
    await notification_service.create_notification(db_session, event_type="e", message="m2")
    results = await notification_service.list_notifications(db_session)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_service_mark_as_read(db_session):
    n = await notification_service.create_notification(db_session, event_type="e", message="m")
    updated = await notification_service.mark_as_read(db_session, n.id)
    assert updated.is_read is True


@pytest.mark.asyncio
async def test_service_mark_as_read_not_found(db_session):
    result = await notification_service.mark_as_read(db_session, "no-id")
    assert result is None


# --- Consumer unit tests ---

@pytest.mark.asyncio
async def test_handle_document_created_valid():
    from src.core.consumer import handle_document_created

    payload = {
        "event": "document.created",
        "document_id": "doc-123",
        "title": "Test Doc",
        "owner_id": "user-1",
    }
    message = MagicMock()
    message.body = json.dumps(payload).encode()
    message.process = MagicMock(return_value=AsyncMock().__aenter__.return_value)
    message.process.__aenter__ = AsyncMock(return_value=None)
    message.process.__aexit__ = AsyncMock(return_value=False)

    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)

    with patch("src.core.consumer.AsyncSessionLocal", return_value=session_mock), \
         patch("src.core.consumer.create_notification", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = MagicMock()
        await handle_document_created(message)
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs[1]["document_id"] == "doc-123" or call_kwargs[0][2] == "doc-123"


@pytest.mark.asyncio
async def test_start_consumer_rabbitmq_unavailable():
    from src.core.consumer import start_consumer
    with patch("aio_pika.connect_robust", side_effect=Exception("Connection refused")):
        result = await start_consumer()
        assert result is None
