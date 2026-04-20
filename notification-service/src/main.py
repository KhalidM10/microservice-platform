import logging
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from src.core.config import settings
from src.core.database import create_tables
from src.core.consumer import start_consumer
from src.api.routes.notifications import router as notifications_router


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

_rabbitmq_connection = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _rabbitmq_connection
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    await create_tables()
    _rabbitmq_connection = await start_consumer()
    yield
    if _rabbitmq_connection:
        await _rabbitmq_connection.close()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

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

app.include_router(notifications_router, prefix=settings.API_PREFIX)


@app.get("/health")
async def health():
    return {"status": "healthy", "version": settings.APP_VERSION, "service": settings.APP_NAME}
