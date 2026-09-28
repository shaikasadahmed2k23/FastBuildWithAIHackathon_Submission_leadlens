# LeadLens evaluation

This document covers what we measure, how, the results so far, and where the numbers fall short. All numbers here come from the JSON reports in `backend/evals/reports/`. Nothing is typed in by hand.

> **Status:** the rule-based (offline) mode has been evaluated. **The live LLM mode (Groq, `llama-3.3-70b-versatile`) has not been run yet.** Its column below is empty until it is. See [Reproduce](#reproduce).

## What is measured

### 1. Question answering (`/ask`), 50 golden questions

- **Construction.** `backend/evals/questions.py` holds 50 questions in 7 categories (counts, data quality, intent, scoring, pipeline, ranking, breakdown). Each has a hand-written *reference SQL* query. `python -m evals.build_golden` runs every reference query on a freshly seeded database and writes the results to `golden.jsonl`. The expected answers are computed from data, never typed. A test (`tests/test_evals.py`) fails if `golden.jsonl` drifts from what the current data produces.
- **Answer kinds.**
  - `scalar` (25 questions): one number.
  - `id_set` (15): a set of lead/activity IDs.
  - `table` (10): a key-to-number mapping, e.g. stale leads per owner.
- **Grading is on the returned rows, not the prose.**
  - `scalar`: the first number in the first row, within ±0.051 or 0.1% (this allows rounding an average to one decimal).
  - `id_set`: exact set equality.
  - `table`: the same keys, with each value within the same tolerance.
- **The prose is checked separately** by the citation checker, which the app runs on every answer at runtime:
  - Every cited ID must appear in the result rows.
  - Every number must appear in the rows, be the row count, or appear in the question.
  - If the rows contain IDs, the answer must cite at least one.

### 2. Data cleaning, against injected ground truth

The seeder injects known problems and writes them to `backend/data/ground_truth.json`. The eval compares the detected `data_issues` against that file and reports precision, recall and F1 for duplicate pairs, stale leads and missing fields.

### Metric definitions

| Metric | Definition |
|---|---|
| Accuracy | Questions whose returned rows match the golden answer, divided by 50 |
| Citation checker pass | Answers that pass the checker, divided by answers that ran a query (declined questions are excluded) |
| Declined | Questions where no query was run: the offline parser refused, or the LLM and the fallback both failed |
| Retry rate | Questions that needed more than one SQL attempt or more than one answer-writing attempt |
| Fallback rate | Questions whose final answer did not come purely from the LLM. **template** = the LLM's SQL was used but its prose failed the checker twice, so a deterministic summary of the rows was shown. **rules** = the LLM failed (error, or 3 invalid SQL attempts), so the rule-based parser answered. In offline mode this is 0 by definition, since rules are the primary path there, not a fallback. |
| p50 / p95 latency | Nearest-rank percentiles of end-to-end `ask()` time per question, in-process (no HTTP) |
| Variance | The golden set repeated N times on the same database: mean, standard deviation and range of each metric, plus questions that pass in some runs but not others |

## Results

| Metric | Rule-based (offline), 3 runs | Live LLM (Groq) |
|---|---|---|
| Accuracy | **50 / 50** in every run (sd 0.0) | not yet run |
| Citation checker pass | 100% (50 / 50) | not yet run |
| Declined | 0 | not yet run |
| Retry rate | 0% (n/a: no LLM) | not yet run |
| Fallback rate | 0% (n/a: rules are primary) | not yet run |
| Latency p50 / p95 | 8 ms / 14 ms | not yet run |
| Unstable questions | none (the path is deterministic) | not yet run |
| Duplicate detection P / R / F1 | 1.000 / 1.000 / 1.000 (192 pairs) | same (no LLM involved) |
| Stale detection P / R / F1 | 1.000 / 1.000 / 1.000 (480) | same |
| Missing-field detection P / R / F1 | 1.000 / 1.000 / 1.000 (240) | same |

Source: `backend/evals/reports/offline.json`.

## How to read these numbers

**Don't use the rule-based 50/50 as evidence that offline mode generalizes.** The parser was written and fixed while looking at the golden questions. Accuracy went from 22/50 to 47, then 49, then 50 as vocabulary gaps were found. The last fix (Q04, "flagged as duplicates") taught the parser status verbs such as *flagged* and *marked*, which count only when an issue type is also named. It was made after seeing the failure. The golden set is effectively the parser's training set.

Better evidence of how it generalizes is in `tests/test_rules.py`:

- **Held-out phrasings** never seen during development, all of which must answer correctly (7 at present).
- **Questions that must be declined** (4), such as "which leads are most likely to churn" and "how many leads are flagged as spam". The parser is built to refuse rather than guess. A wrong answer with a green "verified" badge would be worse than no answer.

**Perfect cleaning scores reflect synthetic noise.** The duplicate kinds (case changes, one-character typos, Gmail dots) were designed alongside the detector. Real CRM duplicates are messier: nicknames, job changes, shared inboxes. Expect lower recall on real data.

**Latency figures are local and in-process.** Offline latency is DuckDB on a laptop. Live latency will be dominated by Groq calls: two per question, more on retries. On a free-tier key it will also include rate-limit backoff, which inflates p95.

## Known failure cases and limits

- **The checker verifies support, not correctness.** An answer that cites the right rows and repeats their numbers can still describe them wrongly, e.g. calling the lowest score the highest. Grading on returned rows covers the SQL; the prose is only checked for invented IDs and numbers.
- **Numbers glued to units aren't checked.** Tokens like `12d` or `3x` are skipped by the number check.
- **Numbers from the question are always allowed.** If a question says "top 10", an answer may say "10" even if fewer rows came back.
- **Row cap.** Queries return at most 200 rows, so a question whose true answer is larger can't pass an `id_set` check. The golden questions are kept under the cap.
- **One phrasing per question.** The golden set doesn't test paraphrase robustness. For offline mode that's partly covered by the held-out tests; for the LLM it isn't covered yet.
- **Single dataset, single seed.** All results are on seed 42.

## Reproduce

From `backend/`, with the venv active:

```bash
python -m evals.build_golden                                       # rebuild expected answers (only after changing seed/questions)
python -m evals.run --mode offline --runs 3 --out evals/reports/offline.json
python -m evals.run --mode live --runs 3 --out evals/reports/live.json    # needs GROQ_API_KEY in backend/.env
```

Each run seeds a fresh temporary database, so it never touches your working data. Without `--out`, the report goes to `evals/latest.json`, which the UI's Evals page shows. `--limit N` runs only the first N questions, for a quick check.
