"""Thin Claude wrapper: system prompt from /prompts, JSON in, JSON out."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
ENV = PROMPTS.parent / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        k, sep, v = line.partition("=")
        if sep and v.strip() and not k.startswith("#"):
            os.environ.setdefault(k.strip(), v.strip())
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def live_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def prompt(name: str, **fmt) -> str:
    text = (PROMPTS / f"{name}.md").read_text()
    for k, v in fmt.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


def ask_json(system_prompt: str, payload: dict, max_tokens: int = 16000, **kwargs) -> dict:
    """One call, one retry if the JSON doesn't parse. kwargs pass through (e.g. MCP)."""
    messages = [{"role": "user", "content": json.dumps(payload, default=str)}]
    if "tools" not in kwargs:  # answer through a tool call so it arrives as parsed JSON
        resp = client().messages.create(
            model=MODEL, max_tokens=max_tokens, messages=messages,
            system=system_prompt + "\n\nDeliver your answer by calling the `submit` tool with the JSON object.",
            tools=[{"name": "submit", "description": "Submit the JSON object the instructions ask for.",
                    "input_schema": {"type": "object", "additionalProperties": True}}])
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is not None and resp.stop_reason != "max_tokens":
            out = block.input
            while len(out) == 1:  # the model sometimes wraps the object: {"json": {...}} or {"json": "{...}"}
                inner = next(iter(out.values()))
                if isinstance(inner, str):
                    try:
                        inner = parse_json(inner)
                    except (ValueError, json.JSONDecodeError):
                        break
                if not isinstance(inner, dict):
                    break
                out = inner
            return out
    create = client().beta.messages.create if kwargs.get("betas") else client().messages.create
    last_err = None
    for _ in range(2):
        resp = create(model=MODEL, max_tokens=max_tokens, system=system_prompt, messages=messages, **kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            return parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            messages = messages + [
                {"role": "assistant", "content": text or "(no text)"},
                {"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object."},
            ]
    raise RuntimeError(f"model did not return valid JSON: {last_err}")
