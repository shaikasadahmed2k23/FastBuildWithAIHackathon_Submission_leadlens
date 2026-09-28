from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import GroundTruth


@pytest.fixture
def client(seeded: GroundTruth, offline: None) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def write_client(fresh_db: GroundTruth, offline: None) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["leads"] > 4900 and body["mode"] == "offline"


def test_overview_counts_match_ground_truth(client: TestClient, seeded: GroundTruth) -> None:
    body = client.get("/overview").json()
    issues = {i["issue_type"]: i["count"] for i in body["issues"]}
    assert issues == {"duplicate": len(seeded.duplicates), "stale": len(seeded.stale),
                      "missing_field": len(seeded.missing)}
    assert sum(b["count"] for b in body["score_histogram"]) == body["totals"]["leads"]
    scores = [t["score"] for t in body["top_leads"]]
    assert scores == sorted(scores, reverse=True)


def test_leads_sorting_paging_and_filters(client: TestClient) -> None:
    page1 = client.get("/leads", params={"sort": "score", "order": "desc", "page_size": 20}).json()
    page2 = client.get("/leads", params={"sort": "score", "order": "desc", "page_size": 20, "page": 2}).json()
    assert len(page1["items"]) == 20 and page1["total"] > 4900
    assert page1["items"][-1]["score"] >= page2["items"][0]["score"]
    assert not {i["lead_id"] for i in page1["items"]} & {i["lead_id"] for i in page2["items"]}

    stale = client.get("/leads", params={"issue": "stale", "stage": "new,contacted", "page_size": 200}).json()
    assert stale["total"] > 0
    assert all("stale" in i["issues"] and i["stage"] in ("new", "contacted") for i in stale["items"])

    lead = page1["items"][0]
    found = client.get("/leads", params={"q": lead["lead_id"]}).json()
    assert [i["lead_id"] for i in found["items"]] == [lead["lead_id"]]

    assert client.get("/leads", params={"sort": "drop table"}).status_code == 400


def test_lead_detail_citations_resolve(client: TestClient) -> None:
    lead_id = client.get("/leads", params={"page_size": 1}).json()["items"][0]["lead_id"]
    body = client.get(f"/leads/{lead_id}").json()
    b = body["breakdown"]
    assert b["score"] == round(b["fit"]["points"] + b["intent"]["points"] + b["recency"]["points"], 1)
    assert body["citations"]
    for ref in body["citations"]:
        assert client.get(f"/rows/{ref}").status_code == 200
    assert client.get("/leads/LD-99999").status_code == 404
    assert client.get("/rows/XX-1").status_code == 400


def test_explain_is_cited(client: TestClient) -> None:
    lead_id = client.get("/leads", params={"page_size": 1}).json()["items"][0]["lead_id"]
    body = client.post(f"/leads/{lead_id}/explain").json()
    assert body["valid"] and lead_id in body["citations"]


def test_issues_filter(client: TestClient, seeded: GroundTruth) -> None:
    body = client.get("/issues", params={"type": "duplicate", "page_size": 500}).json()
    assert body["total"] == len(seeded.duplicates)
    assert all(i["related_lead_id"] for i in body["items"])


def test_ask_offline(client: TestClient, seeded: GroundTruth) -> None:
    body = client.post("/ask", json={"question": "how many leads are missing phone"}).json()
    expected = sum(1 for m in seeded.missing if m["field"] == "phone")
    assert body["valid"] and body["rows"] == [{"lead_count": expected}] and body["sql"]
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_action_endpoints(write_client: TestClient, seeded: GroundTruth) -> None:
    lead_id = seeded.stale[0]
    created = write_client.post("/actions", json={"type": "outreach", "lead_ids": [lead_id], "actor": "alice"})
    assert created.status_code == 201
    action = created.json()
    assert action["status"] == "pending" and action["payload"]["subject"] and lead_id in action["payload"]["citations"]

    assert [a["action_id"] for a in write_client.get("/actions", params={"status": "pending"}).json()] == [action["action_id"]]
    approved = write_client.post(f"/actions/{action['action_id']}/approve", json={"actor": "bob"}).json()
    assert approved["status"] == "executed"
    assert write_client.post(f"/actions/{action['action_id']}/reject", json={"actor": "bob"}).status_code == 409
    assert write_client.post("/actions/AX-99999/approve", json={}).status_code == 404
    bad = write_client.post("/actions", json={"type": "stage_change", "lead_ids": [lead_id], "payload": {"stage": "x"}})
    assert bad.status_code == 400
    detail = write_client.get(f"/leads/{lead_id}").json()
    assert detail["actions"][0]["action_id"] == action["action_id"]
    assert "stale" not in detail["lead"]["issues"]


def test_health_reports_llm_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import llm
    from app.config import settings

    assert client.get("/health").json()["llm_status"] == "none"
    monkeypatch.setattr(settings, "groq_api_key", "test")
    monkeypatch.setitem(llm.last_call, "ok", False)
    body = client.get("/health").json()
    assert body["llm"] == "groq" and body["llm_status"] == "failing"
    monkeypatch.setitem(llm.last_call, "ok", True)
    assert client.get("/health").json()["llm_status"] == "ok"
