"""Build data/seapoint_snapshot.json from raw Seapoint MCP pulls in data/raw/.

raw/txns_p*.json  query_transactions rows (bank payments, direct debits, transfers)
raw/queue.json    unpaid invoices + payments not yet sent
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"
OUT = Path(__file__).resolve().parent / "seapoint_snapshot.json"
SUFFIX = re.compile(r"\b(ltd|limited|uk|llp|plc|pbc|bv|inc|computing|technologies|solicitors|society)\b")


def key(name):
    return re.sub(r"[^a-z0-9]", "", SUFFIX.sub("", name.lower()))


rows = [r for p in sorted(RAW.glob("txns_p*.json")) for r in json.loads(p.read_text())["data"]]
q = json.loads((RAW / "queue.json").read_text())

vendors, transactions = {}, []
for r in rows:
    p = r.get("participant") or {}
    vid = p.get("id") or "raw:" + key(p.get("name") or r["description"])
    name = p.get("name") or r["description"]
    category = (r.get("category") or {}).get("name", "uncategorised").split(" › ")[-1].lower()
    vendors.setdefault(vid, {"vendor_id": vid, "name": name, "category": category, "bank_account": None})
    transactions.append({
        "txn_id": r["id"], "vendor_id": vid, "vendor_name": name,
        "amount": r["reporting_amount"]["amount"], "currency": "GBP",
        "date": r["date"][:10], "category": category,
        "channel": {"DIRECT_DEBIT": "direct_debit", "TRANSFER": "transfer"}.get(r["type"], "bill"),
        "invoice_number": r.get("reference"), "description": r["description"], "bank_account": None,
    })


def match(name):
    k = key(name)
    best, score = None, 0.0
    for v in vendors.values():
        vk = key(v["name"])
        s = 1.0 if vk and (k.startswith(vk) or vk.startswith(k)) else SequenceMatcher(None, k, vk).ratio()
        if s > score:
            best, score = v, s
    return best if score >= 0.8 else None


def bill(bid, name, amount, cur, ref, issue, due, desc, bank=None):
    v = match(name)
    return {
        "bill_id": bid, "vendor_id": v["vendor_id"] if v else "new:" + key(name), "vendor_name": name,
        "amount": amount, "currency": "GBP" if "->" in cur else cur, "invoice_number": ref,
        "issue_date": issue, "due_date": due, "category": v["category"] if v else "unknown",
        "description": desc, "bank_account": bank,
    }


pending = [bill(i, n, a, c, ref, iss, due, f"{desc} [source: {src}]")
           for i, n, a, c, ref, iss, due, src, desc in q["invoices"]]
by_id = {b["bill_id"]: b for b in pending}
for i, n, a, c, ref, sched, kind, bank, inv in q["payments"]:
    if inv in by_id:
        by_id[inv]["bank_account"] = bank
        by_id[inv]["description"] += f" [payment {i} drafted to a one-off '{kind}' payee, not a saved beneficiary]"
    else:
        pending.append(bill(i, n, a, c, ref, sched, sched, f"Payment awaiting release to {kind} payee: {ref}", bank))

snap = {
    "source": "seapoint",
    "company": "Northstar Labs Ltd (Seapoint sandbox)",
    "as_of": "2026-10-20",
    "cash_balance": q["cash_balance"],
    "monthly_burn": q["monthly_burn_gross_3m_avg"],
    "vendors": sorted(vendors.values(), key=lambda v: v["name"]),
    "transactions": sorted(transactions, key=lambda t: t["date"]),
    "pending_bills": pending,
    "payroll_payouts": [dict(zip(("payment_id", "name", "employee_id", "amount"), p)) for p in q["payroll_payouts"]],
}
OUT.write_text(json.dumps(snap, indent=2))
print(f"{OUT.name}: {len(snap['vendors'])} vendors, {len(transactions)} txns, {len(pending)} pending")
for b in pending:
    print(f"  {b['bill_id'][:14]:14s} {b['vendor_name'][:28]:28s} -> {b['vendor_id'][:30]:30s} £{b['amount']:>9,.2f} due {b['due_date']}")
