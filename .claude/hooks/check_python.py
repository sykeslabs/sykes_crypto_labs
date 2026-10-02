"""PostToolUse: byte-compile an edited .py file so syntax errors surface immediately."""
import json
import py_compile
import sys

data = json.load(sys.stdin)
path = (data.get("tool_input") or {}).get("file_path", "")
if path.endswith(".py"):
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        print(f"Syntax error in {path}:\n{e.msg}", file=sys.stderr)
        sys.exit(2)
sys.exit(0)
