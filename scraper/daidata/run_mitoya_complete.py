"""収集→分析を続けて実行する。収集が停止(429/403/検算不一致)した場合は分析しない。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scraper.daidata import analyze, collect  # noqa: E402


def main() -> int:
    try:
        rows, meta = collect.collect()
    except collect.RateLimited as e:
        print(f"STOP(429): {e}", file=sys.stderr)
        return 2
    except collect.CollectError as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 1
    csv_path = collect.write_csv(rows, meta)
    print(f"CSV: {csv_path}\n{meta}")
    print(f"REPORT: {analyze.analyze(csv_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
