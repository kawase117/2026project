#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スクレイパー実行ラッパー（エンコーディング対応）
"""

import sys
import subprocess
import datetime

# 実行ログを記録
output_file = f"scraper_output_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

print(f"Scraper execution log: {output_file}")
print("=" * 60)

# subprocess でスクレイパーを実行し、UTF-8 で出力
result = subprocess.run(
    [sys.executable, "scraper/anaslo-scraper_multi.py"],
    encoding='utf-8',
    errors='replace',
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

# 出力をコンソール＆ファイルに同時に書込
with open(output_file, 'w', encoding='utf-8') as f:
    for line in result.stdout.split('\n'):
        print(line)
        f.write(line + '\n')

print("=" * 60)
print(f"Exit code: {result.returncode}")
sys.exit(result.returncode)
