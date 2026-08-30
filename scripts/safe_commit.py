"""pre-commitがruff-format等でファイルを書き換えた場合に、再ステージして1回だけ再コミットする。

背景: 2026-08-25のmirror-review(document/mirror_evidence_2026-08-25.md セクション4-E)で、
pre-commitのruff-check/ruff-formatがファイルを書き換えてコミットが一度失敗し、
手作業で再ステージ・再コミットする手順が3回以上独立に観測された。

このスクリプトはフックをスキップしない。フックが書き換えた分を再ステージするだけで、
フック自体は毎回通常通り実行される。

使い方:
    venv\\Scripts\\python.exe scripts/safe_commit.py "コミットメッセージ"

事前に対象ファイルを `git add` しておくこと(このスクリプトは `git add -A` のような
無差別なステージは行わない。再試行時のみ、既にステージ済み/追跡済みのファイルに対して
`git add -u` で再ステージする)。
"""

from __future__ import annotations

import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('usage: safe_commit.py "<commit message>"', file=sys.stderr)
        return 1
    message = argv[0]

    result = subprocess.run(["git", "commit", "-m", message])
    if result.returncode == 0:
        print("commit succeeded")
        return 0

    # pre-commit のフックがファイルを書き換えた場合、変更はワークツリーに残るが
    # ステージには乗っていない。追跡済みファイルの変更分だけ再ステージして1回だけ再試行する。
    print("commit failed (pre-commitがファイルを書き換えた可能性) — 再ステージして1回だけ再試行します", file=sys.stderr)
    subprocess.run(["git", "add", "-u"])

    result = subprocess.run(["git", "commit", "-m", message])
    if result.returncode == 0:
        print("commit succeeded (pre-commit整形後の再試行)")
        return 0

    print("commit failed — 上記のpre-commit出力を確認してください(自動リトライは1回のみ)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
