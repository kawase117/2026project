"""朝の定例: ana-slo の前日分を取り込み、期日の来た予告を採点する（X監視は別スケジュール）。

2026-09-24 以降のスケジュール（3タスクに分離、適応的に早期完了）:
    03:00  X監視のみ（scraper/twitter_monitor/run_daily.py を直接起動）。
           ana-slo とは無関係なので同じロックを取らず独立して回す。
    07:00  ana-slo 取得 + --only-if-complete（本スクリプトを --skip-twitter
           --only-if-complete で起動）。全ホールが前日分まで揃った場合は、
           30分待たずその場で履歴蓄積・予告採点・フォワード凍結まで完了する。
           1ホールでも揃わなければ、その日はここで打ち切り07:30に委ねる。
    07:30  ana-slo 再取得（本スクリプトを --skip-twitter で起動、
           --only-if-complete は付けない）。07:00 で完了済みならスクレイパーが
           取得済みの日をスキップしほぼ無処理で終わるが、履歴/採点/フォワードは
           冪等（採点済み・凍結済みはスキップ）なので再実行しても無害。
           07:00 が不完全だった場合の最終的な安全網として、完全性を問わず必ず実行する。

なぜ ana-slo を先に置くか:
    ana-slo はおおむね 07:30 に前日分を公開する（不定期で、出ない日もある）。
    07:00 の一発目は空振りすることもあるが、**早く公開された日にまで
    30分寝かせる理由は無い**（2026-09-24 指摘）。--only-if-complete で
    「取れているかどうか」を実測してから後続を進めるかを判断する。

    順序には意味がある。`announce register` は target_date > db_max を要求する
    ため、取り込みと登録は競合しうる。ただし取り込むのは**前日分**なので
    db_max は昨日までにしかならず、今日を対象日とする予告は登録できる。
    逆に取り込みを何日も溜めると、その日数ぶんの予告が登録不能になる
    （2026-08-30〜09-06 で実際に6日分を失った）。だから毎日取り込む。

    フォワードテストの凍結（backtest.forward plan-all）は一度凍結すると
    上書きしない仕様なので、全ホールが前日分まで揃うまでは走らせない
    （--only-if-complete が history/announce-score/forward をまとめてゲートする）。

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

from runlock import acquire_or_exit  # 同ディレクトリ

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


def audit_dates(before: dict[str, str], start: str, end: str) -> list[str]:
    """データ監査に渡す日付。実行前の最終日がいちばん古いホールの翌日から end まで(start より前は見ない)。

    取り込みが進まなかった日(どのホールも end まで揃っていた)でも end は必ず含める。
    """
    oldest = min(before.values()) if before else end
    first = max(start, (datetime.strptime(oldest, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d"))
    days = []
    day = datetime.strptime(min(first, end), "%Y%m%d")
    while day.strftime("%Y%m%d") <= end:
        days.append(day.strftime("%Y%m%d"))
        day += timedelta(days=1)
    return days


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
    parser.add_argument("--skip-forward", action="store_true", help="フォワードテストの採点と凍結を行わない")
    parser.add_argument(
        "--skip-event-history",
        action="store_true",
        help="当日イベントのあるホールの答え合わせ表(backtest.event_days morning)を作らない",
    )
    parser.add_argument(
        "--skip-juggler-ledger",
        action="store_true",
        help="ジャグラー持ち越し候補の前向き検証台帳(backtest.juggler_carryover ledger)への追記を行わない",
    )
    parser.add_argument(
        "--skip-scoreboard",
        action="store_true",
        help="前向き検証の総合採点表(backtest.scoreboard → backtest/forward/SCOREBOARD.md)を更新しない",
    )
    parser.add_argument(
        "--skip-hall-review",
        action="store_true",
        help="前日分のホールレビューHTML生成(backtest.daily_digest hall-review)を行わない",
    )
    parser.add_argument(
        "--skip-announce-score",
        action="store_true",
        help="期日の来た予告の採点を行わない（ana-slo 公開前の早い試行でフォワード凍結を巻き込まないため）",
    )
    parser.add_argument(
        "--skip-git-push",
        action="store_true",
        help="朝の機械生成物(backtest/forward・daily_digest)の自動コミット&プッシュを行わない",
    )
    parser.add_argument(
        "--skip-audit",
        action="store_true",
        help="取り込み直後のデータ品質監査(database.data_audit)を行わない",
    )
    parser.add_argument(
        "--ignore-audit-errors",
        action="store_true",
        help="監査が ERROR でも予告採点・フォワード・ジャグラー台帳を止めない（人が中身を確認した後の再実行用）",
    )
    parser.add_argument(
        "--only-if-complete",
        action="store_true",
        help=(
            "ana-slo取得後、全ホールが前日分まで揃っていた場合だけ履歴/予告採点/フォワードへ進む。"
            "1ホールでも揃わなければそこで打ち切り、後続の再試行タスク（07:30枠）に委ねる。"
            "07:00枠が早期に成功した日は、30分待たずその場で最後まで完了させるための仕組み"
            "（2026-09-24: 07:00の再試行は『取れていなかった場合の保険』であって、"
            "取れているのに後続処理を30分寝かせる理由は無いという指摘を反映）。"
        ),
    )
    # 取得済みの日はスクレイパー側でスキップされるので、窓を広く取っても
    # 実際に開くのは欠けている日だけ。前日1日だけにすると、途中にできた穴
    # （403で落ちた日、ana-slo が遅れて掲載した日）が永久に埋まらない。
    parser.add_argument("--days", type=int, default=10, help="何日前まで遡って欠落を探すか (既定 10)")
    args = parser.parse_args()

    # 手で回している最中にスケジューラが発火しても、二重には走らせない。
    # 2026-09-12 に run_daily.py が 07:51 と 08:01 の2本同時に走り、
    # state.db と .browser_profile を奪い合った。
    lock = acquire_or_exit("daily_pipeline")
    try:
        return _run(args)
    finally:
        lock.release()


def _run(args: argparse.Namespace) -> int:
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

        if args.only_if_complete:
            incomplete = sorted(hall for hall, value in after.items() if value != end)
            if incomplete:
                print("\n  ※ --only-if-complete: 前日分(%s)がまだ揃っていないホールがある。" % end)
                for hall in incomplete:
                    print("      %-34s %s" % (hall, after.get(hall, "なし")))
                print("     履歴/予告採点/フォワードはここでは行わない（07:30枠の再試行に委ねる）。")
                return 0
            print("\n  ※ --only-if-complete: 全ホールが前日分まで揃った。このまま最後まで進める。")

    # 取り込んだ前日分(end)のデータ品質監査。結果は document/registry/DATA_AUDIT.jsonl に追記される。
    #
    # ERROR のときに朝の実行全体を止めず、「一度書いたら直せない段」だけを飛ばす。理由:
    #   - このスクリプトは個々の段が失敗しても終了コードで落とさず先へ進む作法で、
    #     完全性で後続を止めるのも --only-if-complete が「不可逆な段をまとめてゲートする」形を取っている。
    #     監査も同じ形に合わせる。
    #   - 予告の採点（作り直し禁止）、フォワードの採点・凍結（凍結は上書きしない）、
    #     ジャグラー台帳（追記のみ）は、壊れたデータで一度書くと嘘の実績が残る。だから飛ばす。
    #   - 履歴の蓄積・ホールレビュー・当日の答え合わせ表は同じ日を再実行すれば上書きされるので続ける。
    #     X 収集と自動プッシュはデータ品質と無関係なので続ける。
    #   - 飛ばした段は、人が監査結果を確認してから --ignore-audit-errors 付きで再実行すれば取り戻せる
    #     （フォワードの凍結は当日16時が締め切り）。
    # 当日分が未掲載なだけのホールは ERROR にならない（presence=INFO）。
    # 監査する日は前日(end)だけでなく、今回の実行で遡って取り込まれた可能性のある日すべて。
    # スクレイパーは --days 日前まで欠けた日を埋めるので、前日だけを見ると、遡って入った日が
    # 監査を通らずに採点・フォワードに使われる(2026-10-16 レビュー指摘)。
    # 実行前の最終日がいちばん古いホールの翌日から end までを渡す(下限は遡り窓の start)。
    audit_blocked = False
    if not args.skip_audit:
        audit_days = audit_dates(before, start, end)
        command = [PYTHON, "-u", "-X", "utf8", "-m", "database.data_audit"]
        for day in audit_days:
            command += ["--date", day]
        code = run("database.data_audit --date %s" % " ".join(audit_days), command)
        if code != 0 and not args.ignore_audit_errors:
            audit_blocked = True
            print("\n  ⚠️ データ監査で ERROR。予告採点・フォワード・ジャグラー台帳を今回は行わない。")
            print("     document/registry/DATA_AUDIT.jsonl を確認し、問題なければ")
            print("     --skip-anaslo --ignore-audit-errors を付けて再実行すること。")

    if not args.skip_history:
        # 角番ピークと並び箇所数を analysis_results.db に貯める。取込の直後に
        # 置くのは、その日の raw データが入った状態でしか計算できないため。
        # 既存日は同じ definition_id で上書きされるだけなので、窓が重なっても害はない。
        run(
            "database/build_analysis_history.py --since %s" % start,
            [PYTHON, "-u", str(PROJECT_ROOT / "database" / "build_analysis_history.py"), "--since", start],
        )

    if not args.skip_hall_review:
        # 前日分のホールレビューHTML(機種/角番/末尾/並び/列/RB設定判別)。
        # フェーズ2対象の3ホール限定(backtest.daily_digest.HALL_REVIEW_HALLS)。
        # 対象日は取り込んだ前日分(end)。データが無ければ hall-review 側が
        # skipped 扱いのレビューを書き、ここでは落とさない。
        run(
            "backtest.daily_digest hall-review --all-halls --date %s" % end,
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.daily_digest", "hall-review", "--all-halls", "--date", end],
        )

    if not args.skip_announce_score and not audit_blocked:
        print("\n" + "=" * 70)
        print("期日の来た予告の採点")
        print("=" * 70)
        score_due_announcements()

    if not args.skip_forward and not audit_blocked:
        # フォワードテスト。ここに置いていなかったせいで 2026-08-13〜09-10 の
        # 29日間、plan-all も score も一度も走らなかった（約270プラン日を失った）。
        # 手で回す運用に戻さないこと。
        #
        # 採点を先に、凍結を後にする。採点は前日までの実績を使うので取り込みの
        # 直後が最も早い。
        #
        # 凍結の対象は **当日**。取り込み直後なら前日分まで入っているので、
        # 当日分を前日までのデータで凍結できる（締め切りは当日16時、
        # forward.FREEZE_DEADLINE_HOUR）。2026-09-13 までは翌日分を凍結しており、
        # 選択が常に2日前のデータで作られていた。
        # ana-slo が未更新で前日分が無い日も凍結は行い、遅れは RUNS の
        # data_lag_days に残す（2 以上なら古いデータでの凍結）。
        run(
            "backtest.forward score-due",
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.forward", "score-due"],
        )
        run(
            "backtest.forward plan-all（対象は当日）",
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.forward", "plan-all"],
        )

    if not args.skip_juggler_ledger and not audit_blocked:
        # ジャグラー持ち越し候補の前向き検証台帳。取り込んだ前日分(end)を、その前日までの履歴で
        # 作った候補と突き合わせて backtest/forward/juggler_carryover_ledger.jsonl へ追記する。
        # 同じ(ホール,日付,機種)は重複追記しない。失敗しても朝の実行は止めない。
        run(
            "backtest.juggler_carryover ledger（前向き検証の台帳）",
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.juggler_carryover", "ledger", "--date", end],
        )

    if not args.skip_scoreboard:
        # 予測文書の名指し(backtest/predictions)の採点を先に済ませてから総合採点表を作る。
        run(
            "backtest.prediction_ledger score-due（予測文書の名指しの採点）",
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.prediction_ledger", "score-due"],
        )
        # 前向き検証の総合採点表。forward の採点と juggler 台帳の追記が終わった後に置く。
        # backtest/forward/SCOREBOARD.{md,json} に書くので、下の自動コミットの許可範囲に入る。
        run(
            "backtest.scoreboard（前向き検証の総合採点表）",
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.scoreboard"],
        )

    if not args.skip_event_history:
        # 当日イベント・予告のあるホールについて、同じイベント・同じ公約の過去の回の
        # 答え合わせ表を output/event_history/<当日>/ に書き出す（前日分の取り込み後に置く）。
        # 設計: document/plans/2026-09-28-event-result-feedback-loop.md 段階5。
        run(
            "backtest.event_days morning（当日の答え合わせ表）",
            [PYTHON, "-u", "-X", "utf8", "-m", "backtest.event_days", "morning"],
        )

    if not args.skip_twitter:
        run(
            "scraper/twitter_monitor/run_daily.py",
            [PYTHON, "-u", str(PROJECT_ROOT / "scraper" / "twitter_monitor" / "run_daily.py")],
            cwd=PROJECT_ROOT / "scraper" / "twitter_monitor",
        )

    if not args.skip_git_push:
        # forward / daily_digest の機械生成物だけをコミットしてプッシュする(許可リスト方式)。
        # 失敗しても朝の実行は失敗にしない。ローカルのコミットは残り、次の実行で再度プッシュされる。
        run(
            "scripts/auto_commit_push.py",
            [PYTHON, "-u", str(PROJECT_ROOT / "scripts" / "auto_commit_push.py")],
        )

    # ana-slo が未更新でも、X が取れなくても、朝の実行そのものは失敗ではない。
    # 個々の異常は上のログに出るので、終了コードでは落とさない。
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
