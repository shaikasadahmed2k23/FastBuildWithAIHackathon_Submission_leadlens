import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.config import settings
from app.ratelimit import limiter
from app.seed import GroundTruth, write_database


@pytest.fixture(scope="session")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GroundTruth]:
    """A freshly seeded database in a temp dir, shared by the whole session."""
    path: Path = tmp_path_factory.mktemp("db") / "test.duckdb"
    original = settings.leadlens_db_path
    settings.leadlens_db_path = str(path)
    truth = write_database(path)
    yield truth
    db.close()
    settings.leadlens_db_path = original


@pytest.fixture
def fresh_db(seeded: GroundTruth, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[GroundTruth]:
    """A private copy of the seeded database for tests that write."""
    db.close()
    copy = tmp_path / "copy.duckdb"
    shutil.copy(settings.db_path, copy)
    monkeypatch.setattr(settings, "leadlens_db_path", str(copy))
    yield seeded
    db.close()


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")


@pytest.fixture(autouse=True)
def isolate_llm_side_effects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with an empty answer cache and rate limiter, and never writes the real call log."""
    monkeypatch.setattr(settings, "llm_log_path", str(tmp_path / "llm_calls.jsonl"))
    monkeypatch.setattr(settings, "llm_rate_limit_per_min", 10_000)
    limiter.reset()
    if db._conn is not None:
        db._conn.execute("DELETE FROM llm_cache")
    yield
