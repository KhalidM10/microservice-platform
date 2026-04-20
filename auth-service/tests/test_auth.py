import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from src.main import app
from src.core.database import get_db, Base
from src.schemas.user import UserRegister
from src.services import auth_service

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


@pytest_asyncio.fixture
async def registered_user(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "user@example.com",
        "password": "securepass123",
        "full_name": "Test User",
    })
    assert resp.status_code == 201
    return resp.json()


@pytest_asyncio.fixture
async def auth_token(client, registered_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "securepass123",
    })
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_register_valid(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "new@example.com",
        "password": "password123",
        "full_name": "New User",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "new@example.com"
    assert "hashed_password" not in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client, registered_user):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "user@example.com",
        "password": "anotherpass123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_missing_email(client):
    resp = await client.post("/api/v1/auth/register", json={"password": "pass123456"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_register_short_password(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "x@example.com",
        "password": "short",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_valid(client, registered_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "securepass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client, registered_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(client):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@example.com",
        "password": "password123",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client, auth_token):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_get_me_no_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_me_invalid_token(client):
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(client, registered_user):
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "user@example.com",
        "password": "securepass123",
    })
    refresh_token = login_resp.json()["refresh_token"]
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_refresh_invalid_token(client):
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "bad.token"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout(client, auth_token):
    resp = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {auth_token}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


# --- Service layer unit tests ---

@pytest.mark.asyncio
async def test_service_register_and_authenticate(db_session):
    user = await auth_service.register_user(
        db_session, UserRegister(email="svc@example.com", password="password123")
    )
    assert user is not None
    assert user.email == "svc@example.com"

    auth = await auth_service.authenticate_user(db_session, "svc@example.com", "password123")
    assert auth is not None

    bad_auth = await auth_service.authenticate_user(db_session, "svc@example.com", "wrongpass")
    assert bad_auth is None


@pytest.mark.asyncio
async def test_service_register_duplicate(db_session):
    await auth_service.register_user(
        db_session, UserRegister(email="dup@example.com", password="password123")
    )
    result = await auth_service.register_user(
        db_session, UserRegister(email="dup@example.com", password="password456")
    )
    assert result is None


@pytest.mark.asyncio
async def test_service_get_user_by_id(db_session):
    user = await auth_service.register_user(
        db_session, UserRegister(email="byid@example.com", password="password123")
    )
    found = await auth_service.get_user_by_id(db_session, user.id)
    assert found is not None
    not_found = await auth_service.get_user_by_id(db_session, "nonexistent-id")
    assert not_found is None
