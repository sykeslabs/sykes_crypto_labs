"""PreToolUse guard. Exit 2 = block; stderr is shown to Claude.

Enforces, deterministically, rules CLAUDE.md only states:
  1. never touch secrets (.env*, claude.session) -- .env.example is fine
  2. doc/history.md is append-only
  3. no live order-placement code (Phase 6 is on hold; paper trading only)
"""
import json
import re
import sys
from pathlib import Path

SECRET_PATH = re.compile(r"(^|[\\/])(\.env(\.(?!example$)[^\\/]+)?|claude\.session)$", re.I)
SECRET_IN_CMD = re.compile(r"(^|[\s\"'=/\\])(\.env(?!\.example)\b|claude\.session)", re.I)
ORDER_ENDPOINT = re.compile(
    r"/api/v3/order\b|/fapi/v1/order|/api/v3/brokerage/orders|private/(buy|sell|edit|cancel)\b"
    r"|create_order\(|place_order\(",
    re.I,
)


def block(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}
    path = (ti.get("file_path") or ti.get("path") or "").replace("\\", "/")

    # 1. secrets
    if path and SECRET_PATH.search(path):
        block(f"Blocked: {path} holds secrets. Use .env.example / app/config/settings.py instead.")
    if tool == "Bash" and SECRET_IN_CMD.search(ti.get("command", "")):
        block("Blocked: command references .env / claude.session. Never read or print secrets.")

    # 2. history.md append-only
    if path.endswith("doc/history.md"):
        if tool == "Edit":
            old, new = ti.get("old_string", ""), ti.get("new_string", "")
            if old and old not in new:
                block("Blocked: doc/history.md is append-only. Keep the anchor text and append after it; "
                      "put corrections in a new dated entry.")
        elif tool == "Write":
            p = Path(data.get("cwd", ".")) / "doc/history.md"
            if p.exists() and not ti.get("content", "").startswith(p.read_text(encoding="utf-8")):
                block("Blocked: rewriting doc/history.md. Append only.")

    # 3. paper-trading only
    if tool in ("Edit", "Write", "MultiEdit") and "/app/" in "/" + path:
        text = ti.get("new_string", "") + ti.get("content", "")
        text += "".join(e.get("new_string", "") for e in ti.get("edits", []) or [])
        if ORDER_ENDPOINT.search(text):
            block("Blocked: looks like live order placement. Phase 6 is on hold; system is PAPER ONLY. "
                  "Ask the user before going further.")

    sys.exit(0)


if __name__ == "__main__":
    main()
