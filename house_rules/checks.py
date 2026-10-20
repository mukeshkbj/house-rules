"""Deterministic controls. No LLM in this file.

Two layers:
  1. Hard invariants - always on, can't be edited or overruled by any agent.
  2. Rule checks    - apply the founder-approved rules mechanically where the
                      rule type is machine-checkable.

The Guardian (LLM) sees these results and may only make a decision STRICTER.
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

SEVERITY = {"approve": 0, "hold": 1, "escalate": 2}

HARD_CEILING = 10_000.00          # anything at or above needs dual approval
DUPLICATE_WINDOW_DAYS = 20        # same vendor, similar amount, within this window
PAID_ON_RECEIPT_DAYS = 5          # same vendor, exact amount, paid within days of the invoice date
NEAR_AMOUNT_PCT = 0.01            # "similar amount" = within 1%
LOOKALIKE_RATIO = 0.85            # name similarity that counts as a lookalike

INJECTION = re.compile(
    r"(\bsystem\b\s*(note|prompt|:)|ignore (all|previous|the)|skip (the )?(review|checks?|approval)"
    r"|pre-?approved|approved by (the )?(ceo|cfo|founder|director)|do not (flag|review|escalate)"
    r"|override|urgent(ly)?[,.]? pay|pay (it )?today|assistant:)",
    re.IGNORECASE,
)


def strictest(*decisions: str) -> str:
    return max(decisions, key=lambda d: SEVERITY[d])


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _bill_date(b: dict) -> date | None:
    return _d(b.get("due_date") or b.get("issue_date") or b.get("date"))


# ---------------------------------------------------------------- invariants

def hard_invariants(bill: dict, snapshot: dict, queue: list[dict]) -> list[dict]:
    """Return findings: {id, severity, message, evidence}. Empty list = clean."""
    findings = []
    vendors = {v["vendor_id"]: v for v in snapshot["vendors"]}
    vendor = vendors.get(bill.get("vendor_id"))
    amount = float(bill.get("amount") or 0)
    bdate = _bill_date(bill)

    # INV-1 duplicate / near-duplicate (history + other bills in the queue)
    inv = _norm(bill.get("invoice_number"))
    others = [
        {**t, "_id": t["txn_id"], "_date": _d(t["date"])} for t in snapshot["transactions"]
    ] + [
        {**b, "_id": b["bill_id"], "_date": _bill_date(b)} for b in queue if b["bill_id"] != bill["bill_id"]
    ]
    for o in others:
        same_vendor = o.get("vendor_id") == bill.get("vendor_id")
        if not same_vendor:
            continue
        oinv = _norm(o.get("invoice_number"))
        inv_match = bool(inv and oinv and (inv == oinv or (min(len(inv), len(oinv)) >= 6
                                                          and (inv.startswith(oinv) or oinv.startswith(inv)))))
        amt_close = abs(float(o["amount"]) - amount) <= max(amount, 1) * NEAR_AMOUNT_PCT
        near_in_time = bdate and o["_date"] and abs((bdate - o["_date"]).days) <= DUPLICATE_WINDOW_DAYS
        issued = _d(bill.get("issue_date"))
        paid_on_receipt = (issued and o["_date"] and abs(float(o["amount"]) - amount) < 0.005
                           and abs((issued - o["_date"]).days) <= PAID_ON_RECEIPT_DAYS)
        if inv_match or (amt_close and near_in_time) or paid_on_receipt:
            findings.append({
                "id": "INV-1", "severity": "escalate",
                "message": (f"Already paid by card on {o['date']} (£{float(o['amount']):,.2f}) - possible duplicate (" if o.get('channel') == 'card' else f"Possible duplicate of {o['_id']} (") +
                           ("same invoice number" if inv_match else "same vendor, amount within 1%, within 20 days" if amt_close and near_in_time else "exact amount paid within 5 days of the invoice date") + ")",
                "evidence": [o["_id"]],
            })
            break

    # INV-2 bank details differ from vendor master
    if vendor and vendor.get("bank_account") and bill.get("bank_account") \
            and bill["bank_account"] != vendor["bank_account"]:
        findings.append({
            "id": "INV-2", "severity": "escalate",
            "message": f"Bank details changed: master {vendor['bank_account']}, bill {bill['bank_account']}. "
                       "Verify by phone using a number already on file.",
            "evidence": [vendor["vendor_id"]],
        })

    # INV-6 payee account given on the bill, but none on file for this vendor
    if vendor and not vendor.get("bank_account") and bill.get("bank_account"):
        findings.append({
            "id": "INV-6", "severity": "escalate",
            "message": f"Pays account {bill['bank_account']}, but no account is on file for {vendor['name']}. "
                       "Verify by phone using a number already on file before saving the payee.",
            "evidence": [vendor["vendor_id"]],
        })

    # INV-7 Seapoint says this invoice number was already paid (exact match, not a heuristic)
    if bill.get("matched_transaction_id"):
        findings.append({"id": "INV-7", "severity": "escalate",
                         "message": f"Seapoint already matched this invoice to payment {bill['matched_transaction_id']}.",
                         "evidence": [bill["matched_transaction_id"]]})
    elif inv:
        same = next((p for p in snapshot.get("paid_invoices", []) if _norm(p["invoice_number"]) == inv and (
            p.get("company_number") == bill.get("vendor_company_number")
            or _norm(p["vendor_name"]) == _norm(bill.get("vendor_name")))), None)
        if same:
            findings.append({"id": "INV-7", "severity": "escalate",
                             "message": f"Invoice {bill['invoice_number']} was already paid on {same['paid_at']} "
                                        f"(Seapoint matched it to {same['transaction_id']}).",
                             "evidence": [same["transaction_id"]]})

    # INV-8 supplier identity on the invoice differs from the identity Seapoint has on file
    if vendor:
        for field, label in (("company_number", "Company number"), ("vat_number", "VAT number")):
            known, given = vendor.get(field), bill.get(f"vendor_{field}")
            if known and given and _norm(known) != _norm(given):
                findings.append({"id": "INV-8", "severity": "escalate",
                                 "message": f"{label} on the invoice ({given}) differs from the one on file for "
                                            f"{vendor['name']} ({known}). Possible impersonation.",
                                 "evidence": [vendor["vendor_id"]]})

    # INV-9 VAT number issued by a different country than the supplier's address
    vat, country = (bill.get("vendor_vat_number") or "").strip().upper(), (bill.get("vendor_country") or "").upper()
    prefix = re.match(r"([A-Z]{2})", vat)
    if prefix and country and prefix.group(1) not in (country, "EU") and not (prefix.group(1) == "GB" and country == "UK"):
        findings.append({"id": "INV-9", "severity": "hold",
                         "message": f"VAT number {bill['vendor_vat_number']} is registered in {prefix.group(1)}, "
                                    f"but the supplier's country is {country}. Check the supplier's details.",
                         "evidence": []})

    # INV-3 unknown vendor / lookalike name
    if not vendor:
        best, ratio = None, 0.0
        for v in vendors.values():
            r = SequenceMatcher(None, _norm(v["name"]), _norm(bill.get("vendor_name"))).ratio()
            if r > ratio:
                best, ratio = v, r
        if best and ratio >= LOOKALIKE_RATIO:
            findings.append({
                "id": "INV-3", "severity": "escalate",
                "message": f"Lookalike vendor: '{bill.get('vendor_name')}' resembles '{best['name']}' "
                           f"({ratio:.0%} similar) but is not in the vendor master.",
                "evidence": [best["vendor_id"]],
            })
        else:
            findings.append({
                "id": "INV-3", "severity": "escalate",
                "message": f"New vendor '{bill.get('vendor_name')}' - not in vendor master. Onboard and verify before paying.",
                "evidence": [],
            })

    # INV-4 hard ceiling
    if amount >= HARD_CEILING:
        findings.append({
            "id": "INV-4", "severity": "escalate",
            "message": f"£{amount:,.2f} is at or above the £{HARD_CEILING:,.0f} ceiling - two approvers required.",
            "evidence": [],
        })

    # INV-5 instruction-like text in untrusted fields
    blob = " ".join(str(bill.get(k) or "") for k in ("description", "vendor_name", "invoice_number"))
    if INJECTION.search(blob):
        findings.append({
            "id": "INV-5", "severity": "escalate",
            "message": "Bill text contains instruction-like wording aimed at the reviewer. Treated as a red flag.",
            "evidence": [],
        })

    return findings


# --------------------------------------------------------------- rule checks

def _in_scope(rule: dict, bill: dict) -> bool:
    scope = rule.get("scope") or {}
    if scope.get("vendor_id"):
        return scope["vendor_id"] == bill.get("vendor_id")
    if scope.get("category"):
        return scope["category"] == bill.get("category")
    return False


def rule_checks(bill: dict, rules: list[dict], snapshot: dict, queue: list[dict]) -> dict:
    """Apply approved rules mechanically.

    Returns {decision, matched: [rule ids], breaches: [{rule_id, severity, message}]}
    decision is what the rules alone would say.
    """
    amount = float(bill.get("amount") or 0)
    bdate = _bill_date(bill)
    matched, breaches, approving = [], [], []

    for r in rules:
        if not _in_scope(r, bill):
            continue
        p, t = r.get("params") or {}, r.get("type")
        breach = None
        if t in ("amount_range", "category_ceiling"):
            lo, hi = p.get("min"), p.get("max")
            if lo is not None and amount < lo:
                breach = f"£{amount:,.2f} is below the usual minimum £{lo:,.2f}"
            elif hi is not None and amount > hi:
                breach = f"£{amount:,.2f} is above the usual maximum £{hi:,.2f}"
        elif t == "payment_timing" and bdate:
            lo, hi = p.get("day_from"), p.get("day_to")
            if lo is not None and hi is not None and not (lo <= bdate.day <= hi):
                breach = f"Due on day {bdate.day}; normally paid between the {lo}th and {hi}th"
        elif t == "frequency" and bdate and p.get("per_month"):
            ym = (bdate.year, bdate.month)
            same = [t_ for t_ in snapshot["transactions"]
                    if t_["vendor_id"] == bill.get("vendor_id") and t_["txn_id"] != bill.get("txn_id")
                    and _d(t_["date"]).timetuple()[:2] == ym]
            same += [b for b in queue if b["bill_id"] != bill["bill_id"]
                     and b.get("vendor_id") == bill.get("vendor_id")
                     and _bill_date(b) and _bill_date(b).timetuple()[:2] == ym]
            if len(same) + 1 > p["per_month"]:
                ids = [x.get("txn_id") or x.get("bill_id") for x in same]
                breach = (f"{len(same) + 1} invoices from this vendor in {bdate:%B %Y}; "
                          f"policy allows {p['per_month']} (others: {', '.join(ids)})")
        else:
            continue  # not machine-checkable; left to the Guardian

        if breach:
            sev = "escalate" if t == "frequency" else "hold"
            breaches.append({"rule_id": r["id"], "severity": sev, "message": f"{r['name']}: {breach}"})
        else:
            matched.append(r["id"])
            if r.get("action") == "auto_approve":
                approving.append(r["id"])

    if breaches:
        decision = strictest(*[b["severity"] for b in breaches])
    elif approving:
        decision = "approve"
    elif matched:
        decision = "hold"
    else:
        decision = "escalate" if amount > 500 else "hold"  # nothing in policy covers it
    return {"decision": decision, "matched": matched, "breaches": breaches}


# ------------------------------------------------------------------ payroll

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
OPEN_RUN = {"draft", "needs_approval", "to_pay", "scheduled", "sending"}


def _run_month(run: dict) -> tuple[int, int] | None:
    p = (run.get("period") or "").lower()
    if m := re.match(r"(\d{4})-(\d{2})-\d{2}", p):
        return int(m[1]), int(m[2])
    if m := re.search(r"(" + "|".join(MONTHS) + r")\s+(\d{4})", p):
        return int(m[2]), MONTHS[m[1]]
    return None


def payroll_findings(runs: list[dict]) -> list[dict]:
    """Checks on Seapoint pay runs: a period paid twice, a run paid before its period, a changed payee account."""
    findings, paid_by_month = [], {}
    for r in runs:
        if r["status"] in ("paid", "partially_paid") and _run_month(r):
            paid_by_month.setdefault(_run_month(r), r)
    for r in runs:
        month = _run_month(r)
        if r["status"] in OPEN_RUN and month in paid_by_month:
            done = paid_by_month[month]
            findings.append({"id": "PAY-1", "severity": "escalate", "run_id": r["id"], "amount": r["total"],
                             "message": f"'{r['name']}' ({r['status']}, £{r['total']:,.2f}) is for {r['period']}, which was "
                                        f"already paid in '{done['name']}' on {done['pay_date']}. Approving it pays the "
                                        f"period twice."})
        if r["status"] == "paid" and month and r.get("pay_date") and date.fromisoformat(r["pay_date"]) < date(*month, 1):
            findings.append({"id": "PAY-2", "severity": "hold", "run_id": r["id"], "amount": r["total"],
                             "message": f"'{r['name']}' was paid on {r['pay_date']}, before its period starts. "
                                        f"That month shows two salary payments in the bank."})
    accounts = {}
    for r in sorted(runs, key=lambda r: r.get("created_at") or ""):
        for emp_id, name, _net, last4 in r.get("employees", []):
            if emp_id in accounts and accounts[emp_id] != last4:
                findings.append({"id": "PAY-3", "severity": "escalate", "run_id": r["id"], "amount": None,
                                 "message": f"{name}'s pay account changed from ..{accounts[emp_id]} to ..{last4} "
                                            f"in '{r['name']}'. Verify with the employee directly."})
            accounts[emp_id] = last4
    return findings
