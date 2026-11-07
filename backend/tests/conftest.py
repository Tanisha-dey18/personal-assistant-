import os
import shutil
import tempfile

_tmp = tempfile.mkdtemp(prefix="astra-test-")
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{_tmp}/test.db".replace("\\", "/"),
    "DATABASE_URL_UNPOOLED": "",
    "QDRANT_URL": "",
    "QDRANT_PATH": f"{_tmp}/qdrant",
    "REDIS_URL": "",
    "EMBEDDING_DIM": "256",
    "PROACTIVE_INTERVAL_SECONDS": "0",
    "OPENAI_API_KEY": "",
    "RATE_LIMIT_PER_MINUTE": "1000",
    "AUTH_RATE_LIMIT_PER_MINUTE": "1000",
    "SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.ai.provider import set_provider_override  # noqa: E402
from tests.fake_provider import FakeProvider  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app

    set_provider_override(FakeProvider())
    with TestClient(app) as c:
        yield c
    set_provider_override(None)
    shutil.rmtree(_tmp, ignore_errors=True)


_n = 0


@pytest.fixture
def auth(client):
    """Registers a fresh user and returns auth headers."""
    global _n
    _n += 1
    r = client.post("/api/auth/register", json={"email": f"user{_n}@test.dev", "password": "supersecret1", "name": f"User{_n}"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["token"]
