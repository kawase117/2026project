"""Daily pipeline entry point: collect, fill any gap, extract, then label.

Profile-timeline crawling silently stops paginating after roughly two and a half
weeks, so a run that follows a break leaves a hole and still exits reporting
success. That happened for real: a run on 2026-09-05 after collecting through
08-12 reported "226 new posts" while 08-14..09-01 came back empty for every
major account, nineteen days lost without a single error.

So the gap is measured before crawling, and anything older than a couple of days
goes through the date-window search instead, which is not subject to that limit.
"""

import argparse
import json
import re
import subprocess
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import DB_PATH

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
LEDGER_PATH = PROJECT_ROOT / "backtest" / "announce" / "LEDGER.jsonl"
PYTHON = sys.executable
JST = ZoneInfo("Asia/Tokyo")
# 予告の対象ホールを本文から拾うための語。表記ゆれを含める
# （蒲田1は「メガ1」「メガいち」「サトウ」などとも書かれる）。
HALL_KEYWORDS = {
    "楽園蒲田店": ("楽園蒲田", "楽蒲"),
    "マルハンメガシティ2000-蒲田1": ("メガシティ2000蒲田1", "メガ1", "メガいち", "蒲田1"),
    "マルハンメガシティ2000-蒲田7": ("メガシティ2000蒲田7", "メガ7", "メガなな", "蒲田7"),
}
# 何日ぶん遡って登録漏れを探すか。これより古い分は register が拒否するので、
# 気づいても RETROACTIVE_NOTES.md 送りになる。
ANNOUNCE_LOOKBACK_DAYS = 10
# 全文の取り直し範囲。タイムラインの article は長文を畳むので、収集しただけの
# 本文は130〜180字で切れている。予告では仕掛けの列挙がまるごと落ちるため、
# 収集の直後に個別ページから取り直す。
#
# 対象は監視ホールに触れている投稿だけに絞る。収集した本文のうち対象ホールに
# 触れているのは 7〜9% しかなく（直近3日で237件中17件）、全件開くと1日80件・
# 14分かかったうえ新着に追いつかなかった。絞れば1日あたり6件程度で済む。
# 予告アカウントはホール名を見出しに置く（「9/7 楽園蒲田」「🪐GALAXYウスイの
# メガなな予想🪐」）ので、折り畳まれた本文でもこの判定は効く。
FULLTEXT_LOOKBACK_DAYS = 7
FULLTEXT_LIMIT = 40
# One day of slack: yesterday's posts are still reachable by the normal crawl.
GAP_TRIGGER_DAYS = 2
# Re-collect from a day before the last known post so a partly-collected day is
# completed rather than half kept.
GAP_OVERLAP_DAYS = 1


def last_collected_date(connection):
    """Return the earliest 'newest post' across accounts, i.e. the weakest link."""
    rows = connection.execute("SELECT handle, MAX(posted_at_jst) FROM seen_tweets GROUP BY handle").fetchall()
    dates = [row[1][:10] for row in rows if row[1]]
    if not dates:
        return None
    return min(date.fromisoformat(value) for value in dates)


def registered_targets():
    """台帳にある (ホール, 対象日) の集合。台帳が無ければ空。"""
    if not LEDGER_PATH.exists():
        return set()
    targets = set()
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("hall") and row.get("target_date"):
            targets.add((row["hall"], row["target_date"]))
    return targets


def is_forecast(text):
    """予告か。結果報告・速報は除く。

    初版は本文に「明日」があることを条件にしていたが、これは取りこぼす。
    999999Q9Q の蒲田7予告は「火曜日のメガななは角◯仕掛け」と曜日で書き、
    「明日」を使わない。実際 2026-09-08 の蒲田7予告（角番仕掛けという
    具体的な主張つき）を検知が落とした。9/8ヘッダを持つ投稿10件が
    「明日」を含まない。

    かわりに、これらのアカウントが見出しで使い分けている語で判定する。
    「予想」「予告」「明日」があれば予告、「速報」「結果」があれば報告。
    報告の判定を先に置くのは、「明日も頼む」で終わる速報があるため。
    """
    if not text:
        return False
    head = "\n".join(text.splitlines()[:2])
    if any(word in head for word in ("速報", "結果", "📈")):
        return False
    return any(word in text for word in ("明日", "予想", "予告"))


def target_date_of(text, posted):
    """予告が指す対象日。見出しに M/D があればそれ、無ければ翌日。

    「9/7 楽園蒲田」のように見出しで対象日を宣言する書き方と、
    「明日は…」しか書かない書き方の両方がある。前者を優先する。
    """
    match = re.match(r"^\s*(\d{1,2})/(\d{1,2})", text)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        year = posted.year
        # 12月末の投稿が1月を指す場合に年をまたぐ
        if posted.month == 12 and month == 1:
            year += 1
        try:
            return date(year, month, day)
        except ValueError:
            pass
    return posted + timedelta(days=1)


def mention_strength(text, header, keywords, n_halls_mentioned):
    """その投稿がそのホール『についての』ものらしさ。0 なら言及なし。

    3 = ハッシュタグでの言及。999999Q9Q は #マルハンメガシティ2000蒲田7 の形で
        対象を明示するので、最も確実。
    2 = 見出し（先頭2行）での言及、かつ投稿が1ホールしか挙げていない。
        kawasakislot の「9/1 楽園蒲田」がこれ。
    1 = 本文中だけの言及、または複数ホールを並べている投稿。
        「西口の楽園蒲田🆚東口はメガ1🆚メガ7って構図でいいですかね」のような
        比較・雑談は3ホールに当たるので、ここへ落ちる。予告は1ホールを名指しする。
    """
    if not any(word in text for word in keywords):
        return 0
    if any(("#" + word) in text for word in keywords):
        return 3
    if n_halls_mentioned == 1 and any(word in header for word in keywords):
        return 2
    return 1


def unregistered_announcements(connection, today):
    """予告が投稿されているのに台帳に無い (ホール, 対象日) を返す。

    収集が正常でも、日次の登録作業が止まれば予告は静かに失われる。実際
    2026-08-30 を最後に 9/7 まで台帳が空き、その間の6日分は register が
    通る状態だったのに登録されなかった。収集の欠損検知だけでは捕まらない
    ので、台帳側も併せて見る。

    判定は粗い。前夜の投稿に「明日」とホール名が入っていれば予告とみなす。
    見落とすより誤検知する方を選んでいる（誤検知は本文を読めば消える）。

    ホール名が本文にあるだけでは、その投稿がそのホール**についての**予告とは
    限らない。kawasakislot の楽園蒲田予告は本文で「メガ1の新店長就任を明らかに
    意識してる」と競合店に触れるので、素朴な部分一致だと楽園蒲田の予告が
    蒲田1の予告として数えられる。そこで見出し（先頭2行）とハッシュタグでの
    言及を本文中の言及より上に置き、根拠として出す投稿もその順で選ぶ。

    根拠を1件だけ任意に選ぶと読み違えが起きる。実際に「西口の楽園蒲田🆚東口は
    メガ1🆚メガ7って構図でいいですかね」という雑談が根拠として表示され、
    正しい検知を誤検知と判断しかけた。同じ組に当たった件数も返す。
    """
    registered = registered_targets()
    since = (today - timedelta(days=ANNOUNCE_LOOKBACK_DAYS)).isoformat()
    rows = connection.execute(
        "SELECT posted_at_jst, COALESCE(full_text, tweet_text), tweet_url FROM seen_tweets WHERE posted_at_jst >= ?",
        (since,),
    ).fetchall()

    missing = {}
    for posted_at, text, url in rows:
        if not is_forecast(text):
            continue
        posted = date.fromisoformat(posted_at[:10])
        # 前夜の投稿は翌営業日が対象。当日昼の投稿も同じ日を指すことがあるが、
        # 前夜のパターンだけを見る（登録が間に合う唯一の窓なので）。
        target = target_date_of(text, posted)
        # 明日を対象とする予告こそ拾う。初版はここで `target > today` を除外して
        # おり、**まだ register できる唯一の分**を落としていた。対象日を過ぎた分は
        # 報告しても RETROACTIVE_NOTES 送りにしかならないので、優先度は逆である。
        if target > today + timedelta(days=1) or target < today - timedelta(days=ANNOUNCE_LOOKBACK_DAYS):
            continue
        header = "\n".join(text.splitlines()[:2])
        n_halls = sum(1 for words in HALL_KEYWORDS.values() if any(word in text for word in words))
        for hall, keywords in HALL_KEYWORDS.items():
            strength = mention_strength(text, header, keywords, n_halls)
            if not strength:
                continue
            key = (hall, target.strftime("%Y%m%d"))
            if key in registered:
                continue
            entry = missing.setdefault(key, {"count": 0, "best": None, "strength": 0})
            entry["count"] += 1
            # 見出し/ハッシュタグでの言及を優先し、同じ強さなら長い本文を採る。
            current = (strength, len(text))
            if entry["best"] is None or current > (entry["strength"], len(entry["best"][1])):
                entry["best"] = (posted_at, text, url)
                entry["strength"] = strength
    return sorted(missing.items())


def run(script, *arguments):
    command = [PYTHON, str(BASE_DIR / script), *arguments]
    print("\n$ %s %s" % (script, " ".join(arguments)), flush=True)
    result = subprocess.run(command, cwd=str(BASE_DIR))
    if result.returncode != 0:
        print("  -> 終了コード %d" % result.returncode, flush=True)
    return result.returncode


def run_project(*arguments):
    """プロジェクトルートで実行する。統合レイヤーは backtest/ 側にある。"""
    command = [PYTHON, *arguments]
    print("\n$ %s" % " ".join(arguments), flush=True)
    result = subprocess.run(command, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print("  -> 終了コード %d" % result.returncode, flush=True)
    return result.returncode


def refresh_integrated_layer():
    """収集の成果を、予告・結果発表・実績を束ねた層に反映する。

    ここまでの工程は state.db を更新するだけで、分析側からは見えない。
    `db/analysis_results.db` まで通して初めて `backtest.integrated.machine_frame`
    が新しい日を返すようになるので、日次の最後に必ず流す。
    """
    run_project("backtest/result_corpus.py", "build")
    run_project("backtest/result_corpus.py", "ingest-prose")
    run_project("backtest/result_corpus.py", "link-machines")
    run_project("-m", "backtest.integrated", "ingest-announce")
    run_project("-m", "backtest.integrated", "ingest-retro")
    run_project("-m", "backtest.integrated", "coverage")


def main() -> int:
    parser = argparse.ArgumentParser(description="収集・欠損補完・抽出・ラベル付けを順に実行します。")
    parser.add_argument("--extract-limit", type=int, default=400, help="1回の抽出で処理する画像数の上限 (既定 400)")
    parser.add_argument("--extract-handles", default=None, help="抽出対象のアカウントを限定 (カンマ区切り)")
    parser.add_argument("--skip-extract", action="store_true", help="抽出を行わず、収集とラベル付けだけ実行します。")
    parser.add_argument("--skip-fulltext", action="store_true", help="折り畳まれた本文の取り直しを行いません。")
    args = parser.parse_args()

    today = datetime.now(JST).date()
    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        last = last_collected_date(connection)

    if last is None:
        print("収集履歴がありません。先に scrape_tweets.py を実行してください。")
        return 1

    gap_days = (today - last).days
    print("最終取得日 %s / 本日 %s (%d日の空き)" % (last, today, gap_days))

    if gap_days >= GAP_TRIGGER_DAYS:
        since = last - timedelta(days=GAP_OVERLAP_DAYS)
        until = today + timedelta(days=1)
        print("プロフィール巡回では遡り切れないため、検索で %s〜%s を補完します。" % (since, until))
        run(
            "backfill_search.py",
            "--since",
            since.isoformat(),
            "--until",
            until.isoformat(),
            "--window-days",
            "7",
            "--min-delay",
            "25",
            "--max-delay",
            "45",
        )
    else:
        print("空きは %d 日なので通常の巡回で足ります。" % gap_days)

    run("scrape_tweets.py")

    if not args.skip_fulltext:
        # 台帳ギャップ検知も予告の登録もこの全文を読むので、prefilter より前に置く。
        run(
            "fetch_full_text.py",
            "--since",
            (today - timedelta(days=FULLTEXT_LOOKBACK_DAYS)).isoformat(),
            "--any-of",
            ",".join(word for words in HALL_KEYWORDS.values() for word in words),
            "--limit",
            str(FULLTEXT_LIMIT),
        )

    run("prefilter.py")

    if not args.skip_extract:
        extract = ["--limit", str(args.extract_limit), "--redo-failed", "--newest-first"]
        if args.extract_handles:
            extract = ["--handles", args.extract_handles] + extract
        run("extract_answers.py", *extract)

    run("infer_hall.py", "--apply")
    run("resolve_dates.py", "--apply")
    refresh_integrated_layer()

    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        gaps = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT substr(posted_at_jst, 1, 10) AS day
                FROM seen_tweets WHERE posted_at_jst >= ?
            )
            """,
            ((today - timedelta(days=30)).isoformat(),),
        ).fetchone()[0]
    print("\n直近30日のうち投稿を取得できた日: %d 日" % gaps)
    if gaps < 25:
        print("  ※ 欠損が疑われます。backfill_search.py で期間を指定して補完してください。")

    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        missing = unregistered_announcements(connection, today)
    print("\n予告があるのに台帳に無い対象日: %d 件" % len(missing))
    today_key = today.strftime("%Y%m%d")
    tomorrow_key = (today + timedelta(days=1)).strftime("%Y%m%d")
    # register できるものを先に出す。過ぎた分をいくら並べても行動は変わらない。
    actionable = [row for row in missing if row[0][1] in (today_key, tomorrow_key)]
    stale = [row for row in missing if row[0][1] not in (today_key, tomorrow_key)]
    for label, group in (("★ 今すぐ register できる", actionable), ("（対象日を過ぎた分）", stale)):
        if not group:
            continue
        print("\n%s: %d 件" % (label, len(group)))
        for (hall, target), entry in group:
            posted_at, text, url = entry["best"]
            others = "" if entry["count"] == 1 else " ほか%d件" % (entry["count"] - 1)
            print("  %s %s (投稿 %s%s)" % (target, hall, posted_at[:16], others))
            print("    %s" % url)
            print("    %s" % text[:70].replace("\n", " "))
    if missing:
        print(
            "  ※ 対象日を過ぎた分は register できない（事後登録は拒否される）。\n"
            "     backtest/announce/RETROACTIVE_NOTES.md に『登録を見送った予告』として記録すること。\n"
            "     ただし失われるのは**的中率の証拠としての価値だけ**である。予告文と投稿時刻は\n"
            "     外部タイムスタンプ付きの事実なので、`backtest.integrated ingest-retro` が\n"
            "     遡及レーン（retroactive=1）に機械抽出で取り込み、統合フレームの\n"
            "     `announced_model_retro` から引ける。的中率の分子分母には入れないこと。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
