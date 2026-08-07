import pytest
from fastapi.testclient import TestClient

from museecho.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)
