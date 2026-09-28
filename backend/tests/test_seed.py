from app.config import AS_OF, OPEN_STAGES, STALE_DAYS
from app.seed import generate


def test_generate_is_deterministic() -> None:
    a = generate(seed=7)
    b = generate(seed=7)
    for df_a, df_b in zip(a[:3], b[:3]):
        assert df_a.equals(df_b)
    assert a[3] == b[3]


def test_volumes_and_injection_rates() -> None:
    companies, leads, activities, truth = generate()
    assert len(companies) == 1500
    assert 4900 <= len(leads) <= 5100
    assert 35_000 <= len(activities) <= 45_000
    assert leads["lead_id"].is_unique and activities["activity_id"].is_unique
    n = len(leads)
    assert 0.03 <= len(truth.duplicates) / n <= 0.05
    assert 0.08 <= len(truth.stale) / n <= 0.12
    assert 0.04 <= len(truth.missing) / n <= 0.06


def test_activities_never_in_future_or_before_lead_created() -> None:
    _, leads, activities, _ = generate()
    joined = activities.merge(leads[["lead_id", "created_at"]], on="lead_id")
    assert (joined["occurred_at"] <= AS_OF).all()
    assert (joined["occurred_at"] >= joined["created_at"]).all()


def test_ground_truth_stale_leads_really_are_stale() -> None:
    _, leads, _, truth = generate()
    stale = leads[leads["lead_id"].isin(truth.stale)]
    assert stale["stage"].isin(OPEN_STAGES).all()
    ref = stale["last_contacted_at"].fillna(stale["created_at"])
    assert ((AS_OF - ref).dt.days >= STALE_DAYS).all()
