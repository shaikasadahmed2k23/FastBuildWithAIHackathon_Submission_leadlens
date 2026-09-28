from app.citations import check, extract_ids

ROWS = [
    {"lead_id": "LD-00012", "name": "Ana Ruiz", "score": 91.25, "created_at": "2026-01-02 10:00"},
    {"lead_id": "LD-00034", "name": "Bo Chen", "score": 88.0, "created_at": "2026-02-03 11:00"},
]


def test_extract_ids_dedupes_in_order() -> None:
    assert extract_ids("[LD-00012] then [ACT-00001] and LD-00012") == ["LD-00012", "ACT-00001"]


def test_valid_answer_passes() -> None:
    report = check("Ana Ruiz [LD-00012] leads with a score of 91.25, then Bo Chen [LD-00034] at 88.", ROWS)
    assert report.valid, report.reason
    assert report.cited == ["LD-00012", "LD-00034"]


def test_rounded_numbers_are_accepted() -> None:
    assert check("Top score is 91.3 [LD-00012].", ROWS).valid


def test_hallucinated_id_is_rejected() -> None:
    report = check("Top lead is [LD-99999].", ROWS)
    assert not report.valid and report.unknown_ids == ["LD-99999"]


def test_invented_number_is_rejected() -> None:
    report = check("Ana Ruiz [LD-00012] has a score of 95.", ROWS)
    assert not report.valid and report.unsupported_numbers == ["95"]


def test_computed_number_is_rejected() -> None:
    # 91.25 + 88 = 179.25 is arithmetic the LLM must not do.
    assert not check("Together they score 179.25 [LD-00012].", ROWS).valid


def test_row_count_and_question_numbers_are_allowed() -> None:
    assert check("Found 2 leads, e.g. [LD-00034].", ROWS).valid
    assert check("Among the top 10, [LD-00012] leads.", ROWS, extra_numbers=[10]).valid


def test_uncited_claims_are_rejected_when_rows_have_ids() -> None:
    assert not check("Ana Ruiz is the best lead.", ROWS).valid


def test_aggregate_without_ids_needs_no_citation() -> None:
    assert check("There are 480 stale leads.", [{"lead_count": 480}]).valid
    assert not check("There are 481 stale leads.", [{"lead_count": 480}]).valid


def test_dates_and_percentages() -> None:
    assert check("Created on 2026-01-02 [LD-00012].", ROWS).valid
    assert check("Conversion is 25% overall.", [{"rate": 0.25}]).valid
