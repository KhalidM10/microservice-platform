import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_celery_task():
    """Prevent process_document_ai.delay() from connecting to Redis in every test."""
    with patch("src.tasks.document_tasks.process_document_ai") as mock_task:
        mock_task.delay = MagicMock()
        yield mock_task
