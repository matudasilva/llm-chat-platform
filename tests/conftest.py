import pytest
from fastapi.testclient import TestClient

from app.main import app  # ajustá si tu app vive en otro módulo


@pytest.fixture
def client():
    return TestClient(app)
