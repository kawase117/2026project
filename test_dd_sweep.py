#!/usr/bin/env python
"""テスト実行スクリプト"""

import sys
from eda.dd_sweep_multihhall import main

if __name__ == "__main__":
    try:
        for hall in ["kamata7", "kamata1", "rakuen"]:
            print(f"\n{'=' * 60}")
            print(f"Running: {hall}")
            print('=' * 60)
            result = main(['--hall', hall])
            if result != 0:
                print(f"Error in {hall}: {result}")
                sys.exit(1)
        print("\nAll completed successfully!")
    except Exception as e:
        print(f"Exception: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
