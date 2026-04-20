from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    DATABASE_URL: str
    APP_NAME: str = "notification-service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
