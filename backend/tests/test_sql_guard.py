import pytest

from app import sql_guard
from app.seed import GroundTruth


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM leads",
        "SELECT 1; DROP TABLE leads",
        "UPDATE leads SET stage = 'won'",
        "SELECT * FROM actions",
        "SELECT * FROM audit_log",
        "SELECT * FROM read_csv('secrets.csv')",
        "SELECT * FROM information_schema.tables",
        "ATTACH 'other.db'",
        "COPY leads TO 'out.csv'",
        "SELECT * FROM leads WHERE nonexistent_col = 1",
        "",
    ],
)
def test_rejects_unsafe_or_invalid_sql(seeded: GroundTruth, sql: str) -> None:
    with pytest.raises(sql_guard.UnsafeSQL):
        sql_guard.run(sql)


def test_runs_valid_select_with_cte_and_row_cap(seeded: GroundTruth) -> None:
    sql, columns, rows = sql_guard.run(
        "WITH s AS (SELECT lead_id, score FROM lead_scores) SELECT * FROM s ORDER BY score DESC, lead_id;"
    )
    assert not sql.endswith(";")
    assert columns == ["lead_id", "score"]
    assert len(rows) == sql_guard.MAX_ROWS
    assert rows[0]["score"] >= rows[-1]["score"]
