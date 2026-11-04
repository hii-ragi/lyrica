"""Exercise the frozen executable, including Japanese Windows encoding."""

import json
from pathlib import Path
import subprocess
import sys

binary = Path(sys.argv[1]).resolve()
request = {"operation": "render_lrc", "lines": [{"start": 59.995, "text": "宇宙へ"}]}
result = subprocess.run([str(binary)], input=json.dumps(request, ensure_ascii=False),
                        encoding="utf-8", capture_output=True, timeout=30, check=True)
expected = {"lrc": "[01:00.00]宇宙へ\n"}
if json.loads(result.stdout) != expected:
    raise SystemExit(f"Unexpected frozen backend response: {result.stdout!r}")
invalid = subprocess.run([str(binary)], input='{"operation":"unknown"}',
                         encoding="utf-8", capture_output=True, timeout=30, check=False)
if invalid.returncode != 1 or "error" not in json.loads(invalid.stdout):
    raise SystemExit("Frozen backend did not reject an invalid request")
print("Frozen backend smoke test passed")
