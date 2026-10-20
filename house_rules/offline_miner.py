"""Keyless Miner: derives rules from payment history in plain code.

Used when no ANTHROPIC_API_KEY is set. Emits the same rule shape as prompts/miner.md.
Frequency rules are deliberately not mined - that gap is what the red team finds.
"""
from __future__ import annotations

from collections import defaultdict

MIN_SUPPORT = 4


def mine(snapshot: dict) -> dict:
    groups = defaultdict(list)
    for t in snapshot["transactions"]:
        if not t["vendor_name"].lower().startswith("unknown"):
            groups[t["vendor_id"]].append(t)

    rules = []
    for vid, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(ts) < MIN_SUPPORT:
            continue
        name = ts[0]["vendor_name"]
        amounts = [t["amount"] for t in ts]
        days = [int(t["date"][8:10]) for t in ts]
        lo, hi = min(amounts), max(amounts)
        fixed = lo == hi
        support = len(ts)
        evidence = {"support_count": support, "counter_examples": 0, "example_txn_ids": [t["txn_id"] for t in ts[:5]]}
        n = len(rules) + 1
        rules.append({
            "id": f"R-{n:03d}", "name": f"{name} {'fixed amount' if fixed else 'usual range'}",
            "type": "amount_range", "scope": {"vendor_id": vid},
            "condition": f"{name} is paid {'exactly' if fixed else 'between'} £{lo:,.2f}"
                         + ("" if fixed else f" and £{hi:,.2f}") + f" ({support} payments)",
            "breach_condition": "Amount outside the historical range",
            "params": {"min": lo, "max": hi} if fixed else {"min": round(lo * 0.9, 2), "max": round(hi * 1.1, 2)},
            "action": "auto_approve" if support >= 5 else "hold",
            "evidence": evidence, "confidence": round(min(0.97, 0.6 + 0.05 * support + (0.05 if fixed else 0)), 2),
        })
        if max(days) - min(days) <= 3:
            rules.append({
                "id": f"R-{n + 1:03d}", "name": f"{name} paid around day {min(days)}", "type": "payment_timing",
                "scope": {"vendor_id": vid},
                "condition": f"{name} falls due between day {min(days)} and {max(days)} of the month",
                "breach_condition": "Due date more than 2 days outside that window",
                "params": {"day_from": max(1, min(days) - 2), "day_to": min(31, max(days) + 2)},
                "action": "hold", "evidence": evidence, "confidence": round(min(0.95, 0.55 + 0.06 * support), 2),
            })
    return {"rules": rules}
