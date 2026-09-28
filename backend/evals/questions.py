"""Golden questions with reference SQL. Expected answers are computed, never typed.

kind:
  scalar - a single number (first numeric cell of the first row)
  id_set - the set of IDs returned (order-insensitive)
  table  - {key: number} pairs (first text column -> first numeric column)
"""

from app.config import AS_OF_SQL

OPEN = "stage NOT IN ('won', 'lost')"
SCORED = "leads l JOIN lead_scores s ON s.lead_id = l.lead_id JOIN companies c ON c.company_id = l.company_id"

QUESTIONS: list[tuple[str, str, str, str]] = [
    # (category, kind, question, reference_sql)
    ("counts", "scalar", "How many leads are there in total?", "SELECT count(*) FROM leads"),
    ("counts", "scalar", "How many open leads are there?", f"SELECT count(*) FROM leads WHERE {OPEN}"),
    ("data_quality", "scalar", "How many stale leads are there?",
     "SELECT count(DISTINCT lead_id) FROM data_issues WHERE issue_type = 'stale'"),
    ("data_quality", "scalar", "How many leads are flagged as duplicates?",
     "SELECT count(DISTINCT lead_id) FROM data_issues WHERE issue_type = 'duplicate'"),
    ("data_quality", "scalar", "How many leads are missing an email address?",
     "SELECT count(*) FROM leads WHERE email IS NULL OR trim(email) = ''"),
    ("data_quality", "scalar", "How many leads are missing a phone number?",
     "SELECT count(*) FROM leads WHERE phone IS NULL OR trim(phone) = ''"),
    ("data_quality", "scalar", "How many leads are missing a job title?",
     "SELECT count(*) FROM leads WHERE title IS NULL OR trim(title) = ''"),
    ("counts", "scalar", "How many leads are in the negotiation stage?",
     "SELECT count(*) FROM leads WHERE stage = 'negotiation'"),
    ("counts", "scalar", "How many leads does Maya Chen own?", "SELECT count(*) FROM leads WHERE owner = 'Maya Chen'"),
    ("counts", "scalar", "How many companies are in the Fintech industry?",
     "SELECT count(*) FROM companies WHERE industry = 'Fintech'"),
    ("intent", "scalar", "How many leads requested a demo in the last 7 days?",
     f"SELECT count(DISTINCT lead_id) FROM activities WHERE type = 'demo_request' AND occurred_at >= {AS_OF_SQL} - INTERVAL 7 DAY"),
    ("intent", "scalar", "How many leads visited the pricing page in the last 30 days?",
     f"SELECT count(DISTINCT lead_id) FROM activities WHERE type = 'pricing_page_visit' AND occurred_at >= {AS_OF_SQL} - INTERVAL 30 DAY"),
    ("counts", "scalar", "How many leads have never been contacted?",
     "SELECT count(*) FROM leads WHERE last_contacted_at IS NULL"),
    ("scoring", "scalar", "How many leads have a score above 80?", "SELECT count(*) FROM lead_scores WHERE score > 80"),
    ("scoring", "scalar", "What is the average lead score?", "SELECT round(avg(score), 1) FROM lead_scores"),
    ("pipeline", "scalar", "What is the total deal value of open leads?",
     f"SELECT round(sum(deal_value), 0) FROM leads WHERE {OPEN}"),
    ("intent", "scalar", "How many activities were recorded in the last 30 days?",
     f"SELECT count(*) FROM activities WHERE occurred_at >= {AS_OF_SQL} - INTERVAL 30 DAY"),
    ("counts", "scalar", "How many leads were won?", "SELECT count(*) FROM leads WHERE stage = 'won'"),
    ("counts", "scalar", "How many leads came from referrals?", "SELECT count(*) FROM leads WHERE source = 'referral'"),
    ("counts", "scalar", "How many C-level leads are there?", "SELECT count(*) FROM leads WHERE seniority = 'c_level'"),
    ("scoring", "scalar", "What is the highest lead score?", "SELECT max(score) FROM lead_scores"),
    ("data_quality", "scalar", "How many stale leads does Tom Becker own?",
     "SELECT count(DISTINCT i.lead_id) FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     "WHERE i.issue_type = 'stale' AND l.owner = 'Tom Becker'"),
    ("counts", "scalar", "How many companies have more than 1000 employees?",
     "SELECT count(*) FROM companies WHERE employees > 1000"),
    ("counts", "scalar", "How many leads work at companies based in Germany?",
     "SELECT count(*) FROM leads l JOIN companies c ON c.company_id = l.company_id WHERE c.country = 'DE'"),
    ("pipeline", "scalar", "What is the average deal value of won leads?",
     "SELECT round(avg(deal_value), 0) FROM leads WHERE stage = 'won'"),

    ("ranking", "id_set", "Who are the top 10 leads by score?",
     "SELECT l.lead_id FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id ORDER BY s.score DESC, l.lead_id LIMIT 10"),
    ("ranking", "id_set", "Top 5 open leads in Fintech",
     f"SELECT l.lead_id FROM {SCORED} WHERE c.industry = 'Fintech' AND l.{OPEN} ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("ranking", "id_set", "Top 5 leads owned by Priya Nair",
     f"SELECT l.lead_id FROM {SCORED} WHERE l.owner = 'Priya Nair' ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("intent", "id_set", "Which Fintech leads requested a demo in the last 3 days?",
     f"SELECT DISTINCT a.lead_id FROM activities a JOIN leads l ON l.lead_id = a.lead_id "
     f"JOIN companies c ON c.company_id = l.company_id WHERE c.industry = 'Fintech' "
     f"AND a.type = 'demo_request' AND a.occurred_at >= {AS_OF_SQL} - INTERVAL 3 DAY"),
    ("data_quality", "id_set", "Top 10 stale leads by score",
     "SELECT i.lead_id FROM data_issues i JOIN lead_scores s ON s.lead_id = i.lead_id "
     "WHERE i.issue_type = 'stale' ORDER BY s.score DESC, i.lead_id LIMIT 10"),
    ("data_quality", "id_set", "Which leads are missing an email address?",
     "SELECT lead_id FROM leads WHERE email IS NULL OR trim(email) = ''"),
    ("ranking", "id_set", "Top 5 leads in the proposal stage",
     f"SELECT l.lead_id FROM {SCORED} WHERE l.stage = 'proposal' ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("ranking", "id_set", "Top 5 C-level leads at Software companies",
     f"SELECT l.lead_id FROM {SCORED} WHERE l.seniority = 'c_level' AND c.industry = 'Software' "
     "ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("pipeline", "id_set", "Which leads at companies with more than 5000 employees are in negotiation?",
     "SELECT l.lead_id FROM leads l JOIN companies c ON c.company_id = l.company_id "
     "WHERE c.employees > 5000 AND l.stage = 'negotiation'"),
    ("ranking", "id_set", "Top 5 leads at UK companies",
     f"SELECT l.lead_id FROM {SCORED} WHERE c.country = 'GB' ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("data_quality", "id_set", "Which duplicate leads belong to Aisha Bello?",
     "SELECT DISTINCT i.lead_id FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     "WHERE i.issue_type = 'duplicate' AND l.owner = 'Aisha Bello'"),
    ("ranking", "id_set", "Top 5 leads that came from events",
     f"SELECT l.lead_id FROM {SCORED} WHERE l.source = 'event' ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("pipeline", "id_set", "Which open leads have a deal value over 60000?",
     f"SELECT lead_id FROM leads WHERE {OPEN} AND deal_value > 60000"),
    ("ranking", "id_set", "Top 5 never-contacted leads by score",
     "SELECT l.lead_id FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id "
     "WHERE l.last_contacted_at IS NULL ORDER BY s.score DESC, l.lead_id LIMIT 5"),
    ("intent", "id_set", "Which Healthcare leads had a meeting in the last 2 days?",
     f"SELECT DISTINCT a.lead_id FROM activities a JOIN leads l ON l.lead_id = a.lead_id "
     f"JOIN companies c ON c.company_id = l.company_id WHERE c.industry = 'Healthcare' "
     f"AND a.type = 'meeting' AND a.occurred_at >= {AS_OF_SQL} - INTERVAL 2 DAY"),

    ("breakdown", "table", "How many leads does each owner have?",
     "SELECT owner, count(*) FROM leads GROUP BY 1"),
    ("breakdown", "table", "Lead count by stage", "SELECT stage, count(*) FROM leads GROUP BY 1"),
    ("breakdown", "table", "Average lead score by industry",
     f"SELECT c.industry, round(avg(s.score), 1) FROM {SCORED} GROUP BY 1"),
    ("data_quality", "table", "Number of stale leads per owner",
     "SELECT l.owner, count(DISTINCT i.lead_id) FROM data_issues i JOIN leads l ON l.lead_id = i.lead_id "
     "WHERE i.issue_type = 'stale' GROUP BY 1"),
    ("breakdown", "table", "How many leads per source?", "SELECT source, count(*) FROM leads GROUP BY 1"),
    ("intent", "table", "Number of demo requests per industry in the last 30 days",
     f"SELECT c.industry, count(*) FROM activities a JOIN leads l ON l.lead_id = a.lead_id "
     f"JOIN companies c ON c.company_id = l.company_id WHERE a.type = 'demo_request' "
     f"AND a.occurred_at >= {AS_OF_SQL} - INTERVAL 30 DAY GROUP BY 1"),
    ("pipeline", "table", "Total open pipeline deal value by owner",
     f"SELECT owner, round(sum(deal_value), 0) FROM leads WHERE {OPEN} GROUP BY 1"),
    ("breakdown", "table", "How many leads are there per seniority level?",
     "SELECT seniority, count(*) FROM leads GROUP BY 1"),
    ("data_quality", "table", "Count of data issues by type",
     "SELECT issue_type, count(*) FROM data_issues GROUP BY 1"),
    ("breakdown", "table", "Average lead score by company country",
     f"SELECT c.country, round(avg(s.score), 1) FROM {SCORED} GROUP BY 1"),
]
