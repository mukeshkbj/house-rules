"""Generate a realistic, seeded sample snapshot for offline testing.

Fictional company "Kestrel Analytics Ltd", 6 months of history (Apr–Sep 2026)
plus October bills awaiting payment. Mirrors the shape the Collector returns
from the Seapoint sandbox, so the rest of the app doesn't care which it gets.

Run:  python data/make_sample.py
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(7)

VENDORS = [
    # id, name, category, bank fingerprint, cadence
    ("V-001", "Amazon Web Services", "cloud", "..4471", "monthly_var"),
    ("V-002", "Figma", "software", "..9012", "monthly_fixed"),
    ("V-003", "Notion Labs", "software", "..3388", "monthly_fixed"),
    ("V-004", "Google Workspace", "software", "..5520", "monthly_fixed"),
    ("V-005", "Priya Shah Consulting", "contractor", "..7731", "contractor"),
    ("V-006", "Reid Dev Studio", "contractor", "..2209", "contractor"),
    ("V-007", "Harbour Desk Coworking", "rent", "..6604", "rent"),
    ("V-008", "Ledgerline Accountants", "professional_services", "..1187", "quarterly"),
    ("V-009", "Trainline", "travel", None, "travel"),
    ("V-010", "Slack Technologies", "software", "..8843", "monthly_fixed"),
]

FIXED = {"V-002": 195.00, "V-003": 96.00, "V-004": 138.00, "V-010": 87.50}
CONTRACTOR = {"V-005": (4200, 4800), "V-006": (3600, 4100)}

txns, n = [], 0


def add(v, amount, d, channel, inv=None, desc=""):
    global n
    n += 1
    vid, name, cat, bank, _ = v
    txns.append({
        "txn_id": f"T-{n:04d}", "vendor_id": vid, "vendor_name": name,
        "amount": round(amount, 2), "currency": "GBP", "date": d.isoformat(),
        "category": cat, "channel": channel, "invoice_number": inv,
        "description": desc, "bank_account": bank if channel != "card" else None,
    })


vmap = {v[0]: v for v in VENDORS}
for m in range(4, 10):  # Apr..Sep
    ym = f"2026{m:02d}"
    add(vmap["V-001"], random.uniform(1650, 2350), date(2026, m, 3), "card", None, f"AWS usage {ym}")
    for vid, amt in FIXED.items():
        add(vmap[vid], amt, date(2026, m, 1 + int(vid[-1]) % 5), "card", None, f"{vmap[vid][1]} subscription")
    for vid, (lo, hi) in CONTRACTOR.items():
        d = date(2026, m, 25) + timedelta(days=random.choice([-1, 0, 0, 1]))
        add(vmap[vid], round(random.uniform(lo, hi) / 50) * 50, d, "bill",
            f"{vid[-1]}{ym}-{random.randint(10, 99)}", f"{vmap[vid][1]} - {m:02d}/2026 services")
    add(vmap["V-007"], 2400.00, date(2026, m, 1), "bill", f"HDC-{ym}", "Monthly desk rental, 6 desks")
    for _ in range(random.choice([1, 2, 3])):
        add(vmap["V-009"], random.choice([62.40, 88.10, 124.50, 156.00, 210.30, 318.75]),
            date(2026, m, random.randint(5, 26)), "card", None, "Rail travel - client visit")
    if m in (4, 7):
        add(vmap["V-008"], 1850.00, date(2026, m, 15), "bill", f"LL-Q{(m - 1) // 3}-2026", "Quarterly bookkeeping & VAT")

vendors = [{"vendor_id": v[0], "name": v[1], "category": v[2], "bank_account": v[3]} for v in VENDORS]

pending = [
    {"bill_id": "B-0101", "vendor_id": "V-005", "vendor_name": "Priya Shah Consulting", "amount": 4500.00,
     "invoice_number": "5202610-41", "issue_date": "2026-10-18", "due_date": "2026-10-25",
     "category": "contractor", "description": "Priya Shah Consulting - 10/2026 services", "bank_account": "..7731"},
    {"bill_id": "B-0102", "vendor_id": "V-006", "vendor_name": "Reid Dev Studio", "amount": 3850.00,
     "invoice_number": "6202610-17", "issue_date": "2026-10-18", "due_date": "2026-10-25",
     "category": "contractor", "description": "Reid Dev Studio - 10/2026 services", "bank_account": "..2209"},
    {"bill_id": "B-0103", "vendor_id": "V-007", "vendor_name": "Harbour Desk Coworking", "amount": 2400.00,
     "invoice_number": "HDC-202610", "issue_date": "2026-09-28", "due_date": "2026-10-01",
     "category": "rent", "description": "Monthly desk rental, 6 desks", "bank_account": "..6604"},
    {"bill_id": "B-0104", "vendor_id": "V-008", "vendor_name": "Ledgerline Accountants", "amount": 1850.00,
     "invoice_number": "LL-Q3-2026", "issue_date": "2026-10-10", "due_date": "2026-10-24",
     "category": "professional_services", "description": "Quarterly bookkeeping & VAT", "bank_account": "..1187"},
]
for b in pending:
    b["currency"] = "GBP"

snapshot = {
    "company": "Kestrel Analytics Ltd (sample)",
    "as_of": "2026-10-20",
    "cash_balance": 412500.00,
    "monthly_burn": 41800.00,
    "vendors": vendors,
    "transactions": txns,
    "pending_bills": pending,
}

out = Path(__file__).with_name("sample_snapshot.json")
out.write_text(json.dumps(snapshot, indent=2))
print(f"wrote {out} - {len(txns)} transactions, {len(pending)} pending bills")
