"""Deterministic synthetic CRM generator.

Produces ~1,500 companies, ~5,000 leads and ~40k activities, then injects a known
set of data problems (duplicates, stale records, missing fields) and writes the
answer key to ``data/ground_truth.json`` so the cleaning step can be scored.

Run: ``python -m app.seed`` (from ``backend/``).
"""

import json
import random
import re
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from faker import Faker

from app import db
from app.config import AS_OF, CLOSED_STAGES, DATA_DIR, OPEN_STAGES, OWNERS, STALE_DAYS

SEED = 42
N_COMPANIES = 1500
N_BASE_LEADS = 4800
DUPLICATE_RATE = 0.04
STALE_RATE = 0.10
MISSING_RATE = 0.05
GROUND_TRUTH_PATH = DATA_DIR / "ground_truth.json"

INDUSTRIES = {
    "Software": 0.22, "Fintech": 0.12, "Healthcare": 0.12, "E-commerce": 0.12,
    "Logistics": 0.10, "Manufacturing": 0.12, "Education": 0.10, "Media": 0.10,
}
COUNTRIES = {"US": 0.45, "GB": 0.12, "DE": 0.10, "IN": 0.10, "CA": 0.08, "AU": 0.07, "FR": 0.08}
TITLES = {
    "c_level": ["CEO", "CTO", "CFO", "COO", "Chief Revenue Officer"],
    "vp": ["VP of Sales", "VP Engineering", "VP Marketing", "VP Operations"],
    "director": ["Director of Sales", "Director of IT", "Head of Growth", "Director of Operations"],
    "manager": ["Sales Manager", "IT Manager", "Marketing Manager", "Procurement Manager"],
    "individual": ["Account Executive", "Software Engineer", "Analyst", "Operations Specialist"],
}
SENIORITY_WEIGHTS = {"c_level": 0.08, "vp": 0.14, "director": 0.2, "manager": 0.3, "individual": 0.28}
SOURCES = {"website": 0.3, "referral": 0.12, "linkedin": 0.2, "event": 0.12, "cold_outbound": 0.18, "partner": 0.08}
STAGE_WEIGHTS = {
    "new": 0.2, "contacted": 0.25, "qualified": 0.18, "proposal": 0.1,
    "negotiation": 0.07, "won": 0.1, "lost": 0.1,
}
ACTIVITY_TYPES = {
    "email_open": 0.34, "website_visit": 0.24, "email_reply": 0.12, "call": 0.1,
    "pricing_page_visit": 0.09, "meeting": 0.06, "demo_request": 0.05,
}
KEYBOARD_NEIGHBORS = {
    "a": "sq", "e": "wr", "i": "uo", "o": "ip", "n": "bm", "r": "et",
    "s": "ad", "t": "ry", "l": "k", "m": "n", "h": "gj", "c": "xv",
}


def _pick(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _typo(rng: random.Random, word: str) -> str:
    """Introduce one realistic keystroke error into ``word``."""
    if len(word) < 4:
        return word + word[-1]
    i = rng.randrange(1, len(word) - 1)
    op = rng.choice(["swap", "drop", "double", "neighbor"])
    if op == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if op == "drop":
        return word[:i] + word[i + 1:]
    if op == "double":
        return word[:i] + word[i] + word[i:]
    ch = word[i].lower()
    repl = rng.choice(KEYBOARD_NEIGHBORS.get(ch, string.ascii_lowercase))
    return word[:i] + repl + word[i + 1:]


def _phone(rng: random.Random) -> str:
    area, mid, last = rng.randint(201, 989), rng.randint(200, 999), rng.randint(0, 9999)
    fmt = rng.choice(["+1 {a}-{m}-{l:04d}", "({a}) {m} {l:04d}", "{a}{m}{l:04d}", "{a}.{m}.{l:04d}"])
    return fmt.format(a=area, m=mid, l=last)


@dataclass
class GroundTruth:
    duplicates: list[dict[str, str]] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    missing: list[dict[str, str]] = field(default_factory=list)


def generate(seed: int = SEED) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, GroundTruth]:
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)

    # --- companies -------------------------------------------------------
    companies: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    while len(companies) < N_COMPANIES:
        name = fake.company().replace(",", "")
        if name in seen_names:
            continue
        seen_names.add(name)
        employees = int(min(50_000, max(3, rng.lognormvariate(4.6, 1.5))))
        companies.append({
            "company_id": f"CO-{len(companies) + 1:05d}",
            "name": name,
            "domain": f"{_slug(name)[:24]}.{rng.choice(['com', 'com', 'io', 'co'])}",
            "industry": _pick(rng, INDUSTRIES),
            "employees": employees,
            "country": _pick(rng, COUNTRIES),
            "created_at": AS_OF - timedelta(days=rng.randint(200, 1500)),
        })

    # --- base leads (all unique people) ---------------------------------
    base: list[dict[str, Any]] = []
    seen_people: set[tuple[str, str, str]] = set()
    seen_emails: set[str] = set()
    while len(base) < N_BASE_LEADS:
        company = rng.choice(companies)
        first, last = fake.first_name(), fake.last_name()
        key = (first.lower(), last.lower(), company["company_id"])
        if key in seen_people:
            continue
        if rng.random() < 0.15:
            email = f"{first}.{last}{rng.randint(1, 99)}@gmail.com".lower()
        else:
            email = f"{first}.{last}@{company['domain']}".lower()
        email = email.replace("'", "")
        if email in seen_emails:
            continue
        seen_people.add(key)
        seen_emails.add(email)
        seniority = _pick(rng, SENIORITY_WEIGHTS)
        stage = _pick(rng, STAGE_WEIGHTS)
        created = AS_OF - timedelta(days=rng.randint(5, 700), hours=rng.randint(0, 23))
        size_factor = min(company["employees"], 5000) ** 0.5
        base.append({
            "company_id": company["company_id"],
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": _phone(rng),
            "title": rng.choice(TITLES[seniority]),
            "seniority": seniority,
            "source": _pick(rng, SOURCES),
            "stage": stage,
            "deal_value": None if stage == "new" and rng.random() < 0.6 else round(rng.uniform(2, 12) * size_factor * 100, -2),
            "owner": rng.choice(OWNERS),
            "created_at": created,
            "hotness": rng.betavariate(1.2, 4),  # latent engagement propensity
        })

    # Contact history. Open leads are kept inside the fresh window unless picked as stale.
    open_idx = [i for i, lead in enumerate(base) if lead["stage"] in OPEN_STAGES]
    stale_idx = set(rng.sample(open_idx, round(STALE_RATE * N_BASE_LEADS)))
    for i, lead in enumerate(base):
        created = lead["created_at"]
        age = (AS_OF - created).days
        if i in stale_idx:
            lead["created_at"] = created = min(created, AS_OF - timedelta(days=STALE_DAYS + 30))
            age = (AS_OF - created).days
            contacted = None if rng.random() < 0.15 else AS_OF - timedelta(days=rng.randint(STALE_DAYS + 1, max(STALE_DAYS + 2, age)))
        elif lead["stage"] in OPEN_STAGES:
            if lead["stage"] == "new" and age < STALE_DAYS - 5 and rng.random() < 0.4:
                contacted = None
            else:
                contacted = AS_OF - timedelta(days=rng.randint(0, min(age, STALE_DAYS - 5)), hours=rng.randint(0, 23))
        else:
            contacted = AS_OF - timedelta(days=rng.randint(0, age))
        lead["last_contacted_at"] = contacted
        lead["updated_at"] = max(created, contacted) if contacted else created
        lead["_stale"] = i in stale_idx

    # --- duplicates -----------------------------------------------------
    n_dups = round(DUPLICATE_RATE * N_BASE_LEADS)
    originals = rng.sample(range(N_BASE_LEADS), n_dups)
    duplicates: list[dict[str, Any]] = []
    for i in originals:
        src = base[i]
        dup = {k: v for k, v in src.items() if not k.startswith("_")}
        kind = rng.choice(["case_change", "name_typo", "email_typo", "gmail_dots"] if src["email"].endswith("@gmail.com")
                          else ["case_change", "name_typo", "email_typo"])
        local, domain = src["email"].split("@")
        if kind == "case_change":
            dup["first_name"], dup["last_name"] = src["first_name"].upper(), src["last_name"].upper()
            dup["email"] = src["email"].upper() if rng.random() < 0.5 else local.capitalize() + "@" + domain
        elif kind == "name_typo":
            dup["last_name"] = _typo(rng, src["last_name"])
            dup["email"] = src["email"]
        elif kind == "email_typo":
            dup["first_name"] = _typo(rng, src["first_name"]) if rng.random() < 0.5 else src["first_name"]
            dup["email"] = _typo(rng, local) + "@" + domain
        else:  # gmail_dots: gmail ignores dots in the local part
            dup["email"] = local.replace(".", "") + "@" + domain
        dup["phone"] = _phone(rng) if rng.random() < 0.3 else src["phone"]
        dup["source"] = _pick(rng, SOURCES)
        dup["stage"] = "new"
        dup["deal_value"] = None
        dup["created_at"] = src["created_at"] + timedelta(days=rng.randint(1, 60))
        dup["created_at"] = min(dup["created_at"], AS_OF - timedelta(days=1))
        dup["last_contacted_at"] = None
        dup["updated_at"] = dup["created_at"]
        dup["hotness"] = src["hotness"] * 0.3
        dup["_dup_of"], dup["_kind"] = i, kind
        # A duplicate is a "new" open lead with no contact: keep it inside the fresh
        # window so its only injected issue is being a duplicate.
        if (AS_OF - dup["created_at"]).days >= STALE_DAYS - 5:
            dup["created_at"] = AS_OF - timedelta(days=rng.randint(1, STALE_DAYS - 5))
            dup["updated_at"] = dup["created_at"]
        duplicates.append(dup)

    # --- missing fields (never on dup pairs, so each lead has one clean label) ---
    dup_related = set(originals)
    candidates = [i for i in range(N_BASE_LEADS) if i not in dup_related]
    missing_idx = rng.sample(candidates, round(MISSING_RATE * N_BASE_LEADS))
    for i in missing_idx:
        fld = rng.choices(["email", "phone", "title"], weights=[0.35, 0.4, 0.25])[0]
        base[i][fld] = rng.choice([None, "", " "])
        base[i]["_missing"] = fld

    # --- assign shuffled IDs so duplicates aren't adjacent to their originals ---
    all_leads = base + duplicates
    order = list(range(len(all_leads)))
    rng.shuffle(order)
    for new_pos, idx in enumerate(order):
        all_leads[idx]["lead_id"] = f"LD-{new_pos + 1:05d}"

    truth = GroundTruth()
    for dup in duplicates:
        truth.duplicates.append({
            "lead_id": dup["lead_id"],
            "original_id": base[dup["_dup_of"]]["lead_id"],
            "kind": dup["_kind"],
        })
    truth.stale = sorted(lead["lead_id"] for lead in base if lead["_stale"])
    truth.missing = sorted(
        ({"lead_id": lead["lead_id"], "field": lead["_missing"]} for lead in base if "_missing" in lead),
        key=lambda m: m["lead_id"],
    )
    truth.duplicates.sort(key=lambda d: d["lead_id"])

    # --- activities -----------------------------------------------------
    activities: list[dict[str, Any]] = []
    for lead in sorted(all_leads, key=lambda x: x["lead_id"]):
        horizon = min(180.0, (AS_OF - lead["created_at"]).total_seconds() / 86400)
        if horizon <= 0:
            continue
        n = int(rng.expovariate(1 / (2.5 + 32 * lead["hotness"])))
        if lead["stage"] in CLOSED_STAGES:
            n //= 2
        for _ in range(min(n, 80)):
            # Hot leads skew their activity toward the recent past.
            back = horizon * (rng.random() ** (1 + 3 * lead["hotness"]))
            activities.append({
                "lead_id": lead["lead_id"],
                "type": _pick(rng, ACTIVITY_TYPES),
                # Whole seconds: `back` comes from float pow(), whose last bit differs between
                # libm implementations (Windows vs Linux); microseconds would make the seed OS-dependent.
                "occurred_at": (AS_OF - timedelta(days=back)).replace(microsecond=0),
            })
    activities.sort(key=lambda a: (a["occurred_at"], a["lead_id"]))
    for n, act in enumerate(activities, start=1):
        act["activity_id"] = f"ACT-{n:05d}"

    lead_cols = ["lead_id", "company_id", "first_name", "last_name", "email", "phone", "title", "seniority",
                 "source", "stage", "deal_value", "owner", "created_at", "last_contacted_at", "updated_at"]
    leads_df = pd.DataFrame(all_leads)[lead_cols].sort_values("lead_id").reset_index(drop=True)
    companies_df = pd.DataFrame(companies)
    activities_df = pd.DataFrame(activities)[["activity_id", "lead_id", "type", "occurred_at"]]
    return companies_df, leads_df, activities_df, truth


def write_database(path: Path | None = None, seed: int = SEED) -> GroundTruth:
    """Rebuild the database from scratch: raw tables, detected issues, scores."""
    from app.cleaning import detect_issues
    from app.scoring import materialize_scores

    target = path or db.settings.db_path
    db.close()
    for suffix in ("", ".wal"):
        Path(str(target) + suffix).unlink(missing_ok=True)

    companies, leads, activities, truth = generate(seed)
    conn = db.connect(target)
    conn.register("companies_df", companies)
    conn.register("leads_df", leads)
    conn.register("activities_df", activities)
    conn.execute("INSERT INTO companies SELECT * FROM companies_df")
    conn.execute("INSERT INTO leads SELECT * FROM leads_df")
    conn.execute("INSERT INTO activities SELECT * FROM activities_df")
    for name in ("companies_df", "leads_df", "activities_df"):
        conn.unregister(name)

    detect_issues(conn)
    materialize_scores(conn)
    conn.execute("CHECKPOINT")
    return truth


def save_ground_truth(truth: GroundTruth, path: Path = GROUND_TRUTH_PATH) -> None:
    payload = {
        "seed": SEED,
        "as_of": AS_OF.isoformat(),
        "counts": {
            "duplicates": len(truth.duplicates),
            "stale": len(truth.stale),
            "missing": len(truth.missing),
        },
        "duplicates": truth.duplicates,
        "stale": truth.stale,
        "missing": truth.missing,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    started = datetime.now()
    truth = write_database()
    save_ground_truth(truth)
    with db.cursor() as cur:
        counts = {t: cur.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("companies", "leads", "activities", "data_issues")}
    print(f"Seeded {counts} in {(datetime.now() - started).total_seconds():.1f}s -> {db.settings.db_path}")


if __name__ == "__main__":
    main()
