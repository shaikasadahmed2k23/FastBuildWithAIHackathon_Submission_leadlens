from app import db
from app.seed import GroundTruth
from evals.build_golden import build
from evals.grading import grade
from evals.questions import QUESTIONS
from evals.run import cleaning_metrics, load_golden


def test_golden_file_matches_current_data(seeded: GroundTruth) -> None:
    """golden.jsonl must be regenerated whenever the seed or schema changes."""
    assert load_golden() == build()
    assert len(QUESTIONS) == 50


def test_grading_rules() -> None:
    assert grade("scalar", 40.2, 40.23)
    assert not grade("scalar", 40.2, 41.0)
    assert grade("id_set", ["LD-1", "LD-2"], ["LD-2", "LD-1"])
    assert not grade("id_set", ["LD-1", "LD-2"], ["LD-1"])
    assert grade("table", {"Software": 43.0}, {"software": 43.02})
    assert not grade("scalar", 1.0, None)


def test_cleaning_metrics_are_perfect_on_fresh_seed(seeded: GroundTruth) -> None:
    with db.cursor():
        metrics = cleaning_metrics(seeded)
    assert all(m["precision"] >= 0.95 and m["recall"] >= 0.95 for m in metrics.values())


def test_heldout_file_matches_current_data(seeded: GroundTruth) -> None:
    from evals.run import EVALS_DIR

    heldout = load_golden(EVALS_DIR / "heldout.jsonl")
    assert heldout == build("heldout")
    assert len(heldout) == 25 and sum(e["kind"] == "decline" for e in heldout) == 2
    golden_questions = {q[2].lower() for q in QUESTIONS}
    assert not any(e["question"].lower() in golden_questions for e in heldout)  # genuinely new phrasings
