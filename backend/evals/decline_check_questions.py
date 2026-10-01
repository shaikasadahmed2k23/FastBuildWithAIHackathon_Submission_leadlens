"""Decline check: a second, small held-out set for the "cannot_answer" path, written before it was run.

Six questions the data cannot answer, chosen outside the categories the SQL prompt names as examples
(churn, likelihood, revenue forecasts, call/email/meeting contents, sentiment), and four answerable
questions near the boundary, to catch over-declining. Never used for tuning.
Expected answers: ``python -m evals.build_golden --set decline_check``.
"""

OPEN = "stage NOT IN ('won', 'lost')"

DECLINE_CHECK: list[tuple[str, str, str, str | None]] = [
    # --- the data has nothing that answers these
    ("decline", "decline", "Which competitors are our leads currently evaluating?", None),
    ("decline", "decline", "What discount did we offer Cruz PLC in our last proposal?", None),
    ("decline", "decline", "How satisfied are our won customers with onboarding?", None),
    ("decline", "decline", "Which leads are based within 50 miles of our office?", None),
    ("decline", "decline", "What is each sales rep's quota attainment this quarter?", None),
    ("decline", "decline", "Which leads prefer to be contacted by phone rather than email?", None),
    # --- answerable, close to the boundary
    ("answerable", "id_set", "Which leads requested a demo but have never been contacted?",
     "SELECT DISTINCT l.lead_id FROM leads l JOIN activities a ON a.lead_id = l.lead_id "
     "WHERE a.type = 'demo_request' AND l.last_contacted_at IS NULL"),
    ("answerable", "scalar", "How many email replies did Priya Nair's leads send in August 2026?",
     "SELECT count(*) FROM activities a JOIN leads l ON l.lead_id = a.lead_id WHERE l.owner = 'Priya Nair' "
     "AND a.type = 'email_reply' AND a.occurred_at >= TIMESTAMP '2026-08-01' AND a.occurred_at < TIMESTAMP '2026-09-01'"),
    ("answerable", "table", "What is the average deal value of won leads in each industry?",
     "SELECT c.industry, avg(l.deal_value) FROM leads l JOIN companies c ON c.company_id = l.company_id "
     "WHERE l.stage = 'won' GROUP BY 1"),
    ("answerable", "id_set", "Which 5 open leads should we call first?",
     f"SELECT l.lead_id FROM leads l JOIN lead_scores s ON s.lead_id = l.lead_id WHERE l.{OPEN} "
     "ORDER BY s.score DESC, l.lead_id LIMIT 5"),
]
