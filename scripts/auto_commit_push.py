"""朝の定例が書き出した機械生成物だけを、コミットしてプッシュする。

背景: 毎朝の run_morning.py は backtest/forward/ と backtest/daily_digest/ に出力を書くが、
git の処理が無く、未コミットの変更が毎日溜まっていた(2026-10-11時点で59件)。

対象は許可リスト方式で、機械的に生成され人が手を入れない出力だけ:
    backtest/forward/        凍結picks・実行ログ・台帳
    backtest/daily_digest/   ホールレビュー・watches・summary
    backtest/predictions/    予測文書の名指しの凍結と採点(score-due が result を書き込む)
    document/registry/DATA_AUDIT.jsonl  取り込み直後のデータ品質監査の結果(1ホール1日1行の追記)

対象外にしているもの(自動でコミットしない):
    backtest/announce/       下書きが台帳のダイジェストと対になっている。セッションで編集中の
                             ファイルを先にコミットすると台帳とずれる。
    document/registry/       人が確認して書く台帳。
    その他                   取り込みCSV・pkl等の作業の残骸。

やらないこと:
    pull / rebase     他のセッションの未コミット変更を巻き込む(2026-10-11に pull --rebase が失敗)。
    force push        しない。
    プッシュ失敗時の再試行  しない。ローカルのコミットは残り、次の実行のプッシュに含まれる。

使い方:
    venv\\Scripts\\python.exe scripts/auto_commit_push.py [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PATHS = [
    "backtest/forward",
    "backtest/daily_digest",
    "backtest/predictions",
    # document/registry/ は人が書く台帳なので対象外だが、この1ファイルだけは毎朝の監査が機械的に追記する
    "document/registry/DATA_AUDIT.jsonl",
]
BRANCH = "main"
JST = ZoneInfo("Asia/Tokyo")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def in_progress() -> str | None:
    """rebase/merge/cherry-pick の途中なら、その名前を返す。"""
    git_dir = Path(git("rev-parse", "--absolute-git-dir").stdout.strip())
    for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        if (git_dir / name).exists():
            return name
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="朝の機械生成物だけをコミット&プッシュする")
    ap.add_argument("--dry-run", action="store_true", help="対象を表示するだけで何も変更しない")
    args = ap.parse_args(argv)

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != BRANCH:
        print(f"[auto-push] ブランチが {branch}（{BRANCH}ではない）のためスキップ")
        return 0
    busy = in_progress()
    if busy:
        print(f"[auto-push] {busy} の途中のためスキップ")
        return 0

    status = git("status", "--porcelain", "--", *ALLOWED_PATHS)
    # 日本語パスは git が引用符付きで返すため、行数だけ数える。
    changed = [line for line in status.stdout.splitlines() if line.strip()]
    if not changed:
        print("[auto-push] 対象の変更なし")
    else:
        print(f"[auto-push] 対象の変更 {len(changed)} 件")
        if args.dry_run:
            return 0
        add = git("add", "--", *ALLOWED_PATHS)
        if add.returncode != 0:
            print("[auto-push] git add 失敗:", add.stderr.strip(), file=sys.stderr)
            return 1
        today = datetime.now(JST).strftime("%Y-%m-%d")
        message = f"chore: 朝の自動出力を追加（forward・daily_digest）{today}"
        # パス指定のコミットは、他にステージ済みのファイルがあっても巻き込まない。
        commit = git("commit", "-m", message, "--", *ALLOWED_PATHS)
        if commit.returncode != 0:
            # pre-commit(ruff-format等)が書き換えた場合は再ステージして1回だけ再試行する。
            git("add", "--", *ALLOWED_PATHS)
            commit = git("commit", "-m", message, "--", *ALLOWED_PATHS)
        if commit.returncode != 0:
            print("[auto-push] コミット失敗:", (commit.stdout + commit.stderr).strip()[-600:], file=sys.stderr)
            return 1
        print("[auto-push] コミット済み")

    ahead = git("rev-list", "--count", f"origin/{BRANCH}..HEAD").stdout.strip()
    if ahead in ("", "0"):
        print("[auto-push] プッシュ対象なし")
        return 0
    if args.dry_run:
        print(f"[auto-push] (dry-run) 未プッシュのコミット {ahead} 件")
        return 0
    push = git("push", "origin", BRANCH)
    if push.returncode != 0:
        print(
            "[auto-push] プッシュ失敗（ローカルのコミットは残る。次の実行で再度プッシュする）:\n"
            + (push.stdout + push.stderr).strip()[-600:],
            file=sys.stderr,
        )
        return 1
    print(f"[auto-push] プッシュ済み（{ahead} コミット）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
