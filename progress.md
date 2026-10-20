# Progress — House Rules on the real Seapoint sandbox

Hackathon 2026-10-20, code freeze 20:20. Plan: House Rules (mine → guard → red team → patch), with the Guardian run on the sandbox's real payment queue.

## Done
- Kit unzipped from `~/Downloads/house-rules.zip`.
- Real data pulled through the `seapoint-staging` MCP for org "Hackathon - PolicyAgent" (Northstar Labs):
  - `data/raw/txns_p1.json`, `txns_p2.json`: 187 bank payments, direct debits and transfers, Apr–Oct 2026. Card spend is left out.
  - `data/raw/queue.json`: 25 unpaid invoices, 2 payments not yet sent, payroll payouts, cash total £2,459,109.84, gross burn £141,388.62 (3-month average).
- `data/build_seapoint_snapshot.py` → `data/seapoint_snapshot.json` (35 vendors, 187 txns, 26 pending). Invoice suppliers are matched to transaction participants by normalised name.
- `checks.hard_invariants` run on the real queue. Real catches:
  - Snowflake: Oct £21,800 already collected by DD on 10-11, and 2 copies of invoice SNF-INV-2026-10 in the queue (would pay 3×).
  - Sentry, Slack, Anthropic, Connolly: already collected or paid this month.
  - Meridian Insurance MIB-2026-330: already paid on 09-23 (same invoice number).
  - WeWork: second Oct rent payment of £2,350 queued (Oct paid 10-01). History shows £2,200 paid twice on 09-14.
  - Clearview CM-2026-114: same invoice twice (UPLOAD + EMAIL_SCAN). The payment goes to a one-off payee, ..9047.
  - Northwind: NW-88431 and NW-88690, same amount 7 days apart.
  - New vendors: Halberd Security, Meridian Translations (GB country, NL VAT number), Lodgewood Travel, PyCon (employee expense).
  - Over £10k, needs dual approval: Remote People £33,600, Fathom £14,400, Snowflake.
- Not in the queue yet: Priya Chandra and Isla Fraser are both paid as employee `emp_001`.

## Done (by 19:09)
- Keyless multi-agent loop on real data: `offline_miner.py` (39 rules, 0 backtest conflicts), new invariant INV-6 (payee account not on file),
  `data/seapoint/attacks.json` (10 real-vendor attacks, A-10 staged miss), `mock/seapoint/patch_double_billing.json`.
- Engine picks miner, attacks and patches by `snapshot.source`. App defaults to the sandbox, and HTML render bugs are fixed.
- Verified in the browser: mine → approve → review (2/3/21) → attack 9/10 → patch → replay 10/10, v40.
- Tests: 5 pass (`.venv/bin/python tests/test_checks.py`), including 2 sandbox story tests.
- Patch backtest finds September payroll paid twice (£11,800): Isla, Priya and Rhys each paid on the 18th and the 25th.
- README demo script rewritten for real data. Launch with `.claude/launch.json` in /Users/mukeshagrawal/seapoint (streamlit on :8501).

## Remaining
- Add ANTHROPIC_API_KEY, then try Live mode. The live Collector also needs SEAPOINT_MCP_URL=https://mcp.seapoint.dev/mcp plus a token.
- Optional: Guardian check for shared employee IDs (emp_001 = Priya Chandra and Isla Fraser).
- Rehearse twice and screen-record an offline backup run.

## Live mode + report
- `.env` holds ANTHROPIC_API_KEY. `llm.py` loads `.env` on import. The API call works (claude-sonnet-5-5).
- Live Miner failed because thinking used about 8.8k of the 8k output limit, which truncated the JSON. Default raised to 16k and Guardian to 8k. One debug call at 16k parsed OK. The full live run in the app has not been re-run yet; the Miner takes about 2 min.
- Interactive report: `report/build_report.py` + `report/template.html` → `report/house-rules-report.html`,
  published privately at https://claude.ai/artifact/Do2RPZK9FocoNotZwfLWcs. Tabs: Architecture (mermaid), Miner, Guardian, Red Team, Patcher, Audit.
  Rebuild with `.venv/bin/python report/build_report.py`, then republish.

## Live Claude run (19:31)
- Fixes: answers come back through a `submit` tool, and the code unwraps {"json": {...}}. Guardian calls run in parallel (8 workers). A failed Guardian call escalates the bill. If Claude gives no reason, the code reason is used.
- Full live loop takes about 2–2.5 min. The last run: 9 rules, 26/26 escalated with reasons, red team wrote 10 new attacks, 10/10 caught, no patch needed.
- An earlier live run approved Nordhaus and found the HubSpot duplicate (already paid by direct debit on 9 Oct), which the code checks missed.
- Live report: https://claude.ai/artifact/2bYNpawbUBoZAptgdrfQG3 (data/live_run.json). Offline report: https://claude.ai/artifact/Do2RPZK9FocoNotZwfLWcs
- The app restarted and defaults to Live + Seapoint sandbox. For a fast demo, pick Offline in the sidebar.

## Founder edits limits (19:4x)
- `Engine.edit_params` lets a person change min/max/day_from/day_to/per_month. It re-runs the backtest, bumps the policy version, logs old → new, and re-reviews the queue if there are decisions.
- UI: an "Edit limits" expander on every rule card, with validation (lower limit can't exceed upper). Verified in the browser: WeWork max 2,585 → 3,000 saved, policy v1, "last changed by Founder".
- Test `test_founder_edit_tightens_policy_and_is_logged` passes (6/6). Invariants still apply on top of any edit.

## Demo video (20:00)
- `demo/house-rules-demo.mp4`: 2:36, 1440×900, ElevenLabs voiceover (voice JBFqnCBsd6RMkjVDRZzb, eleven_multilingual_v2).
- Rebuild: `python3 demo/make_vo.py` (clips + durations), then `NODE_PATH=~/.nvm/versions/node/v22.18.0/lib/node_modules ~/.nvm/versions/node/v22.18.0/bin/node demo/record_demo.js` (needs the app running on :8501), then the ffmpeg mix in this session (adelay per `demo/vo/timeline.json`).
- ELEVENLABS_API_KEY is in `.env`. The key was pasted in chat, so rotate it after the event.

## New invoices (20:40)
- Saved policy: `Engine.save_policy/load_policy` → `data/policy_<source>.json` (rules, version, audit). The backtest re-runs on load. App sidebar has 💾 Save policy and 📂 Load saved.
- `python -m house_rules.review_new [--live]` reviews only unseen bill ids against the saved policy, writes data/reviews/, updates data/seen_bills.json and logs to the policy audit.
- Verified: saved v40 from the UI (WeWork max 3000). The CLI reviewed 26, then 0 on the second run. 7/7 tests pass, including a new-bill test (legit Nordhaus November approved, lookalike "Nordhaus Studios Ltd" escalated).
- Seapoint had no invoices newer than 14 Oct at 20:40. Refreshing data/raw is still manual (needs a token or a Claude session).

## Seapoint features (21:1x)
- Raw pulls from Seapoint: `data/raw/invoices.json` (all 39 invoices, with VAT and company numbers and matched transaction ids) and `data/raw/seapoint_extra.json` (69 participants, payment queue, card payments for open-invoice suppliers, 8 pay runs, cash and burn). `queue.json` removed.
- Builder uses Seapoint participant ids. Identity comes from paid invoices via transaction id (Snowflake, Clearview, Deel company numbers). Name matching prefers the longest prefix (fixes AWS → "Amazon UK").
- New checks: INV-7 (already paid invoice number), INV-8 (company or VAT number differs), INV-9 (VAT country ≠ supplier country, catches Meridian Translations), paid-on-receipt duplicate (catches HubSpot), card-payment duplicate (catches Lodgewood). Payroll: PAY-1 draft October run would pay October twice (£11,800), PAY-2 October run paid early on 18 Sep, PAY-3 pay account change.
- Halberd, Meridian Translations and Lodgewood are known Seapoint suppliers, so they are no longer flagged as new. Only PyCon is still flagged.
- Correction: the "September salaries paid twice" story is two salary runs in September because the October run was paid early (Seapoint payroll). Patch rationale, report and README are updated. The YouTube voiceover still says "paid twice".
- `prompts/seapoint_pull.md` is the self-contained pull and review prompt for a scheduled Claude run. The schedule is not created yet; it needs the user's OK.
- Verified: 7/7 tests, review_new shows PAY-1 and PAY-2, the app screenshot shows the Payroll checks section.
