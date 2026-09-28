import pytest

from app import actions, db
from app.seed import GroundTruth


def _count(sql: str, params: list[object]) -> int:
    with db.cursor() as cur:
        return cur.execute(sql, params).fetchone()[0]


def test_merge_moves_activities_and_clears_duplicate_issue(fresh_db: GroundTruth) -> None:
    pair = fresh_db.duplicates[0]
    dup, orig = pair["lead_id"], pair["original_id"]
    total_acts = _count("SELECT count(*) FROM activities WHERE lead_id IN (?, ?)", [dup, orig])

    a = actions.create("merge", [orig, dup], {"primary_id": orig}, "alice")
    assert a.status == "pending"
    assert _count("SELECT count(*) FROM leads WHERE lead_id = ?", [dup]) == 1  # nothing happens before approval

    a = actions.approve(a.action_id, "bob", "confirmed same person")
    assert a.status == "executed" and a.decided_by == "bob"
    assert [e.event.split(":")[0] for e in a.audit] == ["created merge for " + f"{orig}, {dup}", "approved", "executed"]
    assert _count("SELECT count(*) FROM leads WHERE lead_id = ?", [dup]) == 0
    assert _count("SELECT count(*) FROM activities WHERE lead_id = ?", [orig]) == total_acts
    assert _count("SELECT count(*) FROM data_issues WHERE ? IN (lead_id, related_lead_id)", [dup]) == 0
    assert _count("SELECT count(*) FROM lead_scores WHERE lead_id = ?", [dup]) == 0


def test_outreach_clears_staleness_and_rescores(fresh_db: GroundTruth) -> None:
    lead_id = fresh_db.stale[0]
    a = actions.create("outreach", [lead_id], {"subject": "Hi", "body": "Checking in."}, "alice")
    actions.approve(a.action_id, "bob")
    assert _count("SELECT count(*) FROM data_issues WHERE lead_id = ? AND issue_type = 'stale'", [lead_id]) == 0
    assert _count("SELECT recency FROM lead_scores WHERE lead_id = ?", [lead_id]) == 2  # just contacted


def test_stage_change_to_closed_zeroes_recency(fresh_db: GroundTruth) -> None:
    lead_id = fresh_db.stale[1]
    actions.approve(actions.create("stage_change", [lead_id], {"stage": "lost"}, "alice").action_id, "bob")
    assert _count("SELECT count(*) FROM leads WHERE lead_id = ? AND stage = 'lost'", [lead_id]) == 1
    assert _count("SELECT recency FROM lead_scores WHERE lead_id = ?", [lead_id]) == 0
    assert _count("SELECT count(*) FROM data_issues WHERE lead_id = ? AND issue_type = 'stale'", [lead_id]) == 0


def test_reject_changes_nothing(fresh_db: GroundTruth) -> None:
    lead_id = fresh_db.stale[2]
    a = actions.reject(actions.create("stage_change", [lead_id], {"stage": "won"}, "alice").action_id, "bob", "no")
    assert a.status == "rejected" and a.note == "no"
    assert _count("SELECT count(*) FROM leads WHERE lead_id = ? AND stage = 'won'", [lead_id]) == 0


def test_decided_actions_cannot_be_decided_again(fresh_db: GroundTruth) -> None:
    a = actions.create("stage_change", [fresh_db.stale[3]], {"stage": "qualified"}, "alice")
    actions.reject(a.action_id, "bob")
    with pytest.raises(actions.ActionConflict):
        actions.approve(a.action_id, "bob")


def test_execution_failure_is_audited_not_applied(fresh_db: GroundTruth) -> None:
    pair = fresh_db.duplicates[1]
    dup, orig = pair["lead_id"], pair["original_id"]
    first = actions.create("merge", [orig, dup], {"primary_id": orig}, "alice")
    second = actions.create("stage_change", [dup], {"stage": "qualified"}, "alice")
    actions.approve(first.action_id, "bob")
    result = actions.approve(second.action_id, "bob")
    assert result.status == "approved"
    assert "execution failed" in result.audit[-1].event


@pytest.mark.parametrize(
    ("type_", "lead_ids", "payload"),
    [
        ("stage_change", ["LD-00001"], {"stage": "bogus"}),
        ("merge", ["LD-00001"], {}),
        ("merge", ["LD-00001", "LD-00002"], {"primary_id": "LD-00003"}),
        ("outreach", ["LD-00001"], {"subject": "", "body": "x"}),
        ("stage_change", ["LD-99999"], {"stage": "won"}),
        ("stage_change", [], {"stage": "won"}),
    ],
)
def test_invalid_actions_are_refused(fresh_db: GroundTruth, type_: actions.ActionType, lead_ids: list[str],
                                     payload: dict[str, str]) -> None:
    with pytest.raises(actions.ActionError):
        actions.create(type_, lead_ids, payload, "alice")
