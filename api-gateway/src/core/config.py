from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    APP_NAME: str = "api-gateway"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    REDIS_URL: str = "redis://localhost:6379"
    AUTH_SERVICE_URL: str = "http://auth-service:8000"
    DOCUMENT_SERVICE_URL: str = "http://document-service:8000"
    NOTIFICATION_SERVICE_URL: str = "http://notification-service:8000"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
