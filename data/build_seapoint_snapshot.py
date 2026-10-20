"""Build data/seapoint_snapshot.json from raw Seapoint MCP pulls in data/raw/.

raw/txns_p*.json         query_transactions rows: bank payments, direct debits, transfers
raw/invoices.json        query_invoices, paid and unpaid, with supplier VAT/company numbers and matched transaction ids
raw/seapoint_extra.json  supplier list (query_transaction_participants), payments waiting to go out (query_payments),
                         card payments for suppliers with open invoices, pay runs (query_payroll), cash and burn
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"
OUT = Path(__file__).resolve().parent / "seapoint_snapshot.json"
SUFFIX = re.compile(r"\b(ltd|limited|uk|llp|plc|pbc|bv|inc|computing|technologies|solicitors|society)\b")


def key(name):
    return re.sub(r"[^a-z0-9]", "", SUFFIX.sub("", (name or "").lower()))


rows = [r for p in sorted(RAW.glob("txns_p*.json")) for r in json.loads(p.read_text())["data"]]
extra = json.loads((RAW / "seapoint_extra.json").read_text())
inv_file = json.loads((RAW / "invoices.json").read_text())
invoices = [dict(zip(inv_file["fields"], r)) for r in inv_file["rows"]]

# Supplier master: Seapoint's own participant ids and categories
vendors = {vid: {"vendor_id": vid, "name": name, "category": cat.lower(), "bank_account": None,
                 "company_number": None, "vat_number": None}
           for vid, name, cat in extra["participants"]}

transactions, txn_vendor = [], {}
for r in rows:
    p = r.get("participant") or {}
    vid = p.get("id") or "raw:" + key(p.get("name") or r["description"])
    name = p.get("name") or r["description"]
    category = (r.get("category") or {}).get("name", "uncategorised").split(" › ")[-1].lower()
    vendors.setdefault(vid, {"vendor_id": vid, "name": name, "category": category, "bank_account": None,
                             "company_number": None, "vat_number": None})
    txn_vendor[r["id"]] = vid
    transactions.append({
        "txn_id": r["id"], "vendor_id": vid, "vendor_name": name,
        "amount": r["reporting_amount"]["amount"], "currency": "GBP", "date": r["date"][:10], "category": category,
        "channel": {"DIRECT_DEBIT": "direct_debit", "TRANSFER": "transfer"}.get(r["type"], "bill"),
        "invoice_number": r.get("reference"), "description": r["description"], "bank_account": None,
    })
for vid, day, amount in extra["card_payments"]:
    v = vendors[vid]
    transactions.append({"txn_id": f"card:{vid}:{day}", "vendor_id": vid, "vendor_name": v["name"], "amount": amount,
                         "currency": "GBP", "date": day, "category": v["category"], "channel": "card",
                         "invoice_number": None, "description": f"{v['name']} card payment", "bank_account": None})

# Supplier identity from invoices Seapoint has already matched to a payment
paid = [i for i in invoices if i["is_paid"]]
for i in paid:
    vid = txn_vendor.get(i["transaction_id"])
    if vid:
        vendors[vid]["company_number"] = vendors[vid]["company_number"] or i["company_number"]
        vendors[vid]["vat_number"] = vendors[vid]["vat_number"] or i["vat_number"]


def match(name, company_number=None):
    if company_number:
        hit = next((v for v in vendors.values() if v["company_number"] == company_number), None)
        if hit:
            return hit
    k = key(name)
    best, score = None, 0.0
    for v in vendors.values():
        vk = key(v["name"])
        if not vk:
            continue
        if k == vk:
            s = 1.0
        elif k.startswith(vk) or vk.startswith(k):  # prefer the longest shared prefix: "Amazon Web Services" over "Amazon"
            s = 0.9 + 0.09 * min(len(k), len(vk)) / max(len(k), len(vk))
        else:
            s = SequenceMatcher(None, k, vk).ratio()
        if s > score:
            best, score = v, s
    return best if score >= 0.8 else None


def bill_from_invoice(i):
    v = match(i["vendor_name"], i["company_number"])
    return {
        "bill_id": i["id"], "vendor_id": v["vendor_id"] if v else "new:" + key(i["vendor_name"]),
        "vendor_name": i["vendor_name"], "amount": i["gbp"], "currency": "GBP", "invoice_number": i["reference"],
        "issue_date": i["invoice_date"], "due_date": i["due_date"], "category": v["category"] if v else "unknown",
        "description": f"{i['summary']} [source: {i['source']}]", "bank_account": None,
        "vendor_country": i["country"], "vendor_vat_number": i["vat_number"],
        "vendor_company_number": i["company_number"], "received_at": i["created_at"],
        "matched_transaction_id": i["transaction_id"],
    }


pending = [bill_from_invoice(i) for i in invoices if not i["is_paid"]]
by_id = {b["bill_id"]: b for b in pending}
for pid, _status, name, amount, ref, sched, kind, bank, inv in extra["payments"]:
    if inv in by_id:
        by_id[inv]["bank_account"] = bank
        by_id[inv]["description"] += f" [payment {pid} drafted to a one-off '{kind}' payee, not a saved beneficiary]"
    else:
        v = match(name)
        pending.append({"bill_id": pid, "vendor_id": v["vendor_id"] if v else "new:" + key(name), "vendor_name": name,
                        "amount": amount, "currency": "GBP", "invoice_number": ref, "issue_date": sched, "due_date": sched,
                        "category": v["category"] if v else "unknown",
                        "description": f"Payment awaiting release to {kind} payee: {ref}", "bank_account": bank})

snap = {
    "source": "seapoint",
    "company": "Northstar Labs Ltd (Seapoint sandbox)",
    "as_of": "2026-10-20",
    "cash_balance": extra["cash_balance"],
    "monthly_burn": extra["monthly_burn_gross_3m_avg"],
    "vendors": sorted(vendors.values(), key=lambda v: v["name"]),
    "transactions": sorted(transactions, key=lambda t: t["date"]),
    "pending_bills": pending,
    "paid_invoices": [{"invoice_id": i["id"], "invoice_number": i["reference"], "vendor_name": i["vendor_name"],
                       "company_number": i["company_number"], "paid_at": i["paid_at"],
                       "transaction_id": i["transaction_id"]} for i in paid],
    "payroll_runs": extra["payroll_runs"],
}
OUT.write_text(json.dumps(snap, indent=2))
print(f"{OUT.name}: {len(snap['vendors'])} vendors, {len(transactions)} txns, {len(pending)} pending, "
      f"{len(paid)} paid invoices, {len(snap['payroll_runs'])} pay runs")
for b in pending:
    print(f"  {b['bill_id'][:14]:14s} {b['vendor_name'][:28]:28s} -> {b['vendor_id'][:30]:30s} £{b['amount']:>9,.2f}")
