#!/usr/bin/env python
"""実行ラッパー：複数ホールのDD分析を一度に実行"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
EDA_SCRIPT = PROJECT_ROOT / "eda" / "dd_sweep_multihhall.py"

halls = ["kamata7", "kamata1", "rakuen"]

for hall in halls:
    print(f"\n{'=' * 60}")
    print(f"Running DD sweep for {hall}")
    print('=' * 60)
    result = subprocess.run([sys.executable, str(EDA_SCRIPT), "--hall", hall], cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"Error running {hall}: {result.returncode}")
        sys.exit(1)

print("\n" + "=" * 60)
print("All DD sweep analysis completed!")
print("=" * 60)
