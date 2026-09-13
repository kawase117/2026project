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

# scripts/runlock.py を読むためのパス追加。twitter_monitor/ から直接起動される。
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from runlock import acquire_or_exit  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
LEDGER_PATH = PROJECT_ROOT / "backtest" / "announce" / "LEDGER.jsonl"
PYTHON = sys.executable
JST = ZoneInfo("Asia/Tokyo")
# 予告の対象ホールを本文から拾うための語。表記ゆれを含める
# （蒲田1は「メガ1」「メガいち」「サトウ」などとも書かれる）。
#
# キーは backtest/announce の hall 表記（台帳の突き合わせに使う）。DB を持つ
# ホールは全部並べる。2026-09-14 まで楽園・蒲田1・蒲田7 の3ホールしか無く、
# kawasakislot の「9/14 レイトギャップ平和島」予告が全文取得の対象から漏れて
# 本文が「狙い目」の直前で切れたまま残った（登録すべき仕掛けの列挙が丸ごと欠落）。
# 「大森」「ヒロキ」「雑色」単独は同系列の別店舗に当たるので使わない。
HALL_KEYWORDS = {
    "楽園蒲田店": ("楽園蒲田", "楽蒲"),
    "マルハンメガシティ2000-蒲田1": ("メガシティ2000蒲田1", "メガ1", "メガいち", "蒲田1"),
    "マルハンメガシティ2000-蒲田7": ("メガシティ2000蒲田7", "メガ7", "メガなな", "蒲田7"),
    "レイトギャップ平和島": ("レイトギャップ平和島", "平和島"),
    "みとや大森町店": ("みとや大森町", "みとや大森"),
    "ARROW池上店": ("ARROW池上", "アロー池上"),
    "ザ-シティ-ベルシティ雑色店": ("ベルシティ雑色",),
    "ヒロキ東口店": ("ヒロキ東口",),
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
# 空きの測り方（2026-09-14 改訂）。
#
# 初版は全アカウントの「最新投稿日」の最小値を空きとしていた。これだと投稿の
# 少ないアカウントが1つあるだけで毎朝 backfill_search.py が走る。実際
# kengyo_niki（最終投稿 08-11、巡回は「tweet articles unavailable」で失敗）に
# 引きずられて 08-10 からの検索補完が毎日走り、朝の実行が40分を超えて
# fetch_full_text.py が 08:14 になっても始まらず、当日登録すべき予告の本文が
# 切れたまま残った。
#
# そこでアカウントごとに次の3つを見る。
#   1. 自分の投稿間隔。10日おきに投稿する店長アカウントの9日の沈黙は欠損ではない。
#   2. 検索補完での確認済み範囲。backfill_progress に done/empty で残った窓が
#      最新投稿から途切れずつながっていれば、そこまでは「投稿が無いことを確認済み」。
#   3. 休眠。最も新しいアカウントより DORMANT_DAYS 以上遅れているものは、収集の
#      断絶ではなくアカウント側の事情（休眠・非公開・凍結・巡回失敗）とみなし、
#      報告だけして補完の引き金にしない。基準を「今日」ではなく「最も新しい
#      アカウント」に置くのは、本物の断絶では全アカウントが一緒に古くなり、
#      主要アカウントが休眠扱いにならないようにするため。
CADENCE_LOOKBACK_DAYS = 60
# 投稿日の間隔の何分位までを「いつもの沈黙」とみなすか。
CADENCE_QUANTILE = 0.9
# 間隔を推定するのに最低限必要な間隔の数。足りなければ GAP_TRIGGER_DAYS を使う。
CADENCE_MIN_INTERVALS = 3
DORMANT_DAYS = 14


def _posting_days(connection):
    """アカウントごとの投稿日（重複なし・昇順）。"""
    days = {}
    rows = connection.execute(
        "SELECT DISTINCT handle, substr(posted_at_jst, 1, 10) FROM seen_tweets "
        "WHERE posted_at_jst IS NOT NULL ORDER BY 1, 2"
    ).fetchall()
    for handle, day in rows:
        days.setdefault(handle, []).append(date.fromisoformat(day))
    return days


def _allowed_silence(days):
    """そのアカウントにとって普通の沈黙日数。最新投稿の手前 CADENCE_LOOKBACK_DAYS 日で測る。"""
    recent = [day for day in days if day > days[-1] - timedelta(days=CADENCE_LOOKBACK_DAYS)]
    intervals = sorted((later - earlier).days for earlier, later in zip(recent, recent[1:]))
    if len(intervals) < CADENCE_MIN_INTERVALS:
        return GAP_TRIGGER_DAYS
    quantile = intervals[min(len(intervals) - 1, int(len(intervals) * CADENCE_QUANTILE))]
    return min(max(GAP_TRIGGER_DAYS, quantile), DORMANT_DAYS)


def _search_confirmed_through(connection, handle, newest):
    """検索補完で投稿の有無を確認済みの最終日。最新投稿日から途切れずつながる窓だけを数える。

    窓は [window_start, window_end) で、完了時刻より先は確認できていない。
    つながりを要求するのは、途中の窓が failed のまま後ろの窓だけ done だと、
    その間の欠損を確認済みと取り違えるため。
    """
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='backfill_progress'").fetchone():
        return newest
    covered = newest
    rows = connection.execute(
        "SELECT window_start, window_end, completed_at_jst FROM backfill_progress "
        "WHERE handle = ? AND status IN ('done', 'empty') ORDER BY window_start",
        (handle,),
    ).fetchall()
    for start, end, completed in rows:
        if date.fromisoformat(start) > covered:
            break
        through = date.fromisoformat(end) - timedelta(days=1)
        if completed:
            through = min(through, date.fromisoformat(completed[:10]))
        covered = max(covered, through)
    return covered


def collection_gap(connection, today):
    """収集の空きをアカウントごとに測る。

    戻り値は dict:
      last     … 補完の起点にする日。quiet・dormant を除いたアカウントの確認済み最終日の
                 最小値。履歴が無ければ None。
      gap_days … today - last
      lagging  … 補完の引き金になったアカウント [(handle, 最新投稿日, 確認済み最終日, 許容沈黙日数)]
      quiet    … 沈黙しているが自分の投稿間隔の範囲内なので対象外にしたアカウント
      dormant  … 休眠・非公開・凍結・巡回失敗の疑いで対象外にしたアカウント
                 [(handle, 最新投稿日, 確認済み最終日)]
    """
    days_by_handle = _posting_days(connection)
    if not days_by_handle:
        return {"last": None, "gap_days": None, "lagging": [], "quiet": [], "dormant": []}
    freshest = max(days[-1] for days in days_by_handle.values())

    lagging, quiet, dormant, counted = [], [], [], []
    for handle, days in sorted(days_by_handle.items()):
        newest = days[-1]
        covered = _search_confirmed_through(connection, handle, newest)
        if (freshest - newest).days >= DORMANT_DAYS:
            dormant.append((handle, newest, covered))
            continue
        allowed = _allowed_silence(days)
        # 検索で直近まで確認済みなら、沈黙の長さに関係なく遅れではない。
        stalled = (today - covered).days >= GAP_TRIGGER_DAYS
        if stalled and (today - newest).days <= allowed:
            quiet.append((handle, newest, covered, allowed))
            continue
        counted.append(covered)
        if stalled:
            lagging.append((handle, newest, covered, allowed))

    # 休眠の基準は最も新しいアカウントなので、そのアカウント自身は必ず counted に入る。
    last = min(counted)
    return {"last": last, "gap_days": (today - last).days, "lagging": lagging, "quiet": quiet, "dormant": dormant}


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

    # state.db と scraper/.browser_profile を単独で掴む。run_morning.py と
    # run_daily_ingest.py の両方がこのスクリプトを子プロセスで呼ぶため、
    # 2026-09-12 には 07:51 と 08:01 の2本が同時に走った。
    lock = acquire_or_exit("twitter_monitor")
    try:
        return _run(args)
    finally:
        lock.release()


def _run(args: argparse.Namespace) -> int:
    today = datetime.now(JST).date()
    with sqlite3.connect(DB_PATH, timeout=60) as connection:
        gap = collection_gap(connection, today)

    last = gap["last"]
    if last is None:
        print("収集履歴がありません。先に scrape_tweets.py を実行してください。")
        return 1

    gap_days = gap["gap_days"]
    print("最終取得日 %s / 本日 %s (%d日の空き)" % (last, today, gap_days))
    for handle, newest, covered, allowed in gap["lagging"]:
        print("  遅れ: %s 最終投稿 %s / 確認済み %s (普段の沈黙 %d日まで)" % (handle, newest, covered, allowed))
    for handle, newest, covered, allowed in gap["quiet"]:
        print("  対象外(投稿間隔の範囲内): %s 最終投稿 %s (普段の沈黙 %d日まで)" % (handle, newest, allowed))
    for handle, newest, covered in gap["dormant"]:
        # 補完の引き金にはしないが、黙って落とすと巡回失敗に気づけないので必ず出す。
        searched = "検索でも %s まで投稿なし" % covered if covered > newest else "検索での確認なし"
        print(
            "  ※ 休眠・非公開・凍結・巡回失敗の疑い: %s 最終投稿 %s（%s）。"
            "scrape_tweets.py のログで「tweet articles unavailable」を確認し、"
            "アカウントの状態を見て config.ACCOUNTS から外すか判断すること。" % (handle, newest, searched)
        )

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
