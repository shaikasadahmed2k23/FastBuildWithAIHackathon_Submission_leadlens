"""Held-out questions: phrased differently from the golden set and never used for tuning.

Expected answers are computed from reference SQL by ``python -m evals.build_golden --set heldout``.
kind "decline" means no query can answer it from this data; the correct behavior is to decline.
"""

from app.config import AS_OF_SQL

OPEN = "stage NOT IN ('won', 'lost')"
LCS = "leads l JOIN companies c ON c.company_id = l.company_id JOIN lead_scores s ON s.lead_id = l.lead_id"

HELDOUT: list[tuple[str, str, str, str | None]] = [
    # --- synonyms
    ("synonym", "scalar", "How many prospects are sitting in the negotiating phase?",
     "SELECT count(*) FROM leads WHERE stage = 'negotiation'"),
    ("synonym", "scalar", "What's the count of deals we closed successfully?",
     "SELECT count(*) FROM leads WHERE stage = 'won'"),
    ("synonym", "scalar", "How many contacts have no phone number on file?",
     "SELECT count(*) FROM leads WHERE phone IS NULL OR trim(phone) = ''"),
    ("synonym", "scalar", "Number of prospects nobody has reached out to yet",
     "SELECT count(*) FROM leads WHERE last_contacted_at IS NULL"),
    ("synonym", "scalar", "What's the mean score of C-suite prospects?",
     "SELECT round(avg(s.score), 1) FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id WHERE l.seniority = 'c_level'"),
    # --- multi-condition filters
    ("multi_filter", "scalar", "How many open Healthcare leads does Daniel Ortiz own?",
     f"SELECT count(*) FROM {LCS} WHERE l.{OPEN} AND c.industry = 'Healthcare' AND l.owner = 'Daniel Ortiz'"),
    ("multi_filter", "id_set", "Which VPs at US logistics companies are in the qualified stage?",
     f"SELECT l.lead_id FROM {LCS} WHERE l.seniority = 'vp' AND c.industry = 'Logistics' AND c.country = 'US' "
     "AND l.stage = 'qualified'"),
    ("multi_filter", "scalar", "How many director-level leads that came from LinkedIn score above 60?",
     f"SELECT count(*) FROM {LCS} WHERE l.seniority = 'director' AND l.source = 'linkedin' AND s.score > 60"),
    ("multi_filter", "id_set", "Which Canadian C-level leads have a score of at least 70?",
     f"SELECT l.lead_id FROM {LCS} WHERE c.country = 'CA' AND l.seniority = 'c_level' AND s.score >= 70"),
    # --- date ranges
    ("date_range", "scalar", "How many leads were created between June 1 and June 30, 2026?",
     "SELECT count(*) FROM leads WHERE created_at >= TIMESTAMP '2026-06-01' AND created_at < TIMESTAMP '2026-07-01'"),
    ("date_range", "scalar", "How many pricing page visits happened in August 2026?",
     "SELECT count(*) FROM activities WHERE type = 'pricing_page_visit' "
     "AND occurred_at >= TIMESTAMP '2026-08-01' AND occurred_at < TIMESTAMP '2026-09-01'"),
    ("date_range", "id_set", "Which Media leads requested a demo during the first week of September 2026 (Sept 1-7)?",
     "SELECT DISTINCT a.lead_id FROM activities a JOIN leads l ON l.lead_id = a.lead_id "
     "JOIN companies c ON c.company_id = l.company_id WHERE c.industry = 'Media' AND a.type = 'demo_request' "
     "AND a.occurred_at >= TIMESTAMP '2026-09-01' AND a.occurred_at < TIMESTAMP '2026-09-08'"),
    ("date_range", "scalar", "How many open leads were last contacted before June 1, 2026?",
     f"SELECT count(*) FROM leads WHERE {OPEN} AND last_contacted_at < TIMESTAMP '2026-06-01'"),
    ("date_range", "scalar", "How many leads flagged as duplicates were created in the past 30 days?",
     f"SELECT count(DISTINCT i.lead_id) FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     f"WHERE i.issue_type = 'duplicate' AND l.created_at >= {AS_OF_SQL} - INTERVAL 30 DAY"),
    # --- top N by X in Y
    ("top_n_by_x", "id_set", "Top 5 leads by deal value in Manufacturing",
     f"SELECT l.lead_id FROM {LCS} WHERE c.industry = 'Manufacturing' AND l.deal_value IS NOT NULL "
     "ORDER BY l.deal_value DESC, l.lead_id LIMIT 5"),
    ("top_n_by_x", "id_set", "Top 3 companies by headcount in Germany",
     "SELECT company_id FROM companies WHERE country = 'DE' ORDER BY employees DESC, company_id LIMIT 3"),
    ("top_n_by_x", "table", "Top 4 industries by average deal value of open leads",
     f"SELECT c.industry, round(avg(l.deal_value), 0) AS avg_deal FROM {LCS} WHERE l.{OPEN} "
     "GROUP BY 1 ORDER BY 2 DESC LIMIT 4"),
    ("synonym", "table", "Won deals per owner",
     "SELECT owner, count(*) FROM leads WHERE stage = 'won' GROUP BY 1"),
    # --- negations
    ("negation", "scalar", "How many leads are not in Software or Fintech?",
     "SELECT count(*) FROM leads l JOIN companies c ON c.company_id = l.company_id "
     "WHERE c.industry NOT IN ('Software', 'Fintech')"),
    ("negation", "scalar", "How many open leads have never had any activity?",
     f"SELECT count(*) FROM leads l WHERE l.{OPEN} AND NOT EXISTS (SELECT 1 FROM activities a WHERE a.lead_id = l.lead_id)"),
    ("negation", "id_set", "Which Education leads in negotiation have no data issues?",
     "SELECT l.lead_id FROM leads l JOIN companies c ON c.company_id = l.company_id "
     "WHERE c.industry = 'Education' AND l.stage = 'negotiation' "
     "AND NOT EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id)"),
    ("negation", "scalar", "How many leads that aren't stale were last contacted more than 60 days ago?",
     f"SELECT count(*) FROM leads l WHERE l.last_contacted_at < {AS_OF_SQL} - INTERVAL 60 DAY "
     "AND NOT EXISTS (SELECT 1 FROM data_issues i WHERE i.lead_id = l.lead_id AND i.issue_type = 'stale')"),
    ("breakdown", "table", "Break down stale leads by stage",
     "SELECT l.stage, count(DISTINCT i.lead_id) FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     "WHERE i.issue_type = 'stale' GROUP BY 1"),
    # --- must decline: the data cannot answer these
    ("decline", "decline", "Which of our leads are most likely to churn next quarter?", None),
    ("decline", "decline", "What did Tom Becker discuss on his last call with each lead?", None),
]
