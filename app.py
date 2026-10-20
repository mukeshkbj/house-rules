"""House Rules - Streamlit UI.  Run: streamlit run app.py"""
import streamlit as st

from house_rules import llm, seapoint
from house_rules.engine import Engine

st.set_page_config(page_title="House Rules", page_icon="🛡️", layout="wide")

CHIP = {"approve": ("#1f7a4d", "#e3f4ea", "Approve"),
        "hold": ("#8a5a00", "#fdf1d8", "Hold"),
        "escalate": ("#a12a2a", "#fbe4e4", "Escalate")}
STATUS = {"proposed": "🟡 proposed", "approved": "🟢 approved", "rejected": "⚪ rejected"}

st.markdown("""
<style>
.chip{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:.8rem}
.muted{color:#6b7280;font-size:.85rem}
.card{border:1px solid rgba(128,128,128,.25);border-radius:10px;padding:12px 14px;margin-bottom:10px}
.miss{border-color:#d33;box-shadow:0 0 0 2px rgba(221,51,51,.15)}
</style>""", unsafe_allow_html=True)


def chip(decision: str) -> str:
    fg, bg, label = CHIP[decision]
    return f'<span class="chip" style="color:{fg};background:{bg}">{label}</span>'


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("🛡️ House Rules")
    st.caption("Your unwritten spend policy, made explicit - then attacked.")
    live_ok = llm.live_available()
    mode = st.radio("Agents", ["Offline (code agents)", "Live (Claude)"], index=1 if live_ok else 0,
                    disabled=not live_ok, help="Live needs ANTHROPIC_API_KEY.")
    source = st.radio("Data", ["Sample company", "Seapoint sandbox"], index=1 if seapoint.CACHE.exists() else 0,
                      help="Seapoint uses data/seapoint_snapshot.json (python data/build_seapoint_snapshot.py).")
    if st.button("Reset session", width="stretch") or "eng" not in st.session_state \
            or st.session_state.get("cfg") != (mode, source):
        try:
            snap = seapoint.load("seapoint" if source.startswith("Seapoint") else "sample")
            st.session_state.eng = Engine(snap, live=mode.startswith("Live"))
            st.session_state.cfg = (mode, source)
        except FileNotFoundError as e:
            st.error(str(e))
            st.stop()
    st.divider()
    st.markdown("**Safety design**")
    st.caption("• No agent can move money - release is a human action.\n"
               "• Hard invariants live in code; agents can only make decisions stricter.\n"
               "• Rules change only on founder approval; every change bumps the policy version.\n"
               "• Red-team bills exist only in memory.")

eng: Engine = st.session_state.eng
snap = eng.snap

# ------------------------------------------------------------------ header
sb = eng.scoreboard()
c = st.columns(5)
c[0].metric("Company", snap.get("company", "-"))
c[1].metric("Cash", f"£{snap.get('cash_balance') or 0:,.0f}")
c[2].metric("Approved rules", len(eng.approved()))
c[3].metric("Policy version", f"v{eng.version}")
c[4].metric("Attacks caught", f"{sb['caught']}/{sb['total']}" if sb["total"] else "-")

t1, t2, t3, t4 = st.tabs(["① Rules", "② Payment queue", "③ Red team", "Audit log"])

# ------------------------------------------------------------------ rules
with t1:
    a, b = st.columns([3, 1])
    a.markdown(f"Mining **{len(snap['transactions'])}** past transactions across "
               f"**{len(snap['vendors'])}** vendors for patterns you follow but never wrote down.")
    if b.button("⛏️ Mine my unwritten rules", type="primary", width="stretch"):
        with st.spinner("Reading six months of spend…"):
            eng.mine()
        st.rerun()

    if eng.rules:
        if st.button("Approve all proposed with confidence ≥ 0.8"):
            for r in eng.rules:
                if r["status"] == "proposed" and r.get("confidence", 0) >= 0.8:
                    eng.set_status(r["id"], "approved")
            st.rerun()

    for r in eng.rules:
        bt = r["backtest"]
        fit = f"fits {bt['in_scope'] - bt['breaches']}/{bt['in_scope']} past transactions"
        origin = " · 🩹 patch" if r.get("origin") == "patch" else ""
        evidence = ", ".join(i[:12] + "…" for i in r["evidence"].get("example_txn_ids", [])[:3])
        why = f"<br><span class='muted'>Why: {r['patch']['rationale']}</span>" if r.get("patch") else ""
        st.markdown(
            f"<div class='card'><b>{r['id']} · {r['name']}</b>{origin} &nbsp;<span class='muted'>"
            f"{STATUS[r['status']]} · confidence {r.get('confidence', 0):.2f} · {fit}</span><br>{r['condition']}<br>"
            f"<span class='muted'>Breach: {r.get('breach_condition', '-')} → {r.get('action', 'hold')}. "
            f"Evidence: {evidence}</span>{why}</div>", unsafe_allow_html=True)
        x, y, _ = st.columns([1, 1, 6])
        if x.button("Approve", key=f"ap-{r['id']}", disabled=r["status"] == "approved"):
            eng.set_status(r["id"], "approved")
            st.rerun()
        if y.button("Reject", key=f"rj-{r['id']}", disabled=r["status"] == "rejected"):
            eng.set_status(r["id"], "rejected")
            st.rerun()
        editable = [k for k in ("min", "max", "day_from", "day_to", "per_month") if k in (r.get("params") or {})]
        if editable:
            label = "Edit limits" + (f" · last changed by {r['edited_by']}" if r.get("edited_by") else "")
            with st.expander(label):
                cols = st.columns(len(editable))
                vals = {}
                for col, k in zip(cols, editable):
                    is_day = k.startswith("day") or k == "per_month"
                    vals[k] = col.number_input(
                        {"min": "Min £", "max": "Max £", "day_from": "From day", "day_to": "To day",
                         "per_month": "Per month"}[k],
                        value=int(r["params"][k]) if is_day else float(r["params"][k]),
                        min_value=1 if is_day else 0.0, max_value=31 if k.startswith("day") else None,
                        step=1 if is_day else 50.0, key=f"ed-{r['id']}-{k}")
                if vals.get("min", 0) > vals.get("max", float("inf")) or vals.get("day_from", 0) > vals.get("day_to", 99):
                    st.error("The lower limit is above the upper limit. Fix it to save.")
                elif st.button("Save limits", key=f"sv-{r['id']}"):
                    eng.edit_params(r["id"], vals)
                    if eng.decisions:
                        eng.review_pending()  # decisions must reflect the policy in force
                    st.rerun()

# ------------------------------------------------------------------ queue
with t2:
    a, b = st.columns([3, 1])
    a.markdown(f"**{len(snap['pending_bills'])}** bills awaiting payment. "
               "The Guardian recommends; you release.")
    if b.button("🔍 Review pending bills", type="primary", width="stretch",
                disabled=not eng.approved()):
        with st.spinner("Checking every bill against policy…"):
            eng.review_pending()
        st.rerun()
    if not eng.approved():
        st.info("Approve some rules first - the Guardian only enforces rules you've signed off.")
    if eng.decisions:
        amounts = {b["bill_id"]: b["amount"] for b in snap["pending_bills"]}
        m = st.columns(3)
        for col, label in zip(m, ("approve", "hold", "escalate")):
            ids = [k for k, v in eng.decisions.items() if v["decision"] == label]
            col.metric(label.capitalize(), len(ids), f"£{sum(amounts[i] for i in ids):,.0f}", delta_color="off")

    for bill in snap["pending_bills"]:
        d = eng.decisions.get(bill["bill_id"])
        head = (f"<b>{bill['vendor_name']}</b> · £{bill['amount']:,.2f} · due {bill['due_date']} "
                f"<span class='muted'>({bill['invoice_number']})</span>")
        st.markdown(f"<div class='card'>{head}&nbsp; {chip(d['decision']) if d else ''}"
                    f"{'<br>' + d['reason'] if d else ''}</div>", unsafe_allow_html=True)
        if d:
            with st.expander("Why - checks behind this decision"):
                st.json({"invariants": d["invariants"], "rule_check": d["rule_check"],
                         "llm_decision": d.get("llm_decision"), "policy_v": d["policy_v"]})

    if eng.decisions:
        ready = [k for k, v in eng.decisions.items() if v["decision"] == "approve"]
        if st.button(f"✅ Release {len(ready)} approved payments (sandbox - logged only)", disabled=not ready):
            eng.log("Founder", "released payments", ", ".join(ready))
            st.success("Logged. In production this hands off to the payment rail with a second approver.")

# ------------------------------------------------------------------ red team
with t3:
    a, b = st.columns([3, 1])
    a.markdown("The Red Team writes realistic bad bills to find gaps in your approved policy. "
               "Attacks never leave this screen.")
    if b.button("⚔️ Launch attack round", type="primary", width="stretch",
                disabled=not eng.approved()):
        with st.spinner("Red Team is drafting attacks…"):
            eng.attack()
        st.rerun()

    if sb["total"]:
        m = st.columns(3)
        m[0].metric("Caught", sb["caught"])
        m[1].metric("Missed", sb["missed"])
        m[2].metric("Catch rate", f"{sb['rate']:.0%}")

    for att in sorted(eng.attacks, key=lambda x: x["caught"]):
        bill, res = att["bill"], att["result"]
        cls = "card" if att["caught"] else "card miss"
        trail = " → ".join(f"v{h['policy_v']} {h['decision']}" for h in att["history"])
        hist = f"<br><span class='muted'>History: {trail} → v{res['policy_v']} {res['decision']}</span>" if trail else ""
        st.markdown(
            f"<div class='{cls}'><b>{att['attack_id']} · {att['technique'].replace('_', ' ')}</b> "
            f"&nbsp;{chip(res['decision'])} &nbsp;<b>{'CAUGHT' if att['caught'] else 'MISSED'}</b><br>"
            f"{bill['vendor_name']} · £{bill['amount']:,.2f} · due {bill['due_date']} · \"{bill['description']}\"<br>"
            f"<span class='muted'>Attacker's idea: {att['why_it_might_pass']}</span><br>"
            f"<span class='muted'>Guardian: {res['reason']}</span>{hist}</div>", unsafe_allow_html=True)
        if not att["caught"]:
            pending_patch = next((r for r in eng.rules if r.get("patch", {}).get("for_attack") == att["attack_id"]
                                  and r["status"] == "proposed"), None)
            if not pending_patch:
                if st.button("🩹 Propose a policy patch", key=f"pp-{att['attack_id']}"):
                    with st.spinner("Miner is looking for the gap…"):
                        try:
                            eng.propose_patch(att["attack_id"])
                        except RuntimeError as e:
                            st.error(str(e))
                    st.rerun()
            else:
                bt = pending_patch["backtest"]
                st.info(f"**Proposed {pending_patch['id']} · {pending_patch['name']}** - "
                        f"{pending_patch['condition']}\n\n{pending_patch['patch']['rationale']}\n\n"
                        f"Backtest: flags {bt['breaches']} of {bt['in_scope']} past transactions "
                        f"({pending_patch['patch'].get('claimed_false_positives', '?')} judged false alarms).")
                if st.button("Approve patch & replay attack", key=f"apr-{att['attack_id']}", type="primary"):
                    eng.set_status(pending_patch["id"], "approved")
                    eng.replay([att["attack_id"]])
                    if eng.decisions:
                        eng.review_pending()  # make sure the patch doesn't block legit bills
                    st.rerun()

# ------------------------------------------------------------------ audit
with t4:
    if eng.audit:
        st.dataframe(list(reversed(eng.audit)), width="stretch", hide_index=True)
    else:
        st.caption("Every agent proposal and every human decision lands here, stamped with the policy version.")
