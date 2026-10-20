"""Data source: Seapoint sandbox via the Claude API MCP connector, or the offline sample.

Safety: the Collector only ever gets an ALLOWLIST of read tools. Every other
tool on the server is disabled, so no agent in this app can pay, approve,
freeze or edit anything - even if a prompt tells it to.

On the night:
  1. Set SEAPOINT_MCP_URL and SEAPOINT_TOKEN (from the organisers).
  2. Run `python -m house_rules.seapoint --discover` to print the tool names.
  3. Put the READ tools in SEAPOINT_READ_TOOLS (comma-separated).
  4. Run `python -m house_rules.seapoint --collect` to cache data/seapoint_snapshot.json.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import llm

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE = DATA / "sample_snapshot.json"
CACHE = DATA / "seapoint_snapshot.json"
SERVER = "seapoint"


def _server() -> dict:
    url = os.getenv("SEAPOINT_MCP_URL")
    if not url:
        raise RuntimeError("SEAPOINT_MCP_URL is not set")
    s = {"type": "url", "url": url, "name": SERVER}
    if os.getenv("SEAPOINT_TOKEN"):
        s["authorization_token"] = os.environ["SEAPOINT_TOKEN"]
    return s


def read_tools() -> list[str]:
    return [t.strip() for t in os.getenv("SEAPOINT_READ_TOOLS", "").split(",") if t.strip()]


def discover() -> list[dict]:
    """List the server's tools without letting the model call any of them."""
    resp = llm.client().beta.messages.create(
        model=llm.MODEL, max_tokens=200,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        mcp_servers=[_server()],
        tools=[{"type": "mcp_toolset", "mcp_server_name": SERVER, "default_config": {"enabled": False}}],
        betas=["mcp-client-2026-09-15"],
    )
    tools = []
    for b in resp.content:
        if getattr(b, "type", "") == "mcp_tool_listing":
            tools += [{"name": t.name if hasattr(t, "name") else t["name"],
                       "description": (t.description if hasattr(t, "description") else t.get("description", ""))}
                      for t in b.tools]
    return tools


def collect() -> dict:
    allow = read_tools()
    if not allow:
        raise RuntimeError("Refusing to collect: SEAPOINT_READ_TOOLS is empty. Allowlist read-only tools first.")
    toolset = {
        "type": "mcp_toolset", "mcp_server_name": SERVER,
        "default_config": {"enabled": False},
        "configs": {name: {"enabled": True} for name in allow},
    }
    snap = llm.ask_json(llm.prompt("collector"), {"task": "Collect the snapshot now."}, max_tokens=32000,
                        mcp_servers=[_server()], tools=[toolset], betas=["mcp-client-2025-11-20"])
    CACHE.write_text(json.dumps(snap, indent=2))
    return snap


def load(source: str = "sample") -> dict:
    path = CACHE if source == "seapoint" else SAMPLE
    if not path.exists():
        if source == "seapoint":
            raise FileNotFoundError("No Seapoint snapshot yet - run: python -m house_rules.seapoint --collect")
        raise FileNotFoundError("Run: python data/make_sample.py")
    snap = json.loads(path.read_text())
    snap.setdefault("vendors", []), snap.setdefault("transactions", []), snap.setdefault("pending_bills", [])
    return snap


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--collect", action="store_true")
    a = ap.parse_args()
    if a.discover:
        for t in discover():
            print(f"{t['name']:40s} {t['description'][:90]}")
        print("\nPut READ-ONLY tool names in SEAPOINT_READ_TOOLS (comma-separated).")
    elif a.collect:
        s = collect()
        print(f"cached {CACHE}: {len(s['vendors'])} vendors, {len(s['transactions'])} txns, "
              f"{len(s['pending_bills'])} pending bills")
    else:
        ap.print_help()
