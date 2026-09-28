from collections.abc import Iterator
from pathlib import Path

import pytest

from app import db
from app.config import settings
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
