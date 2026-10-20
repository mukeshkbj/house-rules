"""Run the full House Rules loop on the sandbox snapshot and render report/house-rules-report.html."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from house_rules import seapoint  # noqa: E402
from house_rules.engine import Engine  # noqa: E402

LIVE = "--live" in sys.argv
e = Engine(seapoint.load("seapoint"), live=LIVE)
e.mine()
for r in e.rules:
    if r.get("confidence", 0) >= 0.8:
        e.set_status(r["id"], "approved")
decisions = e.review_pending()
e.attack()
missed = [a["attack_id"] for a in e.attacks if not a["caught"]]
patch = e.propose_patch(missed[0]) if missed else None
if patch:
    e.set_status(patch["id"], "approved")
    e.replay(missed)

bills = {b["bill_id"]: b for b in e.snap["pending_bills"]}
data = {
    "mode": "Live: Claude agents (" + __import__("house_rules.llm", fromlist=["MODEL"]).MODEL + ")" if LIVE else "Offline: code agents",
    "company": e.snap["company"], "as_of": e.snap["as_of"], "cash": e.snap["cash_balance"],
    "burn": e.snap["monthly_burn"], "txn_count": len(e.snap["transactions"]), "vendor_count": len(e.snap["vendors"]),
    "policy_v": e.version,
    "rules": [{k: r.get(k) for k in ("id", "name", "type", "condition", "params", "action", "confidence", "status", "origin")}
              | {"support": r["evidence"].get("support_count"), "bt_in": r["backtest"]["in_scope"],
                 "bt_breach": r["backtest"]["breaches"], "bt_ids": r["backtest"]["breach_ids"]} for r in e.rules],
    "decisions": [{"bill": bills[k], "decision": d["decision"], "reason": d["reason"], "code_decision": d["code_decision"], "llm_decision": d.get("llm_decision"),
                   "invariants": [{"id": f["id"], "message": f["message"]} for f in d["invariants"]],
                   "matched": d["rule_check"]["matched"], "breaches": d["rule_check"]["breaches"]}
                  for k, d in decisions.items()],
    "attacks": [{"id": a["attack_id"], "technique": a["technique"], "idea": a["why_it_might_pass"], "bill": a["bill"],
                 "decision": a["result"]["decision"], "reason": a["result"]["reason"], "caught": a["caught"],
                 "history": a["history"]} for a in e.attacks],
    "patch": patch and {"id": patch["id"], "name": patch["name"], "condition": patch["condition"],
                        "rationale": patch["patch"]["rationale"], "for": patch["patch"]["for_attack"],
                        "bt_in": patch["backtest"]["in_scope"], "bt_breach": patch["backtest"]["breaches"]},
    "flagged_history": [t for t in e.snap["transactions"] if patch and t["txn_id"] in patch["backtest"]["breach_ids"]],
    "payroll": e.snap.get("payroll_payouts", []),
    "audit": e.audit,
    "score": e.scoreboard(),
}
tpl = (ROOT / "report" / "template.html").read_text()
out = ROOT / "report" / ("house-rules-report-live.html" if LIVE else "house-rules-report.html")
(ROOT / "data" / ("live_run.json" if LIVE else "offline_run.json")).write_text(json.dumps(data, indent=1, default=str))
html = tpl.replace("/*DATA*/null", json.dumps(data, default=str).replace("</", "<\\/"))
if LIVE:
    html = html.replace("<title>House Rules Agent Report</title>", "<title>House Rules Live Run</title>")
out.write_text(html)
print(out, f"{len(data['rules'])} rules, {len(data['decisions'])} decisions, {len(data['attacks'])} attacks")
