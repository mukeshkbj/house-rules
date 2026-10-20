"""Review only the bills that are new since the last run, against the saved (founder-signed) policy.

    python -m house_rules.review_new            # code agents
    python -m house_rules.review_new --live     # Claude Guardian on top of the code checks

Steps: load the latest snapshot, load data/policy_<source>.json, skip bill ids already in
data/seen_bills.json, review the rest, write data/reviews/<timestamp>.json and log to the policy's
audit trail. Read-only: nothing is paid or changed in Seapoint.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from . import checks, seapoint
from .engine import ROOT, Engine

SEEN = ROOT / "data" / "seen_bills.json"
REVIEWS = ROOT / "data" / "reviews"


def run(source: str = "seapoint", live: bool = False, seen_path: Path = SEEN, out_dir: Path = REVIEWS,
        policy_path: Path | None = None, snapshot: dict | None = None) -> dict:
    eng = Engine(snapshot or seapoint.load(source), live=live)
    if not eng.load_policy(policy_path):
        raise SystemExit(f"No saved policy at {policy_path or eng.policy_path()}. Approve rules in the app and click 'Save policy'.")
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    queue = eng.snap["pending_bills"]
    new = [b for b in queue if b["bill_id"] not in seen]

    results = eng._map(lambda b: eng.review(b, queue), new)
    payroll = [f for f in checks.payroll_findings(eng.snap.get("payroll_runs", [])) if f"{f['id']}:{f['run_id']}" not in seen]
    report = {"reviewed_at": datetime.now().isoformat(timespec="seconds"), "policy_v": eng.version,
              "mode": "live" if live else "offline", "new_bills": len(new), "already_seen": len(queue) - len(new),
              "decisions": [{"bill": b, **{k: r[k] for k in ("decision", "reason", "code_decision")},
                             "checks": [f["id"] for f in r["invariants"]]} for b, r in zip(new, results)],
              "payroll": payroll}
    if new or payroll:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"review_{report['reviewed_at'].replace(':', '')}.json").write_text(json.dumps(report, indent=1, default=str))
        counts = {d: sum(1 for x in results if x["decision"] == d) for d in ("approve", "hold", "escalate")}
        eng.log("Guardian", "reviewed new bills", ", ".join(f"{v} {k}" for k, v in counts.items())
                + (f"; {len(payroll)} payroll findings" if payroll else ""))
        eng.save_policy(policy_path)
        seen_path.write_text(json.dumps(sorted(seen | {b["bill_id"] for b in new}
                                               | {f"{f['id']}:{f['run_id']}" for f in payroll}), indent=1))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--source", default="seapoint")
    args = ap.parse_args()
    rep = run(args.source, args.live)
    print(f"policy v{rep['policy_v']} · {rep['new_bills']} new bills · {rep['already_seen']} already reviewed")
    for d in rep["decisions"]:
        b = d["bill"]
        print(f"  {d['decision']:8s} {b['vendor_name'][:28]:28s} £{b['amount']:>10,.2f}  {d['reason'][:110]}")
    for f in rep["payroll"]:
        print(f"  {f['severity']:8s} PAYROLL {f['id']}  {f['message']}")
