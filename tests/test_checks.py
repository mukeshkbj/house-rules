"""Run: python -m pytest -q   (or just: python tests/test_checks.py)"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from house_rules import seapoint
from house_rules.engine import Engine

def _engine():
    e = Engine(seapoint.load("sample"), live=False)
    e.mine()
    for r in e.rules:
        e.set_status(r["id"], "approved")
    return e

def test_legit_bills_approved():
    assert all(d["decision"] == "approve" for d in _engine().review_pending().values())

def test_only_staged_attack_misses_then_patch_catches_it():
    e = _engine()
    e.attack()
    assert [a["attack_id"] for a in e.attacks if not a["caught"]] == ["A-10"]
    p = e.propose_patch("A-10")
    assert p["backtest"]["breaches"] == 0          # no false alarms on history
    e.set_status(p["id"], "approved")
    e.replay(["A-10"])
    assert e.scoreboard()["missed"] == 0
    assert all(d["decision"] == "approve" for d in e.review_pending().values())  # patch doesn't block legit bills

def test_rules_never_loosen_invariants():
    e = _engine()
    bill = dict(e.snap["pending_bills"][0], bill_id="X", bank_account="..0000")
    assert e.review(bill, e.snap["pending_bills"])["decision"] == "escalate"

def _sandbox():
    e = Engine(seapoint.load("seapoint"), live=False)
    e.mine()
    for r in e.rules:
        e.set_status(r["id"], "approved")
    return e

def test_sandbox_real_catches():
    e = _sandbox()
    decisions = e.review_pending()
    approved = sorted(b["vendor_name"] for b in e.snap["pending_bills"] if decisions[b["bill_id"]]["decision"] == "approve")
    assert approved == ["Amazon Web Services UK Ltd", "Nordhaus Studio BV"]

def test_sandbox_staged_miss_patch_finds_double_payroll():
    e = _sandbox()
    e.attack()
    assert [a["attack_id"] for a in e.attacks if not a["caught"]] == ["A-10"]
    p = e.propose_patch("A-10")
    assert p["backtest"]["breaches"] == 6           # September salaries paid twice - real findings
    e.set_status(p["id"], "approved")
    e.replay(["A-10"])
    assert e.scoreboard()["missed"] == 0

def test_founder_edit_tightens_policy_and_is_logged():
    e = _sandbox()
    nordhaus = next(b for b in e.snap["pending_bills"] if b["vendor_name"].startswith("Nordhaus"))
    assert e.review(nordhaus, e.snap["pending_bills"])["decision"] == "approve"
    rule = next(r for r in e.rules if r["type"] == "amount_range" and r["scope"].get("vendor_id") == nordhaus["vendor_id"])
    v = e.version
    e.edit_params(rule["id"], {"max": 7500.0})
    assert e.version == v + 1 and e.audit[-1]["action"] == "edited rule"
    assert e.review(nordhaus, e.snap["pending_bills"])["decision"] == "hold"

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("pass", name)
