import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import cache, db, importer
from app.config import DATA_DIR
from app.main import app
from app.seed import GroundTruth

SAMPLE = DATA_DIR / "sample_hubspot_export.csv"


def test_hubspot_headers_are_mapped() -> None:
    headers = ["Record ID", "First Name", "Last Name", "Email", "Phone Number", "Job Title", "Company Name",
               "Company Domain Name", "Lead Status", "Lifecycle Stage", "Create Date", "Amount"]
    m = importer.propose_mapping(headers)
    assert m["email"] == "Email" and m["company"] == "Company Name" and m["domain"] == "Company Domain Name"
    assert m["stage"] == "Lead Status"  # preferred over Lifecycle Stage
    assert m["deal_value"] == "Amount" and m["created_at"] == "Create Date" and m["industry"] is None


def test_salesforce_headers_are_mapped() -> None:
    headers = ["FirstName", "LastName", "Email", "Phone", "Title", "Company", "Website", "LeadSource", "Status",
               "NumberOfEmployees", "CreatedDate", "Owner Name"]
    m = importer.propose_mapping(headers)
    assert (m["first_name"], m["company"], m["domain"], m["source"], m["stage"], m["owner"]) == (
        "FirstName", "Company", "Website", "LeadSource", "Status", "Owner Name")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [({"Lead Status": "Open Deal"}, "proposal"), ({"Lead Status": "Closed - Converted"}, "won"),
     ({"Lead Status": "Unqualified"}, "lost"), ({"Lead Status": "Nurture"}, "new")],
)
def test_stage_values_are_normalized(raw: dict[str, str], expected: str) -> None:
    row = {"Company": "Acme", "Email": "a@acme.com", **raw}
    out = importer.transform_row(row, {**{t: None for t in importer.SYNONYMS}, "company": "Company",
                                       "email": "Email", "stage": "Lead Status"})
    assert out.record is not None and out.record["stage"] == expected
    assert bool(out.warnings) == (raw["Lead Status"] == "Nurture") or raw["Lead Status"] != "Nurture"


def test_row_values_are_cleaned() -> None:
    mapping = {**{t: None for t in importer.SYNONYMS}, "company": "c", "email": "e", "title": "t",
               "employees": "n", "deal_value": "a", "country": "k", "domain": "d", "created_at": "cd"}
    out = importer.transform_row({"c": "Acme", "e": "x@acme.com", "t": "VP of Sales", "n": "51-200",
                                  "a": "$12,500.00", "k": "United Kingdom", "d": "https://www.Acme.com/",
                                  "cd": "3/14/2026"}, mapping)
    r = out.record
    assert r is not None
    assert (r["seniority"], r["employees"], r["deal_value"], r["country"], r["domain"]) == (
        "vp", 125, 12500.0, "GB", "acme.com")
    assert r["created_at"].month == 3


def test_invalid_rows_list_every_reason() -> None:
    mapping = {**{t: None for t in importer.SYNONYMS}, "company": "c", "email": "e", "deal_value": "a"}
    out = importer.transform_row({"c": "", "e": "bad@", "a": "TBD"}, mapping)
    assert out.record is None
    assert sorted(out.reasons) == sorted(["invalid email 'bad@'", "no company", "deal value 'TBD' is not a number"])


def test_preview_matches_sample_file() -> None:
    p = importer.preview(SAMPLE.read_bytes(), SAMPLE.name)
    assert p.rows == 300 and p.will_reject == 12
    assert set(p.unmapped_headers) == {"Record ID", "Lifecycle Stage"}


def test_import_sample_runs_cleaning_and_scoring(fresh_db: GroundTruth) -> None:
    with db.cursor() as cur:
        leads_before = cur.execute("SELECT count(*) FROM leads").fetchone()[0]
        version_before = cache.data_version(cur)
    p = importer.preview(SAMPLE.read_bytes(), SAMPLE.name)
    result = importer.run_import(SAMPLE.read_bytes(), SAMPLE.name, p.mapping, "tester")

    assert result.imported == 288 and len(result.rejected) == 12
    # Re-exports of existing CRM leads must attach to the same company as the original lead.
    with db.cursor() as cur:
        pairs = cur.execute(
            """SELECT imp.company_id = orig.company_id FROM leads imp JOIN leads orig
               ON lower(imp.email) = lower(orig.email) AND imp.lead_id <> orig.lead_id
               WHERE imp.lead_id IN (SELECT unnest(?)) AND orig.lead_id NOT IN (SELECT unnest(?))""",
            [result.lead_ids, result.lead_ids]).fetchall()
    assert len(pairs) == 10 and all(same for (same,) in pairs)
    assert result.matched_companies >= 10
    # 10 in-file duplicates + 10 re-exports of existing leads
    assert result.issues["duplicate"] == 30  # 10 pairs inside the file (20 leads) + 10 matched to existing leads
    with db.cursor() as cur:
        assert cur.execute("SELECT count(*) FROM leads").fetchone()[0] == leads_before + 288
        scored = cur.execute("SELECT count(*) FROM lead_scores WHERE lead_id IN (SELECT unnest(?))",
                             [result.lead_ids]).fetchone()[0]
        assert scored == 288
        assert cache.data_version(cur) == version_before + 1  # cached answers are invalidated
        audit = cur.execute("SELECT event FROM audit_log WHERE action_id = ?", [result.batch_id]).fetchone()[0]
    assert "imported 288 leads" in audit


def test_mapping_without_company_is_refused(fresh_db: GroundTruth) -> None:
    p = importer.preview(SAMPLE.read_bytes(), SAMPLE.name)
    with pytest.raises(importer.ImportRejected):
        importer.run_import(SAMPLE.read_bytes(), SAMPLE.name, {**p.mapping, "company": None}, "tester")


@pytest.fixture
def client(fresh_db: GroundTruth, offline: None) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_import_endpoints(client: TestClient) -> None:
    files = {"file": (SAMPLE.name, SAMPLE.read_bytes(), "text/csv")}
    preview = client.post("/import/preview", files=files).json()
    assert preview["rows"] == 300
    resp = client.post("/import", files=files, data={"mapping": json.dumps(preview["mapping"]), "actor": "alice"})
    assert resp.status_code == 200 and resp.json()["imported"] == 288
    lead_id = resp.json()["lead_ids"][0]
    assert client.get(f"/leads/{lead_id}").status_code == 200

    assert client.post("/import/preview", files={"file": ("x.txt", b"a,b\n1,2", "text/plain")}).status_code == 400
    assert client.post("/import/preview", files={"file": ("x.csv", b"only_one_column\n1", "text/csv")}).status_code == 400
    assert client.post("/import", files=files, data={"mapping": "not json"}).status_code == 400
