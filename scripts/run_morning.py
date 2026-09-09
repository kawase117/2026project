"""朝の定例: ana-slo の前日分を取り込み、期日の来た予告を採点し、X監視を回す。

なぜ ana-slo を先に置くか:
    ana-slo はおおむね 07:30 に前日分を公開する（不定期で、出ない日もある）。
    タスクは 08:00 なので、その直後を狙って前日分だけを取りに行く。

    順序には意味がある。`announce register` は target_date > db_max を要求する
    ため、取り込みと登録は競合しうる。ただし取り込むのは**前日分**なので
    db_max は昨日までにしかならず、今日を対象日とする予告は登録できる。
    逆に取り込みを何日も溜めると、その日数ぶんの予告が登録不能になる
    （2026-08-30〜09-06 で実際に6日分を失った）。だから毎日取り込む。

更新が無い日を失敗にしない:
    ana-slo が更新されない日は一覧に日付リンクが無く、ホールごとに警告が出て
    成功0件になる。これは異常ではないので、終了コードでは落とさず、
    取り込めた日数だけを報告する。翌日の実行で自然に埋まる。

403 について:
    連続アクセスで 403 が返る。2026-09-07 に 8日×10ホール=80ページを一度に
    取りに行って途中で遮断された。前日分だけなら 10ページなので通常は問題ない。
    遮断された場合はホール単位で諦めて次へ進む（anaslo_scraper_auto_multi 側）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
JST = ZoneInfo("Asia/Tokyo")
LEDGER_PATH = PROJECT_ROOT / "backtest" / "announce" / "LEDGER.jsonl"
ANNOUNCE_DIR = PROJECT_ROOT / "backtest" / "announce"
DB_DIR = PROJECT_ROOT / "db"


def run(label: str, command: list[str], cwd: Path | None = None) -> int:
    print("\n" + "=" * 70, flush=True)
    print("$ %s" % label, flush=True)
    print("=" * 70, flush=True)
    result = subprocess.run(command, cwd=str(cwd or PROJECT_ROOT))
    if result.returncode != 0:
        print("  -> 終了コード %d" % result.returncode, flush=True)
    return result.returncode


def hall_max_dates() -> dict[str, str]:
    """ホールごとの収録最終日。DBが無ければ含めない。"""
    out: dict[str, str] = {}
    for path in sorted(DB_DIR.glob("*.db")):
        try:
            connection = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            row = connection.execute("SELECT MAX(date) FROM machine_detailed_results").fetchone()
            connection.close()
        except sqlite3.Error:
            continue
        if row and row[0]:
            out[path.stem] = row[0]
    return out


def score_due_announcements() -> None:
    """対象日のデータが揃った未採点の予告を採点する。

    採点は結果ファイルを書き込むだけで、予告の内容には触れない（announce.py が
    登録時のダイジェストを検証し、書き換わっていれば拒否する）。

    撤回・差し替え済みの版は採点しない。台帳には撤回前の行も残っており、
    素朴に台帳を辿ると `<key>.withdrawn.json` が併存する版まで採点してしまう。
    実際にこの実装の初版が、対象日を誤って登録し撤回済みだった
    rakuen__20260828 と rakuen__20260829 に結果を書き込んだ（手で戻した）。
    撤回済みの版を誤った対象日で採点すると、台帳に嘘の実績が残る。
    """
    if not LEDGER_PATH.exists():
        print("台帳がありません。")
        return
    maxes = hall_max_dates()
    pending = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key, hall, target = row.get("key"), row.get("hall"), row.get("target_date")
        if not (key and hall and target):
            continue
        path = ANNOUNCE_DIR / (key + ".json")
        if not path.exists():
            continue
        if (ANNOUNCE_DIR / (key + ".withdrawn.json")).exists():
            print("  %s %s: 撤回済みのため採点しない (%s)" % (target, hall, key))
            continue
        if (ANNOUNCE_DIR / (key + "__v2.json")).exists():
            print("  %s %s: v2 に差し替え済みのため採点しない (%s)" % (target, hall, key))
            continue
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("result") is not None:
            continue  # 採点済み。作り直しは禁止されている
        if maxes.get(hall, "") < target:
            print("  %s %s: 対象日のデータがまだ無い (DB最終 %s)" % (target, hall, maxes.get(hall, "なし")))
            continue
        pending.append((target, hall, path))

    if not pending:
        print("採点できる予告はありません。")
        return
    for target, hall, path in sorted(pending):
        print("\n--- 採点 %s %s ---" % (target, hall), flush=True)
        result = subprocess.run(
            [PYTHON, "-m", "backtest.announce", "score", str(path)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
        )
        if result.returncode != 0:
            print("  失敗: %s" % result.stderr.decode("utf-8", "replace").strip().splitlines()[-1:])
            continue
        obj = json.loads(result.stdout.decode("utf-8"))
        claims = obj.get("result", {}).get("claims", [])
        hits = sum(1 for c in claims if c.get("hit") is True)
        misses = sum(1 for c in claims if c.get("hit") is False)
        unknown = sum(1 for c in claims if c.get("hit") is None)
        print("  的中 %d / 外れ %d / 判定不能 %d  (%s)" % (hits, misses, unknown, path.name))
        print("  ⚠️ 機械判定のみ。台番号別の確認・並びブロック検出・RB確率での裏取りは")
        print("     announce-prep スキルの『答え合わせ』節に従って別途行うこと。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-anaslo", action="store_true", help="ana-slo の取得と取り込みを行わない")
    parser.add_argument("--skip-twitter", action="store_true", help="X監視パイプラインを回さない")
    parser.add_argument("--skip-history", action="store_true", help="analysis_results.db への日次指標の蓄積を行わない")
    # 取得済みの日はスクレイパー側でスキップされるので、窓を広く取っても
    # 実際に開くのは欠けている日だけ。前日1日だけにすると、途中にできた穴
    # （403で落ちた日、ana-slo が遅れて掲載した日）が永久に埋まらない。
    parser.add_argument("--days", type=int, default=10, help="何日前まで遡って欠落を探すか (既定 10)")
    args = parser.parse_args()

    today = datetime.now(JST).date()
    start = (today - timedelta(days=args.days)).strftime("%Y%m%d")
    end = (today - timedelta(days=1)).strftime("%Y%m%d")

    before = hall_max_dates()
    print("ホール別の収録最終日 (実行前):")
    for hall, value in sorted(before.items()):
        print("  %-34s %s" % (hall, value))

    if not args.skip_anaslo:
        run(
            "anaslo_scraper_auto_multi.py --start-date %s --end-date %s" % (start, end),
            [
                PYTHON,
                "-u",
                str(PROJECT_ROOT / "scraper" / "anaslo_scraper_auto_multi.py"),
                "--start-date",
                start,
                "--end-date",
                end,
            ],
            cwd=PROJECT_ROOT / "scraper",
        )
        run(
            "database/batch_incremental_updater.py",
            [PYTHON, "-u", str(PROJECT_ROOT / "database" / "batch_incremental_updater.py")],
        )

        after = hall_max_dates()
        print("\n取り込み結果:")
        advanced = 0
        for hall in sorted(after):
            old, new = before.get(hall, "なし"), after[hall]
            if old != new:
                advanced += 1
                print("  %-34s %s -> %s" % (hall, old, new))
            else:
                print("  %-34s %s (変化なし)" % (hall, old))
        if advanced == 0:
            print("\n  ※ どのホールも進みませんでした。ana-slo が未更新（不定期）か、")
            print("     403で遮断された可能性があります。翌日の実行で埋まります。")

    if not args.skip_history:
        # 角番ピークと並び箇所数を analysis_results.db に貯める。取込の直後に
        # 置くのは、その日の raw データが入った状態でしか計算できないため。
        # 既存日は同じ definition_id で上書きされるだけなので、窓が重なっても害はない。
        run(
            "database/build_analysis_history.py --since %s" % start,
            [PYTHON, "-u", str(PROJECT_ROOT / "database" / "build_analysis_history.py"), "--since", start],
        )

    print("\n" + "=" * 70)
    print("期日の来た予告の採点")
    print("=" * 70)
    score_due_announcements()

    if not args.skip_twitter:
        run(
            "scraper/twitter_monitor/run_daily.py",
            [PYTHON, "-u", str(PROJECT_ROOT / "scraper" / "twitter_monitor" / "run_daily.py")],
            cwd=PROJECT_ROOT / "scraper" / "twitter_monitor",
        )

    # ana-slo が未更新でも、X が取れなくても、朝の実行そのものは失敗ではない。
    # 個々の異常は上のログに出るので、終了コードでは落とさない。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
