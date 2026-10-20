"""House Rules orchestration: mine -> approve -> guard -> attack -> patch -> replay.

Works in two modes:
  live=True   agents are Claude calls (prompts/*.md)
  live=False  offline mock (canned rules, attack catalogue, code-only Guardian) -
              for building the UI before the night and as a demo fallback.
Deterministic checks (checks.py) run in BOTH modes and always have the last word on strictness.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import checks, llm, offline_miner

ROOT = Path(__file__).resolve().parent.parent
def _techniques(source: str) -> list[dict]:
    sub = "seapoint/" if source == "seapoint" else ""
    return json.loads((ROOT / "data" / f"{sub}attacks.json").read_text())["attacks"]


class Engine:
    def __init__(self, snapshot: dict, live: bool = False):
        self.snap = snapshot
        self.live = live
        self.source = snapshot.get("source", "sample")
        self.techniques = _techniques(self.source)
        self.rules: list[dict] = []          # each has status: proposed | approved | rejected
        self.version = 0
        self.audit: list[dict] = []
        self.decisions: dict[str, dict] = {}  # bill_id -> decision
        self.attacks: list[dict] = []         # attack + result
        self.patches: list[dict] = []
        self.round = 0

    # ------------------------------------------------------------ saved policy
    def policy_path(self) -> Path:
        return ROOT / "data" / f"policy_{self.source}.json"

    def save_policy(self, path: Path | None = None) -> Path:
        """Persist the signed policy so new bills are judged against it, not a freshly mined one."""
        path = path or self.policy_path()
        self.log("Founder", "saved policy", f"v{self.version}, {len(self.approved())} approved rules")
        path.write_text(json.dumps({"source": self.source, "version": self.version,
                                    "saved_at": datetime.now().isoformat(timespec="seconds"),
                                    "rules": self.rules, "audit": self.audit}, indent=1, default=str))
        return path

    def load_policy(self, path: Path | None = None) -> bool:
        path = path or self.policy_path()
        if not path.exists():
            return False
        saved = json.loads(path.read_text())
        self.rules, self.version, self.audit = saved["rules"], saved["version"], saved["audit"]
        for r in self.rules:  # history may have grown since the policy was saved
            r["backtest"] = self.backtest(r)
        self.log("System", "loaded policy", f"v{self.version} saved {saved.get('saved_at', '?')}")
        return True

    # ------------------------------------------------------------ helpers
    def log(self, actor: str, action: str, detail: str = ""):
        self.audit.append({"time": datetime.now().strftime("%H:%M:%S"), "policy_v": self.version,
                           "actor": actor, "action": action, "detail": detail})

    def approved(self) -> list[dict]:
        return [r for r in self.rules if r["status"] == "approved"]

    def backtest(self, rule: dict) -> dict:
        """Run one rule over history. A good rule fits history: few or no breaches."""
        in_scope = [t for t in self.snap["transactions"] if checks._in_scope(rule, t)]
        breaches = []
        for t in in_scope:
            res = checks.rule_checks({**t, "due_date": t["date"]}, [rule], self.snap, [])
            if res["breaches"]:
                breaches.append(t["txn_id"])
        return {"in_scope": len(in_scope), "breaches": len(breaches), "breach_ids": breaches[:5],
                "examples": [t["txn_id"] for t in in_scope[:5]]}

    def _add_rule(self, rule: dict, origin: str):
        rule = {**rule, "status": "proposed", "origin": origin}
        rule["backtest"] = self.backtest(rule)
        if not rule.get("evidence", {}).get("example_txn_ids"):
            rule.setdefault("evidence", {})["example_txn_ids"] = rule["backtest"]["examples"]
        self.rules = [r for r in self.rules if r["id"] != rule["id"]] + [rule]
        return rule

    # ------------------------------------------------------------ 1. mine
    def mine(self):
        if self.live:
            out = llm.ask_json(llm.prompt("miner"), {
                "vendors": self.snap["vendors"], "transactions": self.snap["transactions"]})
        else:
            out = (offline_miner.mine(self.snap) if self.source == "seapoint"
                   else json.loads((ROOT / "mock" / "rules.json").read_text()))
        self.rules = []
        for r in out.get("rules", []):
            self._add_rule(r, "miner")
        self.log("Miner", "proposed rules", f"{len(self.rules)} rules from {len(self.snap['transactions'])} transactions")
        return self.rules

    def set_status(self, rule_id: str, status: str, who: str = "Founder"):
        for r in self.rules:
            if r["id"] == rule_id and r["status"] != status:
                r["status"] = status
                self.version += 1
                self.log(who, f"{status} rule", f"{rule_id} - {r['name']}")

    def edit_params(self, rule_id: str, params: dict, who: str = "Founder"):
        """A person changes a rule's limits. Re-backtests, bumps the version and logs old -> new."""
        r = next(x for x in self.rules if x["id"] == rule_id)
        old = dict(r.get("params") or {})
        new = {**old, **params}
        if new == old:
            return r
        r["params"] = new
        r["edited_by"] = who
        r["backtest"] = self.backtest(r)
        self.version += 1
        changes = ", ".join(f"{k} {old.get(k)} → {v}" for k, v in params.items() if old.get(k) != v)
        self.log(who, "edited rule", f"{rule_id} - {changes}")
        return r

    # ------------------------------------------------------------ 2. guard
    def review(self, bill: dict, queue: list[dict]) -> dict:
        rules = self.approved()
        inv = checks.hard_invariants(bill, self.snap, queue)
        rc = checks.rule_checks(bill, rules, self.snap, queue)
        code_decision = checks.strictest(rc["decision"], *[f["severity"] for f in inv]) if inv else rc["decision"]

        result = {"bill_id": bill["bill_id"], "code_decision": code_decision, "invariants": inv,
                  "rule_check": rc, "policy_v": self.version}

        if self.live:
            hist = [t for t in self.snap["transactions"]
                    if t["vendor_id"] == bill.get("vendor_id") or t["category"] == bill.get("category")][-60:]
            try:
                g = llm.ask_json(llm.prompt("guardian"), {
                    "rules": rules, "vendors": self.snap["vendors"], "history": hist, "bill": bill,
                    "prechecks": {"invariants": inv, "rule_check": rc, "code_decision": code_decision}},
                    max_tokens=8000)
            except Exception as e:  # an unreachable reviewer never approves anything
                g = {"decision": "escalate", "reason": f"Guardian call failed ({type(e).__name__}); escalated for a person."}
            llm_decision = g.get("decision") if g.get("decision") in checks.SEVERITY else "escalate"
            result.update(decision=checks.strictest(code_decision, llm_decision), llm_decision=llm_decision,
                          reason=g.get("reason") or self._mock_reason(inv, rc), risk_signals=g.get("risk_signals", []),
                          rules_applied=g.get("rules_applied", rc["matched"]))
            if checks.SEVERITY[llm_decision] < checks.SEVERITY[code_decision]:
                result["reason"] += f" (Code checks raised this to '{code_decision}'.)"
        else:
            result.update(decision=code_decision, reason=self._mock_reason(inv, rc),
                          risk_signals=[f["id"] for f in inv], rules_applied=rc["matched"])
        return result

    @staticmethod
    def _mock_reason(inv, rc) -> str:
        if inv:
            return " ".join(f["message"] for f in inv)
        if rc["breaches"]:
            return " ".join(b["message"] for b in rc["breaches"])
        if rc["decision"] == "approve":
            return f"Fits approved policy ({', '.join(rc['matched'])}). Nothing unusual found."
        if rc["matched"]:
            return f"Within policy ({', '.join(rc['matched'])}) but no rule allows auto-approval."
        return "No approved rule covers this vendor or category."

    def _map(self, fn, items):
        """Guardian calls are independent; run them in parallel when they hit the API."""
        if not self.live:
            return [fn(x) for x in items]
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(fn, items))

    def review_pending(self):
        q = self.snap["pending_bills"]
        for b, d in zip(q, self._map(lambda b: self.review(b, q), q)):
            self.decisions[b["bill_id"]] = d
        counts = {d: sum(1 for x in self.decisions.values() if x["decision"] == d) for d in checks.SEVERITY}
        self.log("Guardian", "reviewed pending bills", ", ".join(f"{v} {k}" for k, v in counts.items()))
        return self.decisions

    # ------------------------------------------------------------ 3. attack
    def attack(self, n: int = 10):
        self.round += 1
        tried = [a["attack_id"] for a in self.attacks]
        if self.live:
            hist = self.snap["transactions"][-80:]
            out = llm.ask_json(llm.prompt("redteam", n=n), {
                "rules": self.approved(), "vendors": self.snap["vendors"], "history": hist,
                "techniques": [{"technique": t["technique"], "example": t["why_it_might_pass"]} for t in self.techniques],
                "already_tried": [{"technique": a["technique"], "bill": a["bill"]} for a in self.attacks]})
            batch = out.get("attacks", [])[:n]
            for i, a in enumerate(batch):  # make ids unique per round
                a["attack_id"] = f"R{self.round}-{a.get('attack_id', i)}"
                a["bill"]["bill_id"] = f"B-RT-{self.round}-{i + 1:02d}"
        else:
            batch = [json.loads(json.dumps(a)) for a in self.techniques if a["attack_id"] not in tried][:n]

        for a in batch:
            a["bill"].setdefault("currency", "GBP")
        results = self._map(lambda a: self.review(a["bill"], self.snap["pending_bills"] + [a["bill"]]), batch)
        for a, res in zip(batch, results):
            a.update(result=res, caught=res["decision"] != "approve", round=self.round, history=[])
            self.attacks.append(a)
        caught = sum(a["caught"] for a in batch)
        self.log("Red Team", f"round {self.round} attack", f"{caught}/{len(batch)} caught")
        return batch

    def scoreboard(self) -> dict:
        total = len(self.attacks)
        caught = sum(a["caught"] for a in self.attacks)
        return {"total": total, "caught": caught, "missed": total - caught,
                "rate": (caught / total) if total else None}

    # ------------------------------------------------------------ 4. patch + replay
    def propose_patch(self, attack_id: str) -> dict:
        a = next(x for x in self.attacks if x["attack_id"] == attack_id)
        if self.live:
            p = llm.ask_json(llm.prompt("patcher"), {
                "rules": self.approved(), "history": self.snap["transactions"],
                "missed_attack": {k: a[k] for k in ("technique", "why_it_might_pass", "bill")}})
        else:
            f = ROOT / "mock" / ("seapoint" if self.source == "seapoint" else "") / f"patch_{a['technique']}.json"
            if not f.exists():
                raise RuntimeError(f"No offline patch for '{a['technique']}' - use live mode.")
            p = json.loads(f.read_text())
        rule = self._add_rule(p["rule"], "patch")
        rule["patch"] = {"for_attack": attack_id, "rationale": p.get("rationale", ""),
                         "replaces": p.get("replaces_rule_id"),
                         "claimed_false_positives": p.get("false_positives_in_history")}
        self.patches.append(rule)
        self.log("Miner", "proposed patch", f"{rule['id']} for {attack_id}: {rule['name']}")
        return rule

    def replay(self, attack_ids: list[str] | None = None):
        out = []
        for a in self.attacks:
            if attack_ids and a["attack_id"] not in attack_ids:
                continue
            a["history"].append({"policy_v": a["result"]["policy_v"], "decision": a["result"]["decision"]})
            a["result"] = self.review(a["bill"], self.snap["pending_bills"] + [a["bill"]])
            a["caught"] = a["result"]["decision"] != "approve"
            out.append(a)
        self.log("Red Team", "replayed attacks",
                 ", ".join(f"{a['attack_id']} {'caught' if a['caught'] else 'missed'}" for a in out))
        return out
