#!/usr/bin/env python3
"""MeoLoom statusline — per-turn and per-session token usage for Claude Code.

Claude Code invokes this after every assistant turn, passing session JSON on
stdin (session_id, transcript_path, model, cost, ...). We incrementally parse
the transcript (byte-offset cache per session, so long sessions stay fast) and
print one line:

    turn 1.2k in / 380 out | session 146.3k tok | ~$0.42 | ctx ~38%

Notes:
- Cost comes from Claude Code's own cost.total_cost_usd when present and is
  always shown with '~' — on subscription plans it is an estimate.
- ctx %% is derived from the last turn's input+cache tokens against the
  context limit (default 200k; override with MEOLOOM_CTX_LIMIT; the legacy
  DATKIT_CTX_LIMIT name remains a fallback).
- Works only in Claude Code (statusline is a Claude Code feature).

Setup (once per machine):
    python3 scripts/statusline.py --install
"""
import json, os, pathlib, sys, tempfile

USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
CTX_LIMIT = int(
    os.environ.get("MEOLOOM_CTX_LIMIT", os.environ.get("DATKIT_CTX_LIMIT", "200000"))
)


def fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)


def find_usages(node, out):
    """Collect every dict literally named 'usage' with known token keys."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "usage" and isinstance(v, dict) and any(isinstance(v.get(kk), int) for kk in USAGE_KEYS):
                out.append(v)
            else:
                find_usages(v, out)
    elif isinstance(node, list):
        for x in node:
            find_usages(x, out)


def cache_path(session_id):
    d = pathlib.Path(tempfile.gettempdir()) / "meoloom-statusline"
    d.mkdir(exist_ok=True)
    return d / f"{session_id}.json"


def load_state(session_id):
    try:
        return json.loads(cache_path(session_id).read_text())
    except Exception:
        return {"offset": 0, "totals": dict.fromkeys(USAGE_KEYS, 0), "last": None}


def save_state(session_id, state):
    try:
        cache_path(session_id).write_text(json.dumps(state))
    except Exception:
        pass  # statusline must never crash the UI


def update_from_transcript(path, state):
    p = pathlib.Path(path)
    if not p.is_file():
        return state
    size = p.stat().st_size
    if size < state["offset"]:  # transcript rotated/truncated — start over
        state = {"offset": 0, "totals": dict.fromkeys(USAGE_KEYS, 0), "last": None}
    with p.open("rb") as f:
        f.seek(state["offset"])
        chunk = f.read()
    # only consume complete lines; keep offset at the last newline
    nl = chunk.rfind(b"\n")
    if nl == -1:
        return state
    state["offset"] += nl + 1
    for line in chunk[: nl + 1].splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        usages = []
        find_usages(obj, usages)
        for u in usages:
            for k in USAGE_KEYS:
                if isinstance(u.get(k), int):
                    state["totals"][k] += u[k]
            state["last"] = {k: u.get(k, 0) if isinstance(u.get(k), int) else 0 for k in USAGE_KEYS}
    return state


def render(state, cost_usd):
    parts = []
    last = state.get("last")
    if last:
        parts.append(f"turn {fmt(last['input_tokens'])} in / {fmt(last['output_tokens'])} out")
    total = sum(state["totals"].values())
    parts.append(f"session {fmt(total)} tok")
    if isinstance(cost_usd, (int, float)) and cost_usd > 0:
        parts.append(f"~${cost_usd:.2f}")
    if last:
        ctx = last["input_tokens"] + last["cache_read_input_tokens"] + last["cache_creation_input_tokens"]
        if ctx:
            parts.append(f"ctx ~{min(100, round(100 * ctx / CTX_LIMIT))}%")
    return " | ".join(parts)


def install():
    settings = pathlib.Path.home() / ".claude" / "settings.json"
    script = str(pathlib.Path(__file__).resolve())
    py = "python" if os.name == "nt" else "python3"
    data = {}
    if settings.is_file():
        try:
            data = json.loads(settings.read_text())
        except Exception:
            print(f"✗ {settings} exists but is not valid JSON — fix it first, nothing changed.")
            return 1
    if "statusLine" in data:
        print(f"✗ statusLine already configured in {settings} — remove it first if you want MeoLoom's; nothing changed.")
        return 1
    data["statusLine"] = {"type": "command", "command": f'{py} "{script}"'}
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n")
    print(f"✓ statusLine installed in {settings}\n  Restart Claude Code to see it.")
    return 0


def main():
    if "--install" in sys.argv:
        sys.exit(install())
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    session_id = payload.get("session_id") or "unknown"
    transcript = payload.get("transcript_path") or ""
    cost = (payload.get("cost") or {}).get("total_cost_usd")
    state = load_state(session_id)
    if transcript:
        state = update_from_transcript(transcript, state)
        save_state(session_id, state)
    print(render(state, cost))


if __name__ == "__main__":
    main()
