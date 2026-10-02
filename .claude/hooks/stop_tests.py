"""Stop: if Claude edited any .py this session, run pytest; on failure, keep Claude working.

Reads the transcript instead of keeping state files in the repo.
"""
import json
import subprocess
import sys
from pathlib import Path

data = json.load(sys.stdin)
if data.get("stop_hook_active"):  # already continued once because of us -> don't loop
    sys.exit(0)

edited_py = False
try:
    with open(data["transcript_path"], encoding="utf-8") as f:
        for line in f:
            if '"tool_use"' in line and ".py" in line and any(t in line for t in ('"Edit"', '"Write"', '"MultiEdit"')):
                edited_py = True
                break
except Exception:
    sys.exit(0)

if not edited_py:
    sys.exit(0)

venv = next((p for p in (Path(".venv/Scripts/python.exe"), Path(".venv/bin/python")) if p.exists()), None)
py = str(venv) if venv else sys.executable
r = subprocess.run([py, "-m", "pytest", "-q", "-x", "--no-header"],
                   capture_output=True, text=True, timeout=280)
if r.returncode != 0:
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-30:])
    print(f"pytest is failing after your Python edits. Fix before finishing:\n{tail}", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
