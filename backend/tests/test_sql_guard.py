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


def test_using_joins_are_accepted(seeded: GroundTruth) -> None:
    # Regression: DuckDB 1.5's get_table_names wrongly rejects valid USING joins.
    _, _, rows = sql_guard.run(
        "WITH top AS (SELECT l.lead_id, s.score FROM leads l JOIN lead_scores s USING (lead_id)) "
        "SELECT * FROM top ORDER BY score DESC, lead_id LIMIT 3"
    )
    assert len(rows) == 3


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM leads WHERE lead_id IN (SELECT column0 FROM read_csv('x.csv'))",  # nested table function
        "SELECT * FROM range(10)",  # any table function, not just blocklisted names
        "WITH audit_log AS (SELECT 1 AS x) SELECT * FROM audit_log",  # CTE shadowing a protected table
        "SELECT * FROM other_schema.leads",
        "SELEC lead_id FROM leads",
    ],
)
def test_parse_tree_guard_rejects(seeded: GroundTruth, sql: str) -> None:
    with pytest.raises(sql_guard.UnsafeSQL):
        sql_guard.run(sql)
