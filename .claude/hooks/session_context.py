"""SessionStart: print a short live snapshot (stdout becomes context)."""
import subprocess
from pathlib import Path


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


root = Path.cwd()
migs = sorted((root / "migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
prompts = sorted(p.name for p in (root / "doc/prompts").glob("[0-9][0-9]_*.md"))
dirty = [l for l in git("status", "--porcelain").splitlines() if l.strip()]

print("## Session snapshot")
print(f"- Branch: {git('branch', '--show-current') or '?'} | last commit: {git('log', '-1', '--format=%h %s')}")
print(f"- Uncommitted files: {len(dirty)}" + (" (commit before building on them)" if dirty else ""))
print(f"- Latest migration: {migs[-1].name if migs else 'none'} (next = {int(migs[-1].name[:4]) + 1:04d})" if migs else "- No migrations")
print(f"- Open implementation prompts: {len(prompts)} in doc/prompts/ (see 00_INDEX.md)")
print("- Mode: PAPER TRADING ONLY. Phase 6 on hold.")
