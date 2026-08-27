import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.routers.catalog import CATALOG_UNAVAILABLE_DETAIL, logger, router


SENSITIVE_ERROR = (
    "postgresql://catalog_user:secret@example.test:5432/topspot "
    "SELECT * FROM catalog_tracks"
)
SENSITIVE_FRAGMENTS = (
    "postgresql://",
    "catalog_user",
    "secret",
    "example.test",
    "SELECT *",
    "catalog_tracks",
)


class FailingSession:
    def exec(self, _statement):
        raise RuntimeError(SENSITIVE_ERROR)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: FailingSession()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/api/catalog/summary", "/api/catalog/get-json-catalog", "/api/catalog/grouped"])
def test_catalog_failures_are_redacted_from_responses_and_logs(client, caplog, path):
    with caplog.at_level(logging.ERROR, logger=logger.name):
        response = client.get(path)

    assert response.status_code == 500
    assert response.json() == {"detail": CATALOG_UNAVAILABLE_DETAIL}
    assert SENSITIVE_ERROR not in response.text
    assert SENSITIVE_ERROR not in caplog.text
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in response.text
        assert fragment not in caplog.text
