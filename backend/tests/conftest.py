import pytest
from fastapi.testclient import TestClient

from app.authz import Actor
from app.config import Settings
from app.db import Database
from app.hr_service import HRService
from app.main import create_app, sign_token


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "t.db"))
    database.init("pw")
    return database


@pytest.fixture
def hr(db):
    return HRService(db)


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "api.db"), token_secret="test-secret", demo_password="pw", llm_mode="rules")


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


@pytest.fixture
def auth(settings):
    def _headers(employee_id: str) -> dict:
        return {"Authorization": f"Bearer {sign_token(settings.token_secret, employee_id, 600)}"}
    return _headers


EMPLOYEE = Actor("E1005", "employee")  # reports to manager E1003
PEER = Actor("E1006", "employee")
MANAGER = Actor("E1003", "manager")
OTHER_MANAGER = Actor("E1004", "manager")
HR_USER = Actor("E1002", "hr")
