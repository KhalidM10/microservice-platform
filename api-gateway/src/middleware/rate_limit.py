import time
import logging
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from src.core.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"

RATE_LIMITS = {
    "unauthenticated": 10,
    "user": 100,
    "admin": 1000,
}
WINDOW_SECONDS = 60


def _decode_role(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("role", "user")
    except JWTError:
        return "unauthenticated"


class RateLimitMiddleware:
    def __init__(self, app):
        self.app = app
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            except Exception:
                return None
        return self._redis

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        redis = await self._get_redis()

        if redis is None:
            await self.app(scope, receive, send)
            return

        auth_header = request.headers.get("Authorization", "")
        token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""

        if token:
            role = _decode_role(token)
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
                key = f"rate:{payload.get('sub', 'unknown')}"
            except JWTError:
                role = "unauthenticated"
                key = f"rate:{request.client.host}"
        else:
            role = "unauthenticated"
            key = f"rate:{request.client.host}"

        limit = RATE_LIMITS.get(role, RATE_LIMITS["user"])

        try:
            current = await redis.incr(key)
            if current == 1:
                await redis.expire(key, WINDOW_SECONDS)
            ttl = await redis.ttl(key)
        except Exception as exc:
            logger.warning("Redis rate limit error: %s", exc)
            await self.app(scope, receive, send)
            return

        remaining = max(0, limit - current)
        reset_at = int(time.time()) + (ttl if ttl > 0 else WINDOW_SECONDS)

        if current > limit:
            response = JSONResponse(
                status_code=429,
                content={"error": "rate limit exceeded", "retry_after": WINDOW_SECONDS},
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                headers[b"x-ratelimit-limit"] = str(limit).encode()
                headers[b"x-ratelimit-remaining"] = str(remaining).encode()
                headers[b"x-ratelimit-reset"] = str(reset_at).encode()
                message["headers"] = list(headers.items())
            await send(message)

        await self.app(scope, receive, send_with_headers)
