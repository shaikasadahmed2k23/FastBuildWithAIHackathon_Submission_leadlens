# LeadLens evaluation

This document covers what we measure, how, the results, and where the numbers fall short. Every number here comes from the JSON reports in `backend/evals/reports/` (`offline.json`, `live.json`). None are typed in by hand.

## Summary

| | Rule-based (offline) | Live LLM (Groq `openai/gpt-oss-120b`) |
|---|---|---|
| Golden accuracy, 3 runs | 50/50 every run | 50/50 every run (see the run 3 caveat) |
| Answers passing the citation checker | 100% | 100% |
| Wrong answers across 150 attempts | 0 | 0 |
| **Held-out accuracy (25 new questions, never tuned on)** | **5/25**; 3 of its 6 answers were wrong | *pending: provider quota* |
| Held-out, after strict-fallback policy | **4/25, 0 wrong answers** (21 declined) | n/a (policy applies to the offline parser only) |

**Read the held-out row first.** The golden set was used to find and fix problems, so 50/50 on it is an upper bound. The held-out set is the honest test of generalization, and the rule-based fallback does poorly on it.

The most important caveat: in live run 3, the provider quota ran out partway through and 17 of the 50 questions fell back. Its 50/50 therefore includes 14 answers from the rule-based parser, which was tuned on these same questions. The LLM's own record is 50/50, 50/50 and 36/36 (the questions it answered in run 3).

**Model note.** The project spec names `llama-3.3-70b-versatile`. Groq no longer serves it (`model_not_found`), and the account has no Llama models. The live results use `openai/gpt-oss-120b` with `reasoning_effort=low`, the largest general model available. Gemini `gemini-3.8-flash` is configured as the fallback provider.

## What is measured

### 1. Question answering (`/ask`), 50 golden questions

- **Construction.** `backend/evals/questions.py` holds 50 questions in 7 categories (counts, data quality, intent, scoring, pipeline, ranking, breakdown). Each has a hand-written *reference SQL* query. `python -m evals.build_golden` runs every reference query on a freshly seeded database and writes the results to `golden.jsonl`. The expected answers are computed from data, never typed. A test fails if `golden.jsonl` drifts from what the current data produces.
- **Answer kinds.**
  - `scalar` (25 questions): one number.
  - `id_set` (15): a set of lead/activity IDs.
  - `table` (10): a key-to-number mapping, e.g. stale leads per owner.
- **Grading is on the returned rows, not the prose.**
  - `scalar`: the first number in the first row, within ±0.051 or 0.1%.
  - `id_set`: exact set equality.
  - `table`: the same keys, with each value within tolerance.
- **The prose is checked by the citation checker**, which the app runs on every answer at runtime:
  - Every cited ID must appear in the result rows.
  - Anything in square brackets must be a real row ID.
  - Every number must appear in the rows, be the row count, or appear in the question.
  - If the rows contain IDs, the answer must cite at least one.

### 2. Data cleaning, against injected ground truth

Detected `data_issues` are compared with `backend/data/ground_truth.json`, written by the seeder. The eval reports precision, recall and F1 for duplicate pairs, stale leads and missing fields. No LLM is involved, so both modes score the same.

### Metric definitions

| Metric | Definition |
|---|---|
| Accuracy | Questions whose returned rows match the golden answer, divided by 50 |
| Citation checker pass | Answers that pass the checker, divided by answers that ran a query |
| Retry rate | Questions that needed more than one SQL attempt or more than one answer-writing attempt |
| Fallback rate | Questions whose final answer did not come purely from the LLM. **template** = the LLM's SQL was used, but its prose failed the checker twice or the answer call failed, so a deterministic summary of the rows was shown. **rules** = the LLM path failed (provider error, or 3 invalid SQL attempts), so the rule-based parser answered. In offline mode this is 0 by definition. |
| Latency p50 / p95 | Nearest-rank percentiles of end-to-end `ask()` time per question, in-process (no HTTP) |
| Latency excluding backoff | The same, minus time spent sleeping on provider rate limits (`retry-after`). This separates the free-tier quota from model speed. |
| Variance | The golden set repeated 3 times on the same database: range and standard deviation per metric, plus questions that pass in some runs but fail in others |

## Results

### Live LLM, 3 runs (`backend/evals/reports/live.json`)

| Metric | Run 1 | Run 2 | Run 3 | Mean ± sd |
|---|---|---|---|---|
| Accuracy | 50/50 | 50/50 | 50/50* | 100% ± 0 |
| Answered by the LLM (no fallback) | 50 | 50 | 33 | |
| Citation checker pass | 100% | 100% | 100% | 100% ± 0 |
| Retry rate | 2% (1 question) | 0% | 0% | 0.7% ± 0.9 |
| Fallback rate | 0% | 0% | 34% (3 template, 14 rules) | 11.3% ± 16.0 |
| Latency p50 / p95, end to end | 8.1s / 13.7s | 5.1s / 11.6s | 7.9s / 146.7s | |
| Latency p50 / p95, excluding backoff | 3.3s / 5.7s | 3.2s / 4.9s | 3.9s / 25.7s | |
| Rate-limit retries (429) | 62 | 47 | 161 | |
| Tokens | 80.7k | 79.5k | 52.0k | |
| Unstable questions | none | | | |

\* In run 3, 14 correct answers came from the rule-based fallback, not the model.

**What happened in run 3.** Partway through, Groq kept returning 429 after all 4 backoff retries (capped at 30s each). The Gemini fallback then failed as well: read timeouts, a 503, and then its own 429s. Afterwards Groq's response headers showed plenty of per-minute token capacity, so the per-minute limit wasn't the cause. Total usage reached about 212k tokens across the three runs, which is consistent with a daily token cap of about 200k on this key. **This wasn't confirmed:** the client logged only the status line at the time. It now records the provider's error message (commit `109d3d1`).

**What the run still shows.** The fallback chain degraded exactly as designed: no question went unanswered, and no failed citation reached the user. It doesn't measure the model. The model-only results are 50/50, 50/50 and 36/36 (the 33 pure-LLM answers plus 3 whose SQL came from the LLM).

### Rule-based (offline), 3 runs (`backend/evals/reports/offline.json`)

| Metric | Result |
|---|---|
| Accuracy | 50/50 in every run (sd 0) |
| Citation checker pass | 100% |
| Declined | 0 |
| Retry / fallback rate | n/a (no LLM) |
| Latency p50 / p95 | 8 ms / 14 ms |

### Data cleaning (both modes)

| Issue | Precision | Recall | F1 | Found / expected |
|---|---|---|---|---|
| Duplicate pairs | 1.000 | 1.000 | 1.000 | 192 / 192 |
| Stale leads | 1.000 | 1.000 | 1.000 | 480 / 480 |
| Missing fields | 1.000 | 1.000 | 1.000 | 240 / 240 |

### Held-out questions (`backend/evals/heldout.jsonl`)

**Construction.** 25 questions written after the golden-set fixes, phrased differently from any golden question (a test enforces no overlap), in 7 categories:

| Category | Questions | Example |
|---|---|---|
| Synonyms | 6 | "How many prospects are sitting in the negotiating phase?" |
| Multi-condition filters | 4 | "Which VPs at US logistics companies are in the qualified stage?" |
| Date ranges | 5 | "How many pricing page visits happened in August 2026?" |
| Top N by X in Y | 3 | "Top 5 leads by deal value in Manufacturing" |
| Negations | 4 | "How many open leads have never had any activity?" |
| Breakdown | 1 | "Break down stale leads by stage" |
| Must decline | 2 | "Which of our leads are most likely to churn next quarter?" |

Expected answers are computed from reference SQL (`python -m evals.build_golden --set heldout`). A decline question passes only if the system runs no query. **Rule: no prompt, rule or guard change is made in response to held-out results.** Failures are reported, not fixed.

**Rule-based (offline), `reports/heldout_offline.json`: 5/25.**

| Outcome | Count | Questions |
|---|---|---|
| Correct answer | 3 | H06, H08 (multi-filter), H18 (won deals per owner) |
| Correctly declined | 2 | H24, H25 (the two must-decline questions) |
| Declined an answerable question | 17 | every synonym except H18, every date-range question, and more |
| **Confident wrong answer** | **3** | H15, H17, H20 |

The three wrong answers matter more than the declines, because each one passed the citation checker and would have been shown as verified:

- **H15** "Top 5 leads by deal value in Manufacturing": ranked by score. The parser recognizes "top 5" and "Manufacturing" but has no concept of "by deal value", and "deal"/"value" are in its known vocabulary, so it didn't decline.
- **H17** "Top 4 industries by average deal value of open leads": returned one overall average (8,986) for all open leads, dropping both "top 4" and the per-industry grouping.
- **H20** "How many open leads have never had any activity?": answered 4,045 (all open leads) instead of 542. The negation "never had any activity" was dropped.

So the design claim that the parser "declines rather than guesses" didn't hold. It declined unknown *words*, but it could still silently drop a known word's *meaning* (ranking measure, negation). The citation checker can't catch this, because every number it states is really in the rows it fetched.

**After the strict-fallback policy, `reports/heldout_offline_strict.json`: 4/25, 0 wrong answers.**

This is a general safety policy, not a per-question fix. The parser was rewritten around *token consumption*: every slot (filter, metric, grouping, ranking, entity) marks the words it uses, and the parser answers only if no content word is left over. It also declines on:
- any negation, except the single supported filter "never (been) contacted", which is consumed as one unit;
- ranking by anything other than score, or ranking groups;
- a parsed filter it can't apply (a day window with no activity to apply it to).

Its vocabulary is a subset of the previous parser's: strictness removed words and added none, so the held-out result couldn't be improved by adding synonyms. The golden set stays 50/50 offline.

| Outcome | Before (5/25) | After strict policy (4/25) |
|---|---|---|
| Correct answer | 3 (H06, H08, H18) | 2 (H06, H08) |
| Correctly declined | 2 (H24, H25) | 2 (H24, H25) |
| Declined an answerable question | 17 | 21 |
| **Confident wrong answer** | **3** (H15, H17, H20) | **0** |

The three former wrong answers now decline with a reason: "can't interpret 'by deal value'", "can't interpret 'industries by'", and "negation 'never' is not supported". The price is coverage. H18 ("Won deals per owner") was answered correctly before, because the old parser treated "deals" as filler, and it now declines because "deals" isn't mapped to anything. A declined question shows "Live model unavailable right now. In offline mode I can answer questions like: …" with 4 example questions as clickable chips; each is tested to be answerable. Tests in `tests/test_rules.py` pin all three former wrong answers as declines, along with other questions in the same failure classes.

**Live LLM: pending.** The planned single live run couldn't happen on Sept 29: Groq returned `429 … tokens per day (TPD): Limit 200000` (the provider's message, now recorded in the call ledger). That day's earlier golden runs had used about 212k tokens. The run needs about 27k tokens (25 questions × ~1,080) and will be run once, unchanged, when the daily window frees up.

### Held-out duplicate detection (`backend/evals/cleaning_heldout.py`)

The seeded CRM only injects the duplicate kinds the detector was built alongside (case changes, one-character typos, Gmail dots), so its perfect score says little. This benchmark uses a separate generator (seed 2027, multilingual names, 520 leads) with six other kinds of duplicate, 10 each, plus 30 **precision traps** that must *not* be merged:

- **Look-alike names at the same company:** Chris/Christine, Dan/Danielle, Alex/Alexis.
- **Same name at an unrelated company.**
- **Family members at the same company.**
- **Colleagues sharing the office main line.**

| Duplicate kind | Example | Held-out (detector untouched) | After fixes (no longer held-out) |
|---|---|---|---|
| Nickname | Robert Smith → Bob Smith, `bob.smith@` | 2/10 | 10/10 |
| Swapped first/last | Jose Garcia → Garcia Jose, no email, same phone | 0/10 | 10/10 |
| Company suffix | "Acme Labs Inc" vs "Acme Labs Ltd" (separate company records) | 6/10 | 10/10 |
| Phone format | same name, personal email, `+1 415-555-0134` vs `(415) 555 0134` | 0/10 | 10/10 |
| Accents | José Müller → Jose Muller, no email | 0/10 | 10/10 |
| Whitespace / case | `" MARIA  "`, `"  Maria.Garcia@X.com "` | 10/10 | 10/10 |
| **Precision / recall / F1** | | **0.90 / 0.30 / 0.45** | 1.00 / 1.00 / 1.00 |
| Traps wrongly merged | | 2/30 (Alex/Alexis Lopez; Raul/Paulo Freitas) | 0/30 |

**The held-out result is the left column** (`reports/cleaning_heldout_before.json`, committed before any detector change). The detector found almost none of the new noise, and its fuzzy whole-name matching merged two different people.

**Fixes, all general techniques:**

- **Names:** accents folded and whitespace/case normalized.
- **First names** match if equal, if one is a known nickname of the other, or if they're one keystroke apart (edit distance ≤ 1, adjacent swaps included). Nicknames must resolve to *exactly* the other name, so Dan↔Daniel matches but Dan↔Danielle doesn't. Two short names (under 4 letters) must match exactly.
- **Swapped fields:** first/last are compared crosswise.
- **Company blocking** uses a normalized name with legal forms removed (Inc, Ltd, LLC, Pvt Ltd, GmbH, S.A., B.V., …) instead of the company record ID.
- **Evidence:** a matching name must be backed by a similar email local part (nickname-canonicalized), the same phone (last 10 digits), or a missing email on one side. A shared phone alone never merges different names.

**Why the right column is not a held-out score:**

- I wrote both the generator's nickname list and the detector's nickname table, and the generator's 20 pairs are all in the table. Real nickname recall will be lower.
- The "S.A." case (2 company-suffix misses) was found by inspecting held-out misses after the first round of fixes.
- The first round of fixes regressed the main seeded set (recall 0.995, then 0.984). The misses were adjacent-letter swaps like Gary→Gayr, and dropped letters that left a 3-letter name (John→Jon). Replacing a similarity threshold with an explicit one-keystroke edit distance, and applying the short-name rule to the longer name, restored 1.000 on the main set.

The benchmark now runs in CI as a regression guard (`tests/test_evals.py`). A fresh held-out set with different noise would be needed to measure generalization again.

**Known remaining gaps:** initials ("J. Smith"), people who changed employer (different company *and* email), transliteration beyond accent stripping (Müller vs Mueller), and genuinely different people one letter apart at the same company (Maria vs Mario Garcia with similar work emails would still merge).

## How we got here: failures found and fixed

The first live run scored 8/10 on a 10-question subset, and the first full run 47/50. Every failure was traced to its cause and fixed in the prompt, the guardrails or the checker. No fix special-cases a question.

| Symptom (question) | Root cause | Fix | Commit |
|---|---|---|---|
| Missing-email/phone counts too low (Q05, Q06: 47 vs 75, 31 vs 100) | The schema prompt never said that blanks are stored as `NULL`, `''` or whitespace | The prompt documents the encoding and the `trim(col) = ''` test | `6b5c930` |
| The same invalid SQL repeated 3 times, then fell back (Q02) | Retry feedback included DuckDB's error but not the rejected SQL; the prompt also encouraged `ILIKE` on coded columns | Retries show the model its own SQL; coded columns take exact `=`/`IN`; dialect note (no `ILIKE ANY`) | `6b5c930` |
| Correct counts rejected on first try (Q05–Q07) | For aggregate results with no IDs, the model invented a citation (`[row-0]`) because the prompt demanded citations | The prompt forbids invented references; the checker now rejects any bracketed text that isn't a real row ID | `6b5c930` |
| "Which …" lists returned 10 of 75 rows (Q29, Q31, Q40) | The prompt's "default LIMIT 10" silently truncated complete lists | LIMIT applies only to top/best/first-N questions | `d6e6b56` |
| Valid `JOIN … USING` queries rejected, forcing retries; one rewrite changed the meaning (Q28, Q30, Q32, Q39) | **A bug in our guard.** DuckDB 1.5's `get_table_names()` binds the query and fails on valid `USING` joins | The guard reads referenced tables from the parse tree (`json_serialize_sql`). This also rejects every table function structurally, and blocks CTE names that would shadow protected tables. | `1c91cb3` |
| "Top 10 stale leads" used "never contacted" as the definition in 2 of 3 runs (Q30) | Business terms weren't defined in the prompt | The prompt defines stale / duplicate / missing field and names `data_issues` as the canonical source | `4e95197` |
| Rule-based mode declined "flagged as duplicates" (Q04) | The parser knew issue types but not the verbs used to say a record has one | Accepts *flagged / marked / tagged …* only next to an issue type ("flagged as spam" is still declined) | `51c7975` |

## Read these numbers with care

- **The prompt fixes were made while looking at the golden set.** Each fix addresses a general cause: data encoding, definitions, dialect, retry context. But they were found using these 50 questions. Unseen questions may expose other gaps.
- **The golden set is small and easy.** 50 questions, one phrasing each, 7 categories, all answerable with one query over 5 tables. 100% here means "reliable on common analytics questions", not "handles any question".
- **The rule-based 50/50 is tuned on the test set.** Accuracy went from 22 to 47, 49 and then 50 as vocabulary gaps were fixed. `tests/test_rules.py` holds 7 held-out phrasings and 4 must-decline questions as a fairer check.
- **Perfect cleaning scores reflect synthetic noise.** The duplicate kinds (case changes, one-character typos, Gmail dots) were designed alongside the detector. Real CRM duplicates (nicknames, job changes, shared inboxes) would lower recall.
- **Three runs is a small sample.** Zero unstable questions across 3 runs doesn't rule out rarer flips at temperature 0 on a reasoning model.
- **Latency depends on the free tier.** On this key, rate-limit waits made up 56% and 42% of total question time in the two clean runs (88% in run 3). Use the "excluding backoff" rows to judge model speed. A paid key would change end-to-end latency but not correctness.

## Known limits

- **The checker verifies support, not correctness.** An answer that cites the right rows and repeats their numbers can still describe them wrongly. Grading on returned rows covers the SQL; the prose is only checked for invented IDs, labels and numbers.
- **Numbers glued to units (`12d`, `3x`) aren't checked,** and numbers from the question are always allowed.
- **Queries return at most 200 rows.** Golden `id_set` answers are kept below that.
- **Single dataset, single seed (42).**

## Reproduce

From `backend/`, with the venv active:

```bash
python -m evals.build_golden                                                  # rebuild expected answers (after changing seed/questions)
python -m evals.run --mode offline --runs 3 --out evals/reports/offline.json
python -m evals.run --mode live --runs 3 --out evals/reports/live.json        # needs GROQ_API_KEY in backend/.env
```

Each run seeds a fresh temporary database, so it never touches your working data. Without `--out`, the report goes to `evals/latest.json`, which the UI's Evals page shows. A live run uses about 80k tokens and about 100 requests (2 per question, plus retries). On a free-tier key with a daily token cap, **a clean 3-run live eval may not fit in one day**, as run 3 above shows.
