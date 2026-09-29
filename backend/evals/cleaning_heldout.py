"""Held-out duplicate-detection benchmark with noise the detector was not built for.

Run from ``backend/``:  python -m evals.cleaning_heldout [--out evals/reports/cleaning_heldout.json]

The seeded CRM only injects case changes, one-character typos and Gmail dots. This set
uses a different seed, multilingual names and six other kinds of duplicate:

  nickname        Robert Smith -> Bob Smith (work email follows the nickname)
  swapped         first and last name swapped, no email, same phone
  company_suffix  same person under "Acme Labs Inc" and "Acme Labs Ltd" (separate company records)
  phone_format    same name and phone in another format, personal instead of work email
  accents         José Müller -> Jose Muller, no email
  whitespace_case stray spaces and different case in names and email

plus precision traps: similar-but-different people at the same company (Chris vs
Christine Lee), the same name at unrelated companies, family members, and colleagues
sharing the office main line.
"""

import argparse
import json
import random
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from faker import Faker

from app.cleaning import find_duplicates

SEED = 2027
KINDS = ("nickname", "swapped", "company_suffix", "phone_format", "accents", "whitespace_case")
PER_KIND = 10
# Pairs the generator uses (formal -> nickname). The detector's own nickname table is separate.
GEN_NICKNAMES = {
    "Robert": "Bob", "William": "Bill", "Elizabeth": "Liz", "Michael": "Mike", "Katherine": "Kate",
    "James": "Jim", "Thomas": "Tom", "David": "Dave", "Jennifer": "Jen", "Christopher": "Chris",
    "Alexander": "Alex", "Samuel": "Sam", "Daniel": "Dan", "Matthew": "Matt", "Nicholas": "Nick",
    "Anthony": "Tony", "Joseph": "Joe", "Steven": "Steve", "Margaret": "Peggy", "Richard": "Dick",
}
SUFFIXES = ["Inc", "Ltd", "LLC", "Pvt Ltd", "GmbH", "S.A.", "Limited", "Corp"]
SECTORS = ["Systems", "Labs", "Logistics", "Health", "Capital", "Media", "Foods", "Analytics", "Robotics", "Energy"]
LOCALES = ["en_US", "es_ES", "de_DE", "fr_FR", "pt_BR"]


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slug(text: str) -> str:
    return "".join(ch for ch in ascii_fold(text).lower() if ch.isalnum())


def generate(seed: int = SEED) -> tuple[pd.DataFrame, list[dict[str, str]], list[dict[str, str]]]:
    """Returns (leads, true duplicate pairs, trap pairs)."""
    rng = random.Random(seed)
    fakers = {loc: Faker(loc) for loc in LOCALES}
    Faker.seed(seed)
    t0 = datetime(2026, 1, 1)

    companies: list[dict[str, str]] = []
    for i in range(120):
        core = f"{fakers['en_US'].last_name()} {rng.choice(SECTORS)}"
        companies.append({"company_id": f"HC-{i + 1:04d}", "core": core, "name": f"{core} {rng.choice(SUFFIXES)}",
                          "domain": f"{slug(core)}.com"})

    leads: list[dict[str, Any]] = []

    def phone() -> str:
        return f"{rng.randint(201, 989)}{rng.randint(200, 999)}{rng.randint(0, 9999):04d}"

    def fmt_phone(digits: str, style: int) -> str:
        a, b, c = digits[:3], digits[3:6], digits[6:]
        return [f"+1 {a}-{b}-{c}", f"({a}) {b} {c}", f"{a}.{b}.{c}", f"+1{digits}", digits][style % 5]

    def add(first: str, last: str, company: dict[str, str], email: str | None, ph: str | None) -> str:
        lead_id = f"HL-{len(leads) + 1:04d}"
        leads.append({"lead_id": lead_id, "company_id": company["company_id"], "company_name": company["name"],
                      "first_name": first, "last_name": last, "email": email, "phone": ph,
                      "created_at": t0 + timedelta(hours=len(leads))})
        return lead_id

    def work_email(first: str, last: str, company: dict[str, str]) -> str:
        return f"{slug(first)}.{slug(last)}@{company['domain']}"

    # Base population: 400 distinct people, some with formal names that have nicknames.
    base: list[dict[str, Any]] = []
    formal = list(GEN_NICKNAMES)
    seen: set[tuple[str, str, str]] = set()
    while len(base) < 400:
        f = fakers[rng.choice(LOCALES)]
        first = rng.choice(formal) if len(base) < 60 else f.first_name()
        last = f.last_name()
        company = rng.choice(companies)
        key = (slug(first), slug(last), company["core"])
        if key in seen:
            continue
        seen.add(key)
        ph = phone()
        lead_id = add(first, last, company, work_email(first, last, company), fmt_phone(ph, 0))
        base.append({"lead_id": lead_id, "first": first, "last": last, "company": company, "phone": ph})

    truth: list[dict[str, str]] = []
    nick_pool = base[:60]
    other_pool = base[60:]
    rng.shuffle(other_pool)
    accented = [b for b in other_pool if ascii_fold(b["first"] + b["last"]) != b["first"] + b["last"]]
    plain = [b for b in other_pool if b not in accented]

    for b in rng.sample(nick_pool, PER_KIND):
        nick = GEN_NICKNAMES[b["first"]]
        dup = add(nick, b["last"], b["company"], work_email(nick, b["last"], b["company"]), None)
        truth.append({"lead_id": dup, "original_id": b["lead_id"], "kind": "nickname"})
    for b in plain[:PER_KIND]:
        dup = add(b["last"], b["first"], b["company"], None, fmt_phone(b["phone"], 1))
        truth.append({"lead_id": dup, "original_id": b["lead_id"], "kind": "swapped"})
    for b in plain[PER_KIND:2 * PER_KIND]:
        other_suffix = rng.choice([s for s in SUFFIXES if not b["company"]["name"].endswith(s)])
        twin = {"company_id": f"HC-{len(companies) + 1:04d}", "core": b["company"]["core"],
                "name": f"{b['company']['core']} {other_suffix}",
                "domain": rng.choice([b["company"]["domain"], f"{slug(b['company']['core'])}.co.uk"])}
        companies.append(twin)
        dup = add(b["first"], b["last"], twin, work_email(b["first"], b["last"], twin), None)
        truth.append({"lead_id": dup, "original_id": b["lead_id"], "kind": "company_suffix"})
    for b in plain[2 * PER_KIND:3 * PER_KIND]:
        personal = f"{slug(b['first'])[0]}{slug(b['last'])}{rng.randint(10, 99)}@gmail.com"
        dup = add(b["first"], b["last"], b["company"], personal, fmt_phone(b["phone"], rng.randint(1, 4)))
        truth.append({"lead_id": dup, "original_id": b["lead_id"], "kind": "phone_format"})
    for b in accented[:PER_KIND]:
        dup = add(ascii_fold(b["first"]), ascii_fold(b["last"]), b["company"], None, None)
        truth.append({"lead_id": dup, "original_id": b["lead_id"], "kind": "accents"})
    for b in plain[3 * PER_KIND:4 * PER_KIND]:
        email = f"  {work_email(b['first'], b['last'], b['company']).title()} "
        dup = add(f" {b['first'].upper()}  ", f"{b['last'].lower()} ", b["company"], email, None)
        truth.append({"lead_id": dup, "original_id": b["lead_id"], "kind": "whitespace_case"})

    # Precision traps: must NOT be merged.
    traps: list[dict[str, str]] = []
    lookalikes = [("Chris", "Christine"), ("Dan", "Danielle"), ("Alex", "Alexis"), ("Sam", "Samantha"),
                  ("Jo", "Joanna"), ("Max", "Maxine"), ("Nick", "Nicole"), ("Ben", "Bernadette")]
    for a, b_name in lookalikes:
        company, last = rng.choice(companies[:120]), fakers["en_US"].last_name()
        x = add(a, last, company, work_email(a, last, company), fmt_phone(phone(), 0))
        y = add(b_name, last, company, work_email(b_name, last, company), fmt_phone(phone(), 0))
        traps.append({"a": x, "b": y, "kind": "lookalike_names"})
    for b in plain[40:48]:  # same name, unrelated company
        company = rng.choice([c for c in companies[:120] if c["core"] != b["company"]["core"]])
        x = add(b["first"], b["last"], company, work_email(b["first"], b["last"], company), fmt_phone(phone(), 0))
        traps.append({"a": b["lead_id"], "b": x, "kind": "same_name_other_company"})
    for b in plain[48:56]:  # family member at the same company
        f = fakers[rng.choice(LOCALES)].first_name()
        x = add(f, b["last"], b["company"], work_email(f, b["last"], b["company"]), fmt_phone(phone(), 0))
        traps.append({"a": b["lead_id"], "b": x, "kind": "family_same_company"})
    for b in plain[56:62]:  # colleague sharing the office main line
        f, last = fakers["en_US"].first_name(), fakers["en_US"].last_name()
        x = add(f, last, b["company"], work_email(f, last, b["company"]), fmt_phone(b["phone"], 2))
        traps.append({"a": b["lead_id"], "b": x, "kind": "shared_phone"})

    return pd.DataFrame(leads), truth, traps


def evaluate(leads: pd.DataFrame, truth: list[dict[str, str]], traps: list[dict[str, str]]) -> dict[str, Any]:
    found = {frozenset((p.lead_id, p.related_lead_id)): p.reason for p in find_duplicates(leads)}
    true_pairs = {frozenset((t["lead_id"], t["original_id"])): t["kind"] for t in truth}
    tp = set(found) & set(true_pairs)
    precision = len(tp) / len(found) if found else 0.0
    recall = len(tp) / len(true_pairs)
    by_kind: dict[str, list[bool]] = defaultdict(list)
    for pair, kind in true_pairs.items():
        by_kind[kind].append(pair in found)
    trap_pairs = {frozenset((t["a"], t["b"])): t["kind"] for t in traps}
    trap_hits: dict[str, int] = defaultdict(int)
    for pair in found:
        if pair in trap_pairs:
            trap_hits[trap_pairs[pair]] += 1
    names = leads.set_index("lead_id")[["first_name", "last_name", "company_name", "email", "phone"]]
    false_positives = [
        {"pair": sorted(pair), "reason": found[pair], "trap": trap_pairs.get(pair),
         "rows": [names.loc[i].fillna("").astype(str).str.strip().tolist() for i in sorted(pair)]}
        for pair in set(found) - set(true_pairs)
    ]
    return {
        "leads": len(leads), "true_pairs": len(true_pairs), "found_pairs": len(found),
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "recall_by_kind": {k: {"found": sum(v), "total": len(v)} for k, v in sorted(by_kind.items())},
        "traps": {"total": len(traps), "merged": sum(trap_hits.values()), "by_kind": dict(trap_hits)},
        "false_positives": false_positives[:40],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--csv", type=Path, default=None, help="also write the dataset for inspection")
    args = parser.parse_args()
    leads, truth, traps = generate()
    report = evaluate(leads, truth, traps)
    print(f"held-out dedup: P={report['precision']:.3f} R={report['recall']:.3f} F1={report['f1']:.3f} "
          f"({report['found_pairs']} found / {report['true_pairs']} true, "
          f"traps merged {report['traps']['merged']}/{report['traps']['total']})")
    for kind, v in report["recall_by_kind"].items():
        print(f"  recall {kind:<16} {v['found']}/{v['total']}")
    for fp in report["false_positives"][:10]:
        print(f"  FP {fp['trap'] or 'other'}: {fp['rows']} ({fp['reason']})")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    if args.csv:
        leads.to_csv(args.csv, index=False)


if __name__ == "__main__":
    main()
