import logging
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from src.core.config import settings
from src.core.proxy import proxy_request, close_http_client
from src.middleware.correlation import CorrelationIDMiddleware
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.security_headers import SecurityHeadersMiddleware


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": settings.APP_NAME,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    yield
    await close_http_client()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app)

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
_tracer_provider = TracerProvider()
trace.set_tracer_provider(_tracer_provider)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health():
    results = {"gateway": "healthy"}
    services = {
        "auth-service": settings.AUTH_SERVICE_URL,
        "document-service": settings.DOCUMENT_SERVICE_URL,
        "notification-service": settings.NOTIFICATION_SERVICE_URL,
    }
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in services.items():
            try:
                resp = await client.get(f"{url}/health")
                results[name] = "healthy" if resp.status_code == 200 else "unhealthy"
            except Exception:
                results[name] = "unhealthy"
    return results


@app.api_route("/api/v1/auth/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def auth_proxy(request: Request):
    return await proxy_request(request, settings.AUTH_SERVICE_URL, "auth-service")


@app.api_route("/api/v1/documents/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def documents_proxy(request: Request):
    return await proxy_request(request, settings.DOCUMENT_SERVICE_URL, "document-service")


@app.api_route("/api/v1/documents", methods=["GET", "POST"])
async def documents_root_proxy(request: Request):
    return await proxy_request(request, settings.DOCUMENT_SERVICE_URL, "document-service")


@app.api_route("/api/v1/notifications/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def notifications_proxy(request: Request):
    return await proxy_request(request, settings.NOTIFICATION_SERVICE_URL, "notification-service")


@app.api_route("/api/v1/notifications", methods=["GET", "POST"])
async def notifications_root_proxy(request: Request):
    return await proxy_request(request, settings.NOTIFICATION_SERVICE_URL, "notification-service")
