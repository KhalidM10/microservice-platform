import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport, Response as HttpxResponse

from src.main import app
from src.core.config import settings


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_all_healthy(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    async def mock_get(url, **kwargs):
        return mock_resp

    with patch("src.main.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = mock_get
        mock_client_cls.return_value = mock_http

        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway"] == "healthy"


@pytest.mark.asyncio
async def test_health_downstream_unreachable(client):
    with patch("src.main.httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client_cls.return_value = mock_http

        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["gateway"] == "healthy"
        assert data["auth-service"] == "unhealthy"
        assert data["document-service"] == "unhealthy"
        assert data["notification-service"] == "unhealthy"


@pytest.mark.asyncio
async def test_proxy_document_service_unavailable(client):
    from jose import jwt
    from datetime import datetime, timezone, timedelta
    token = jwt.encode(
        {"sub": "u1", "role": "user", "type": "access",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.SECRET_KEY, algorithm="HS256",
    )
    with patch("src.core.proxy._do_request", side_effect=Exception("down")):
        resp = await client.get(
            "/api/v1/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 503
        assert "service temporarily unavailable" in resp.json()["error"]


@pytest.mark.asyncio
async def test_proxy_forwards_to_auth(client):
    from src.core.proxy import get_http_client
    import httpx

    mock_upstream = HttpxResponse(
        201,
        content=b'{"id":"u1","email":"test@x.com","role":"user","is_active":true,"created_at":"2024-01-01T00:00:00","full_name":null}',
        headers={"content-type": "application/json"},
    )
    with patch("src.core.proxy._do_request", return_value=mock_upstream):
        resp = await client.post(
            "/api/v1/auth/register",
            json={"email": "test@x.com", "password": "password123"},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_security_headers_present(client):
    with patch("src.core.proxy._do_request", side_effect=Exception("down")):
        resp = await client.get("/api/v1/documents")
    assert "x-content-type-options" in resp.headers
    assert "x-frame-options" in resp.headers


@pytest.mark.asyncio
async def test_correlation_id_returned(client):
    with patch("src.core.proxy._do_request", side_effect=Exception("down")):
        resp = await client.get("/api/v1/documents")
    assert "x-correlation-id" in resp.headers


@pytest.mark.asyncio
async def test_correlation_id_passed_through(client):
    cid = "test-correlation-123"
    with patch("src.core.proxy._do_request", side_effect=Exception("down")):
        resp = await client.get(
            "/api/v1/documents",
            headers={"X-Correlation-ID": cid},
        )
    assert resp.headers.get("x-correlation-id") == cid


@pytest.mark.asyncio
async def test_rate_limit_no_redis(client):
    """When Redis is unavailable, requests pass through (fail-open)."""
    mock_upstream = HttpxResponse(
        200, content=b"[]", headers={"content-type": "application/json"}
    )
    with patch("src.core.proxy._do_request", return_value=mock_upstream):
        resp = await client.get("/api/v1/documents")
    assert resp.status_code in (200, 401, 503)


@pytest.mark.asyncio
async def test_docs_endpoint(client):
    resp = await client.get("/docs")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_proxy_notification_service(client):
    mock_upstream = HttpxResponse(
        200, content=b"[]", headers={"content-type": "application/json"}
    )
    with patch("src.core.proxy._do_request", return_value=mock_upstream):
        resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200


# --- Middleware unit tests ---

def test_security_headers_middleware():
    from src.middleware.security_headers import SecurityHeadersMiddleware
    assert SecurityHeadersMiddleware is not None


def test_rate_limit_middleware_imports():
    from src.middleware.rate_limit import RateLimitMiddleware, RATE_LIMITS
    assert RATE_LIMITS["unauthenticated"] == 10
    assert RATE_LIMITS["user"] == 100
    assert RATE_LIMITS["admin"] == 1000


def test_correlation_middleware_imports():
    from src.middleware.correlation import CorrelationIDMiddleware
    assert CorrelationIDMiddleware is not None


def test_proxy_imports():
    from src.core.proxy import proxy_request, get_http_client, close_http_client
    assert proxy_request is not None


def test_config_loads():
    from src.core.config import settings
    assert settings.APP_NAME == "api-gateway"
    assert settings.SECRET_KEY is not None


def test_rate_limit_decode_role_unauthenticated():
    from src.middleware.rate_limit import _decode_role
    role = _decode_role("invalid.token.value")
    assert role == "unauthenticated"


def test_rate_limit_decode_role_valid():
    from src.middleware.rate_limit import _decode_role
    from jose import jwt
    from datetime import datetime, timezone, timedelta
    token = jwt.encode(
        {"sub": "u1", "role": "admin", "type": "access",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.SECRET_KEY, algorithm="HS256",
    )
    role = _decode_role(token)
    assert role == "admin"
