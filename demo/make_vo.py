"""Generate one ElevenLabs voiceover clip per demo caption and record each clip's duration."""
import json
import os
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
for line in (HERE.parent / ".env").read_text().splitlines():
    k, _, v = line.partition("=")
    if v.strip():
        os.environ.setdefault(k.strip(), v.strip())
KEY = os.environ["ELEVENLABS_API_KEY"]
VOICE = os.getenv("ELEVENLABS_VOICE", "JBFqnCBsd6RMkjVDRZzb")

LINES = {
    "arch": "Here's how it works. Seapoint data comes in read-only. The Miner proposes rules and the founder approves them. The Guardian checks every bill, and hard checks in code can only make it stricter. The Red Team attacks, the Patcher proposes fixes, and every step lands in the audit log.",
    "title": "This is House Rules. Agents that turn a founder's unwritten spend policy into rules, enforce them, attack them, and fix them.",
    "hook": "Every startup has a spend policy, but it's never written down. Here's Northstar Labs on the Seapoint sandbox: two point four six million pounds in cash, a hundred and eighty-seven real payments, and twenty-six bills waiting. All read-only.",
    "mine": "First, the Miner reads the payment history and writes down every supplier's usual amount and payment day, each with its evidence and a backtest.",
    "approve": "The founder signs off the rules. Thirty-nine rules, no conflicts with history. Every approval bumps the policy version.",
    "guard": "Next, the Guardian reviews the real payment queue. Every bill gets approve, hold, or escalate, with a one-line reason.",
    "snow": "Here's the big catch. Snowflake's October bill was already collected by direct debit, and the same invoice is queued twice. That's forty-three thousand six hundred pounds stopped.",
    "paid": "It also caught bills that were already paid this month: Sentry, Slack, Anthropic, Connolly, and an insurance invoice paid in September.",
    "control": "The founder stays in control. WeWork's new rent is on hold because it's above the usual range.",
    "raise": "The founder agrees to the rise and lifts the maximum to three thousand pounds. The change is backtested, versioned, and logged.",
    "approved_rent": "Now the rent is approved. But the duplicate October rent payment is still blocked. A person can loosen a rule, never the hard checks.",
    "attack": "Now the Red Team attacks the policy: duplicates, a lookalike supplier, new bank details, a split invoice, and a fake pre-approved note.",
    "missed": "Nine out of ten are caught. One gets through: a second Fathom invoice this month, in range and on time.",
    "patch": "So the agent proposes a fix: one invoice per payroll supplier per month.",
    "backtest": "And its backtest found something nobody planted. September salaries were paid twice. Eleven thousand eight hundred pounds overpaid.",
    "replayed": "The founder approves the patch, the attack is replayed, and it's caught. Ten out of ten.",
    "audit": "Every agent and human action is in the audit log, with the policy version in force.",
    "close": "Autonomy you can audit. Agents write the policy, attack it, and fix it. Code has the last word, and a human signs every change.",
}

out = HERE / "vo"
out.mkdir(exist_ok=True)
durations = {}
for key, text in LINES.items():
    mp3 = out / f"{key}.mp3"
    if not mp3.exists():
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128",
            data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                             "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode(),
            headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"})
        mp3.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                         capture_output=True, text=True).stdout.strip()
    durations[key] = round(float(dur) * 1000)
    print(f"{key:14s} {durations[key] / 1000:5.1f}s")
(out / "durations.json").write_text(json.dumps(durations, indent=1))
print("total", round(sum(durations.values()) / 1000, 1), "s")
