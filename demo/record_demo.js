// Records the House Rules demo against the running app (http://localhost:8501).
// Run: NODE_PATH=$(npm root -g) node demo/record_demo.js
const { chromium } = require("playwright");
const path = require("path");

const URL = "http://localhost:8501";
const OUT = path.join(__dirname, "raw");
const W = 1440, H = 900;
const sleep = ms => new Promise(r => setTimeout(r, ms));

const DUR = JSON.parse(require("fs").readFileSync(path.join(__dirname, "vo", "durations.json"), "utf8"));
const timeline = [];
let t0 = 0, lastEnd = 0;
async function cue(key) {  // wait for the previous line to finish, then log this line's start
  const wait = lastEnd - Date.now();
  if (wait > 0) await sleep(wait);
  timeline.push({ key, t: (Date.now() - t0) / 1000 });
  lastEnd = Date.now() + DUR[key] + 400;
}

async function caption(page, key, title, body = "") {
  await cue(key);
  await page.evaluate(([t, b]) => {
    let el = document.getElementById("demo-cap");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-cap";
      el.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:2147483647;" +
        "max-width:1000px;width:calc(100% - 120px);background:rgba(13,22,31,.92);color:#fff;border-radius:10px;" +
        "padding:14px 22px;font:16px/1.45 -apple-system,'Segoe UI',sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.25)";
      document.body.appendChild(el);
    }
    el.innerHTML = `<div style="font-weight:700;font-size:19px;margin-bottom:2px">${t}</div>${b ? `<div style="opacity:.85">${b}</div>` : ""}`;
    el.style.display = "block";
  }, [title, body]);
}

async function card(page, key, title, sub, ms) {
  await cue(key);
  ms = Math.max(ms, DUR[key] + 500);
  await page.evaluate(([t, s]) => {
    const el = document.createElement("div");
    el.id = "demo-card";
    el.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:#0E151C;color:#E4EAF0;display:grid;place-content:center;" +
      "text-align:center;gap:14px;font-family:-apple-system,'Segoe UI',sans-serif";
    el.innerHTML = `<div style="font:800 64px/1.05 -apple-system,sans-serif;letter-spacing:-.01em">${t}</div>` +
      `<div style="font-size:22px;opacity:.8;max-width:900px">${s}</div>`;
    document.body.appendChild(el);
  }, [title, sub]);
  await sleep(ms);
  await page.evaluate(() => document.getElementById("demo-card")?.remove());
}

async function scrollTo(page, locator) {
  await locator.scrollIntoViewIfNeeded();
  await page.mouse.wheel(0, -120);
  await sleep(400);
}

const tab = (page, name) => page.getByRole("tab", { name: new RegExp(name) }).click();
const button = (page, name) => page.getByRole("button", { name: new RegExp(name) }).first();

(async () => {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: OUT, size: { width: W, height: H } } });
  const page = await ctx.newPage();
  t0 = Date.now();
  await page.goto(URL);
  await page.getByText("Mine my unwritten rules").waitFor();
  await page.getByText("Offline (code agents)").click();
  await sleep(2500);

  // 0. Title
  await card(page, "title", "House Rules", "Your unwritten spend policy, made explicit, enforced, attacked and fixed.<br>Running on the Seapoint sandbox · read-only · no agent can move money", 5000);

  // 1. Hook
  await caption(page, "hook", "Every startup has a spend policy. It's never written down.",
    "Northstar Labs: £2.46M cash, 187 real payments since April, 26 bills waiting to be paid. All read from Seapoint, read-only.");
  await sleep(7000);

  // 2. Mine
  await caption(page, "mine", "1 · The Miner writes down the rules the founder already follows",
    "Every supplier's usual amount and payment day, each with its evidence and a backtest against history.");
  await button(page, "Mine my unwritten rules").click();
  await sleep(4500);
  await page.mouse.wheel(0, 500); await sleep(2500);
  await page.mouse.wheel(0, -500); await sleep(1000);
  await caption(page, "approve", "The founder signs off the rules", "39 rules, zero conflicts with history. Every approval bumps the policy version: now v39.");
  await button(page, "Approve all proposed").click();
  await sleep(5000);

  // 3. Guard
  await tab(page, "Payment queue");
  await sleep(800);
  await caption(page, "guard", "2 · The Guardian reviews the real payment queue",
    "Every bill gets approve, hold or escalate, with a one-line reason. Hard checks run in plain code.");
  await button(page, "Review pending bills").click();
  await sleep(4500);
  const snow = page.locator(".card", { hasText: "Snowflake Computing UK Ltd" }).first();
  await scrollTo(page, snow);
  await caption(page, "snow", "Caught: Snowflake would have been paid three times for October",
    "October's £21,800 was already collected by direct debit on 11 Oct, and the same invoice is queued twice. £43,600 stopped.");
  await sleep(8000);
  const meridian = page.locator(".card", { hasText: "Meridian Insurance" }).first();
  await scrollTo(page, meridian);
  await caption(page, "paid", "Also caught: bills that were already paid",
    "Sentry, Slack, Anthropic and Connolly were already collected this month. Meridian's invoice was paid on 23 Sep.");
  await sleep(6500);

  // 4. Human edits a limit
  const wework = page.locator(".card", { hasText: "£2,950.00" }).first();
  await scrollTo(page, wework);
  await caption(page, "control", "3 · The founder stays in control",
    "WeWork's new £2,950 rent is on hold: it's above the usual £2,585. The founder agrees to the rise.");
  await sleep(6000);
  await tab(page, "Rules");
  await sleep(800);
  const editor = page.getByText("Edit limits").nth(1);
  await scrollTo(page, editor);
  await editor.click();
  await sleep(1200);
  const max = page.getByLabel("Max £").nth(1);
  await max.click({ clickCount: 3 });
  await max.type("3000", { delay: 120 });
  await max.press("Tab");
  await caption(page, "raise", "Raise WeWork's maximum to £3,000", "The edit is backtested, bumps the policy to v40 and goes in the audit log.");
  await sleep(2500);
  await page.getByRole("button", { name: "Save limits" }).first().click();
  await sleep(4000);
  await tab(page, "Payment queue");
  await sleep(1000);
  await scrollTo(page, page.locator(".card", { hasText: "£2,950.00" }).first());
  await caption(page, "approved_rent", "WeWork's rent is now approved",
    "But the second October rent payment of £2,350 is still escalated. A person can loosen a rule, never the hard checks.");
  await sleep(7000);
  await page.evaluate(() => window.scrollTo(0, 0));

  // 5. Attack
  await tab(page, "Red team");
  await sleep(800);
  await caption(page, "attack", "4 · The Red Team attacks the policy",
    "Duplicates, a lookalike 'Snowfiake', new bank details, a split invoice, a fake 'pre-approved by CFO' note. In memory only.");
  await button(page, "Launch attack round").click();
  await sleep(4500);
  await caption(page, "missed", "9 of 10 caught. One got through.",
    "A second Fathom invoice this month: in range, on time, under the £10k two-approver limit.");
  await sleep(7000);

  // 6. Patch
  await caption(page, "patch", "5 · The agent proposes a fix", "One invoice per payroll and staffing supplier per month, with a backtest.");
  await button(page, "Propose a policy patch").click();
  await sleep(3500);
  await scrollTo(page, page.getByText("Backtest:").first());
  await caption(page, "backtest", "The backtest found something nobody planted",
    "September salaries for three employees were paid twice, on the 18th and the 25th. £11,800 overpaid.");
  await sleep(8000);
  await button(page, "Approve patch").click();
  await sleep(4000);
  await page.evaluate(() => window.scrollTo(0, 0));
  await caption(page, "replayed", "Patch approved, attack replayed: 10/10 caught", "Policy v41. Legitimate bills still pass.");
  await sleep(6500);

  // 7. Audit + close
  await tab(page, "Audit log");
  await caption(page, "audit", "Every agent and human action, with the policy version in force", "");
  await sleep(6000);
  await card(page, "close", "Autonomy you can audit",
    "Agents write the policy, attack it and fix it. Code has the last word on strictness.<br>A human signs every change. The same agents also run live on Claude.", 6500);

  require("fs").writeFileSync(path.join(__dirname, "vo", "timeline.json"), JSON.stringify(timeline, null, 1));
  await ctx.close();
  await browser.close();
  console.log("recorded to", OUT);
})().catch(e => { console.error(e); process.exit(1); });
