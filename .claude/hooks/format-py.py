"""PostToolUse hook: Edit/Write された .py ファイルを ruff format で自動整形する。"""

import json
import subprocess
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

path = (data.get("tool_input") or {}).get("file_path", "")
if path.endswith(".py"):
    subprocess.run([sys.executable, "-m", "ruff", "format", "-q", path], timeout=30)
sys.exit(0)
