"""Generate ``data/sample_hubspot_export.csv``: a realistic, messy HubSpot contacts export.

Run from ``backend/``:  python -m scripts.make_sample_hubspot_export

300 rows: 268 new contacts, 10 re-exports of leads already in the CRM (dedup should
catch them), 10 in-file duplicates, and 12 invalid rows the importer must reject.
"""

import csv
import random
from datetime import timedelta
from pathlib import Path

from faker import Faker

from app.config import AS_OF, DATA_DIR
from app.seed import generate

OUT = DATA_DIR / "sample_hubspot_export.csv"
HEADERS = ["Record ID", "First Name", "Last Name", "Email", "Phone Number", "Job Title", "Company Name",
           "Company Domain Name", "Industry", "Number of Employees", "Country/Region", "Lead Status",
           "Lifecycle Stage", "Original Source", "Contact owner", "Create Date", "Last Contacted", "Amount"]
STATUSES = ["New", "Open", "In Progress", "Open Deal", "Attempted to Contact", "Connected", "Unqualified", "Bad Timing"]
LIFECYCLE = ["Lead", "Marketing Qualified Lead", "Sales Qualified Lead", "Opportunity", "Customer"]
SOURCES = ["Organic Search", "Direct Traffic", "Referrals", "Social Media", "Email Marketing", "Offline Sources"]
INDUSTRIES = ["Computer Software", "Financial Services", "Hospital & Health Care", "Retail",
              "Logistics and Supply Chain", "Education Management", "Online Media",
              "Mechanical or Industrial Engineering"]
TITLES = ["CEO", "Co-Founder", "VP of Sales", "Vice President, Operations", "Director of IT", "Head of Growth",
          "Marketing Manager", "Team Lead", "Software Engineer", "Analyst"]
COUNTRIES = ["United States", "United States", "United Kingdom", "Germany", "India", "Canada"]
OWNERS = ["Maya Chen", "Daniel Ortiz", "Priya Nair", "Tom Becker"]


def main() -> None:
    rng = random.Random(11)
    fake = Faker()
    Faker.seed(11)
    rows: list[dict[str, str]] = []

    def stamp(days_back: int) -> str:
        return (AS_OF - timedelta(days=days_back, minutes=rng.randint(0, 900))).strftime("%Y-%m-%d %H:%M")

    def contact() -> dict[str, str]:
        first, last = fake.first_name(), fake.last_name()
        company = fake.company().replace(",", "")
        domain = "".join(ch for ch in company.lower() if ch.isalnum())[:20] + ".com"
        created = rng.randint(5, 400)
        contacted = "" if rng.random() < 0.25 else stamp(rng.randint(0, created))
        return {
            "First Name": first, "Last Name": last, "Email": f"{first}.{last}@{domain}".lower(),
            "Phone Number": fake.numerify("+1 (###) ###-####") if rng.random() > 0.08 else "",
            "Job Title": rng.choice(TITLES) if rng.random() > 0.06 else "", "Company Name": company,
            "Company Domain Name": rng.choice([domain, f"www.{domain}", f"https://{domain}"]),
            "Industry": rng.choice(INDUSTRIES),
            "Number of Employees": rng.choice([str(rng.randint(5, 5000)), "51-200", "201-500"]),
            "Country/Region": rng.choice(COUNTRIES), "Lead Status": rng.choice(STATUSES),
            "Lifecycle Stage": rng.choice(LIFECYCLE), "Original Source": rng.choice(SOURCES),
            "Contact owner": rng.choice(OWNERS), "Create Date": stamp(created), "Last Contacted": contacted,
            "Amount": f"${rng.randint(20, 900) * 100:,}.00" if rng.random() < 0.6 else "",
        }

    rows += [contact() for _ in range(268)]
    rows[5]["Lead Status"] = "Nurture"  # unknown status: imported as 'new' with a warning

    # Re-exports of leads already in the CRM (same person, same company).
    companies, leads, _, _ = generate()
    by_company = companies.set_index("company_id")
    for _, lead in leads[leads["email"].fillna("").str.contains("@")].sample(10, random_state=3).iterrows():
        co = by_company.loc[lead["company_id"]]
        base = contact()
        base.update({"First Name": lead["first_name"], "Last Name": lead["last_name"], "Email": lead["email"].upper(),
                     "Company Name": co["name"], "Company Domain Name": co["domain"]})
        rows.append(base)

    # Duplicates inside the file: same person entered twice with different casing and stray spaces.
    for original in rng.sample(rows[:268], 10):
        dup = dict(original)
        dup["Email"] = original["Email"].upper()
        dup["First Name"] = f" {original['First Name']} "
        dup["Create Date"] = stamp(3)
        rows.append(dup)

    # Invalid rows, two of each kind.
    bad = [contact() for _ in range(12)]
    for i in (0, 1):
        bad[i]["Email"] = bad[i]["Email"].split("@")[0] + "@"
    for i in (2, 3):
        bad[i]["Company Name"] = ""
    for i in (4, 5):
        bad[i]["Create Date"] = "31/31/2026"
    for i in (6, 7):
        bad[i]["Amount"] = "TBD"
    for i in (8, 9):
        bad[i].update({"First Name": "", "Last Name": "", "Email": ""})
    for i in (10, 11):
        bad[i]["Create Date"] = "2027-01-05 09:00"
    rows += bad

    rng.shuffle(rows)
    for n, row in enumerate(rows, start=1):
        row["Record ID"] = str(90_000 + n)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT}")


if __name__ == "__main__":
    main()
