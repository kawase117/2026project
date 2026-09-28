# -*- coding: utf-8 -*-
"""結果発表アカウントの投稿を、機種×日の正解ラベルとして取り込む。

なぜ追跡外ホールを取り込むのか
------------------------------
`slokotae7` は毎日1ホールについて、ホール自身が公表した該当台を定型で書いている。

    8月20日(木)
    楽園松戸店
    四星　ブラックホール
    34/311台(10.9%)
    対象台平均+2944枚

    【全台】
    バイオRE3
    3/3　平均+3639枚

    【1/2】
    SAO2　10台中5台

この89ホールのほとんどは `db/` に実績DBを持たない。台の配置法則を学ぶことはできないし、
学ぼうともしない（ホール横断で配置則をプールしない、という既存方針は動かさない）。

取り込む理由は別にある。**「本物の全台系が差枚の上でどう見えるか」の分布が、
自前データからは原理的に測れない**からである。自前データには正解ラベルが
`backtest/announce/` の数十件しかなく、閾値 +1,800 は自分のスコア分布から
決めた値なので、取りこぼし率を自分で検算すると循環参照になる。

2026-09-09 の計測（当方スケールへ変換後）では、【全台】と公表された機種386件の
平均差枚は 中央値 +1,925 / p25 +915 / p10 +192 で、全粒度1,120件の p05 は
**-408枚** だった。本物の全台系の4分の1は平均差枚が +1,000 に届かない。
`score = G比 × 平均差枚` にG比1.4を当てると、閾値+1,800はこのうち 35.6% を
取り逃がす計算になる。

⚠️ **これは当方10ホールの取りこぼし率の測定ではない。** 89の他ホールの分布であり、
使ってよいのは事前分布・警報としてだけである。当方ホールで同じ率が出る保証はない。

⚠️ **投稿者の選択バイアスがある。** 目立つ日を選んで書いているはずなので、
コーパスは強い日に偏る。したがって上記の取りこぼし率は **下限** と読む。

「平均差枚」のスケール（2026-09-09 に実測して解決）
--------------------------------------------------
一部の投稿は機種名の行に台番号の範囲を書く（"L戦国乙女5 (2220-2222)"）。
楽園蒲田の55件でこの範囲を `machine_detailed_results` に突き合わせたところ、
範囲幅と実在台数は全件一致し、報告値と当方の `diff_coins_normalized` 平均は

    実測 = 1.0266 × 報告 + 25.8     （n=55, 残差sd 9.2枚, 最大残差 28枚）

というほぼ決定的な関係にあった。報告値は当方より約3%低いスケールで書かれている。
`REPORTED_TO_LOCAL` でこの変換を当ててから当方の閾値と比べる。
⚠️ 変換は投稿者 `slokotae7` の記法に対する較正であって、他アカウントには当てはまらない。

画像から抽出済みの台番号（link-machines）
------------------------------------
本文の解析とは別に、投稿の画像から `extraction_entries` が台番号を抜いている。
`infer_hall.py` はそれを10ホールと突き合わせて所属を同定しようとして大半を落とすが、
**ホールと営業日は本文に書いてある**ので同定は要らない。tweet_id で結び付け、
DBは検証にだけ使う。楽園蒲田で1,024台×26日の台単位ラベルが取れた（機種名の一致68%）。

年の決定と検算
--------------
本文は「8月20日(木)」と年を書かない。投稿時刻の年を当て、投稿月より先の月が
書かれていたら前年とする。本文が曜日を書いているので、**導出した日付の曜日と
本文の曜日が一致するかを毎行検算する**。一致しない行は `weekday_ok=0` を立てて
取り込み、集計側で落とせるようにする（黙って捨てると、書式変更に気づけない）。
"""

import argparse
import os
import re
import sqlite3
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE_DB = os.path.join(ROOT, "scraper", "twitter_monitor", "state.db")
ANALYSIS_DB = os.path.join(ROOT, "db", "analysis_results.db")

# 定型の表形式で結果を書くアカウント。本文から機種×日のラベルが取れる。
RESULT_ACCOUNTS = ("slokotae7",)

# 本文は散文でホールの愛称しか名乗らず、台番号は画像にしかないアカウント。
# 機種行は取れないので `external_result_models` は作らず、`link-machines` 用に
# ホールと営業日だけを持つ報告として登録する。
#
# 999999Q9Q は「メガなな＝蒲田7」「メガいち＝蒲田1」という愛称で書く。
# `予想`（前夜の予測）と `速報`（日付が変わった直後の結果）があり、**速報だけ**が
# 結果報告である。予想を結果として取り込むと、当たっていない予測が正解ラベルになる。
PROSE_ACCOUNTS = {
    "999999Q9Q": {
        "halls": (
            (("メガなな", "メガ7", "蒲田7", "蒲田七"), "マルハンメガシティ2000-蒲田7"),
            (("メガいち", "メガ1", "蒲田1", "蒲田一"), "マルハンメガシティ2000-蒲田1"),
        ),
        "result_marker": "速報",
    },
}

WEEKDAYS = "月火水木金土日"

# 報告値を当方の diff_coins_normalized スケールへ直す係数（モジュール docstring 参照）。
# 楽園蒲田の台番号付き55件からの回帰。slokotae7 の記法に対する較正である。
REPORTED_TO_LOCAL = (1.0266, 25.8)


def to_local_scale(reported):
    slope, intercept = REPORTED_TO_LOCAL
    return slope * reported + intercept


RE_DATE = re.compile(r"^\s*(\d{1,2})月(\d{1,2})日\s*[（(]?([月火水木金土日])?")
RE_BLOCK = re.compile(r"^\s*【([^】]+)】\s*$")
# 対象台数は "34/311台(10.9%)" とも "22/587台"（楽園はパーセントを書かない）とも来る。
# パーセントを必須にしていたため、楽園の投稿は target_machines が全滅していた（2026-09-10 修正）。
RE_RATE = re.compile(r"(\d+)\s*/\s*(\d+)\s*台(?:\s*[（(]\s*([\d.]+)\s*[%％]\s*[)）])?")
RE_TARGET_MEAN = re.compile(r"対象台平均\s*([+\-−]?[\d,]+)\s*枚")
RE_HALL_TOTAL = re.compile(r"店舗総差枚\s*([+\-−]?[\d,]+)\s*枚")
RE_MEAN = re.compile(r"平均\s*([+\-−]?[\d,]+)\s*枚")
# "3/3"、"+6/8台"、"10台中5台" のいずれの書き方も来る。"6/8台" の「台」まで
# 食わないと、機種名として "台" が残って直前行への引き継ぎが働かなくなる。
RE_NOF = re.compile(r"(\d+)\s*/\s*(\d+)\s*台?|(\d+)\s*台中\s*(\d+)\s*台")
# 数値を落とした残りが単位や符号だけになった行は、機種名を持たないとみなす。
RE_NAME_JUNK = re.compile(r"^[\s　+＋\-−台枚]*$")
# 一部の行は機種名のあとに台番号の範囲を書く（"L戦国乙女5 (2220-2222)"）。
# 台番号が取れた行は、実績DBのある追跡内ホールなら台単位で突き合わせられる。
RE_NUMBERS = re.compile(r"[（(]\s*(\d{3,4})\s*[-−~〜]\s*(\d{3,4})\s*[)）]")
# ゼロ幅文字が投稿に混じる。機種名の突き合わせを壊すので取り除く。
RE_INVISIBLE = re.compile(r"[​‌‍﻿]")

SCHEMA = """
CREATE TABLE IF NOT EXISTS external_result_reports (
    report_id        TEXT PRIMARY KEY,    -- tweet_id
    source           TEXT NOT NULL,
    tweet_url        TEXT,
    posted_at        TEXT,
    hall_name        TEXT,
    business_date    TEXT,                -- YYYYMMDD
    weekday_stated   TEXT,
    weekday_ok       INTEGER,             -- 本文の曜日と導出日付が一致したか
    event_name       TEXT,
    target_machines  INTEGER,
    total_machines   INTEGER,
    target_pct       REAL,
    target_mean_diff INTEGER,
    hall_total_diff  INTEGER,
    is_tracked_hall  INTEGER NOT NULL,    -- db/ に実績DBがあるホールか
    raw_text         TEXT NOT NULL,
    ingested_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_result_models (
    report_id    TEXT NOT NULL REFERENCES external_result_reports(report_id),
    seq          INTEGER NOT NULL,
    granularity  TEXT NOT NULL,           -- 全台 / 1/2 / 3台並び ...
    model_name   TEXT NOT NULL,
    n_target     INTEGER,
    n_total      INTEGER,
    mean_diff    INTEGER,
    number_from  INTEGER,               -- 本文が台番号範囲を書いていた場合のみ
    number_to    INTEGER,
    PRIMARY KEY (report_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_erm_granularity
    ON external_result_models(granularity, mean_diff);

CREATE TABLE IF NOT EXISTS external_result_machines (
    report_id      TEXT NOT NULL REFERENCES external_result_reports(report_id),
    image_path     TEXT NOT NULL,
    machine_number INTEGER NOT NULL,
    hall_name      TEXT NOT NULL,
    business_date  TEXT NOT NULL,
    extracted_name TEXT,
    actual_name    TEXT,               -- 当日その番号に実在した機種名
    name_agrees    INTEGER,            -- 抽出名と実在名が折り合うか
    -- その台がどの粒度の仕掛けに属していたか（全台 / 3台並び / 1/2 ...）。
    -- 一意に決まらなければ NULL のままにする。推測で埋めない。
    granularity    TEXT,
    granularity_source TEXT,           -- number_range / model_name / NULL
    PRIMARY KEY (report_id, image_path, machine_number)
);

CREATE INDEX IF NOT EXISTS idx_erx_hall_date
    ON external_result_machines(hall_name, business_date);
"""


def norm_int(value):
    return int(str(value).replace(",", "").replace("−", "-").replace("+", ""))


def tracked_halls():
    """db/ に実績DBがあるホール名。追跡内/外の切り分けにだけ使う。"""
    db_dir = os.path.join(ROOT, "db")
    if not os.path.isdir(db_dir):
        return set()
    return {os.path.splitext(f)[0] for f in os.listdir(db_dir) if f.endswith(".db")}


def resolve_year(month, day, posted_at):
    """投稿時刻から年を当てる。投稿月より先の月なら前年の投稿とみなす。"""
    posted = datetime.fromisoformat(posted_at)
    year = posted.year
    if month > posted.month + 1:
        year -= 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_report(text, posted_at):
    """1投稿を (ヘッダ辞書, 機種行リスト) に分解する。日付行が無ければ None。"""
    lines = [RE_INVISIBLE.sub("", line).strip() for line in text.splitlines()]
    head_index = next((i for i, line in enumerate(lines) if RE_DATE.match(line)), None)
    if head_index is None:
        return None

    match = RE_DATE.match(lines[head_index])
    month, day, weekday = int(match.group(1)), int(match.group(2)), match.group(3)
    resolved = resolve_year(month, day, posted_at)
    if resolved is None:
        return None

    header = {
        "business_date": resolved.strftime("%Y%m%d"),
        "weekday_stated": weekday,
        "weekday_ok": None if weekday is None else int(WEEKDAYS[resolved.weekday()] == weekday),
    }

    # ホール名は日付行の次の非空行。イベント名はさらに次の非空行のうち、
    # 台数行でも粒度ブロックでもないもの。
    rest = [line for line in lines[head_index + 1 :] if line]
    if rest:
        header["hall_name"] = rest[0]
    for line in rest[1:]:
        if RE_BLOCK.match(line) or RE_RATE.search(line) or RE_TARGET_MEAN.search(line):
            break
        header["event_name"] = line
        break

    # 対象台数は粒度ブロックより前にしか出ない。全文を探すと機種行の
    # "+6/8台 平均+2,336枚" をホール全体の対象台数と取り違える。
    head_block = next((i for i, line in enumerate(lines) if RE_BLOCK.match(line)), len(lines))
    head_text = "\n".join(lines[:head_block])
    match = RE_RATE.search(head_text)
    if match:
        header["target_machines"] = int(match.group(1))
        header["total_machines"] = int(match.group(2))
        if match.group(3):
            header["target_pct"] = float(match.group(3))
    match = RE_TARGET_MEAN.search(text)
    if match:
        header["target_mean_diff"] = norm_int(match.group(1))
    match = RE_HALL_TOTAL.search(text)
    if match:
        header["hall_total_diff"] = norm_int(match.group(1))

    # 機種名と数値が同じ行に来る書式（"バイオRE3 3/3 平均+3639枚"）と、
    # 別行に分かれる書式（"バイオRE3" / "3/3　平均+3639枚"）が混在する。
    # 数値行に名前が残らなければ、直前の「数値を含まない行」を機種名として引き継ぐ。
    def split_name(line):
        """行から台番号範囲を切り出し、(機種名, 範囲 or None) を返す。"""
        found = RE_NUMBERS.search(line)
        stripped = RE_NUMBERS.sub("", RE_NOF.sub("", RE_MEAN.sub("", line)))
        stripped = stripped.strip("　 \t＋+")
        if RE_NAME_JUNK.match(stripped):
            stripped = ""
        span = (int(found.group(1)), int(found.group(2))) if found else None
        return stripped, span

    models = []
    granularity = None
    pending = (None, None)
    for line in lines:
        block = RE_BLOCK.match(line)
        if block:
            granularity = block.group(1)
            pending = (None, None)
            continue
        if not granularity or not line:
            continue
        mean = RE_MEAN.search(line)
        count = RE_NOF.search(line)
        if not (mean or count):
            # 台番号は機種名の行に書かれ、平均差枚は次の行に来ることがある
            # （"L戦国乙女5 (2220-2222)" / "平均+7547枚"）。範囲ごと持ち越す。
            pending = split_name(line)
            continue
        name, span = split_name(line)
        if not name:
            name, span = pending[0], span or pending[1]
        if not name:
            continue
        row = {"granularity": granularity, "model_name": name}
        if span:
            row["number_from"], row["number_to"] = span
        if mean:
            row["mean_diff"] = norm_int(mean.group(1))
        if count:
            groups = count.groups()
            row["n_target"] = int(groups[0] or groups[3])
            row["n_total"] = int(groups[1] or groups[2])
        models.append(row)

    return header, models


def build(state_db=STATE_DB, analysis_db=ANALYSIS_DB):
    source = sqlite3.connect("file:%s?mode=ro" % state_db, uri=True)
    target = sqlite3.connect(analysis_db)
    target.executescript(SCHEMA)
    # 既存DBに後から足した列を通す（テーブルは毎回 state.db から作り直せる派生データ）。
    existing = {row[1] for row in target.execute("PRAGMA table_info(external_result_models)")}
    for column in ("number_from", "number_to"):
        if column not in existing:
            target.execute("ALTER TABLE external_result_models ADD COLUMN %s INTEGER" % column)
    tracked = tracked_halls()
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    placeholders = ",".join("?" * len(RESULT_ACCOUNTS))
    rows = source.execute(
        "SELECT tweet_id, handle, tweet_url, posted_at_jst, "
        "COALESCE(full_text, tweet_text, '') FROM seen_tweets "
        "WHERE handle IN (%s)" % placeholders,
        RESULT_ACCOUNTS,
    ).fetchall()

    reports = models_total = skipped = mismatched = 0
    for tweet_id, handle, url, posted, text in rows:
        parsed = parse_report(text, posted)
        if parsed is None:
            skipped += 1
            continue
        header, models = parsed
        if header.get("weekday_ok") == 0:
            mismatched += 1
        target.execute(
            "INSERT OR REPLACE INTO external_result_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                tweet_id,
                handle,
                url,
                posted,
                header.get("hall_name"),
                header.get("business_date"),
                header.get("weekday_stated"),
                header.get("weekday_ok"),
                header.get("event_name"),
                header.get("target_machines"),
                header.get("total_machines"),
                header.get("target_pct"),
                header.get("target_mean_diff"),
                header.get("hall_total_diff"),
                int(header.get("hall_name") in tracked),
                text,
                now,
            ),
        )
        target.execute("DELETE FROM external_result_models WHERE report_id = ?", (tweet_id,))
        for seq, row in enumerate(models):
            target.execute(
                "INSERT INTO external_result_models "
                "(report_id, seq, granularity, model_name, n_target, n_total, "
                " mean_diff, number_from, number_to) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    tweet_id,
                    seq,
                    row["granularity"],
                    row["model_name"],
                    row.get("n_target"),
                    row.get("n_total"),
                    row.get("mean_diff"),
                    row.get("number_from"),
                    row.get("number_to"),
                ),
            )
        reports += 1
        models_total += len(models)

    target.commit()
    print("取り込み: 投稿 %d 件 / 機種行 %d 件 (日付行なしで除外 %d 件)" % (reports, models_total, skipped))
    print("曜日不一致: %d 件 (weekday_ok=0。書式変更の兆候として監視する)" % mismatched)
    tracked_count = target.execute("SELECT COUNT(*) FROM external_result_reports WHERE is_tracked_hall = 1").fetchone()[
        0
    ]
    print("うち追跡内ホール: %d 件 / 追跡外: %d 件" % (tracked_count, reports - tracked_count))
    return reports


def _prose_hall(text, halls):
    """散文の速報がどのホールの結果かを本文から決める。

    1行目（「ファンキーサトウのメガいち速報」のような見出し）に書かれたホールを最優先し、
    1行目で決まらなければ本文で最初に出てくるホールを採る。

    2026-09-28 までは別名を halls の並び順（蒲田7が先）に探して最初に見つかったホールを
    採っていたため、W来店コラボの日の「メガいち速報 … メガいち&メガなな同時来店コラボ」が
    本文中の『メガなな』で蒲田7にされ、蒲田1の画像のラベルが蒲田7の別の台に付いていた
    （6/30・7/30）。
    """
    stripped = (text or "").strip()
    first = stripped.splitlines()[0] if stripped else ""
    for scope in (first, stripped):
        best = None
        for aliases, name in halls:
            positions = [scope.find(a) for a in aliases if a in scope]
            if positions and (best is None or min(positions) < best[0]):
                best = (min(positions), name)
        if best:
            return best[1]
    return None


def ingest_prose_reports(state_db=STATE_DB, analysis_db=ANALYSIS_DB):
    """散文アカウントの結果速報を、ホールと営業日だけの報告として登録する。

    `slokotae7` は表形式なので本文から機種行まで取れるが、`999999Q9Q` は散文で、
    台番号は画像にしかない。機種行は作れないが、**ホールと営業日さえ確定すれば
    `link-machines` が画像の台番号を台単位ラベルに変えられる**。

    ホールは本文の愛称から取る（メガなな／メガいち）。`infer_hall.py` の画像照合には
    頼らない——照合は10ホールからの同定で落ちやすく、しかも画像の紐付け自体が
    壊れうる（モジュール docstring 参照）。本文が名乗っているものを使い、
    DBは `link-machines` 側の検証にだけ使う。

    営業日は `extraction_entries.business_date`（`resolve_dates.py` が解決済みのもの）を
    使う。散文には日付が書かれておらず、投稿時刻からの規則で決まっているため、
    ここで作り直さない。**同一ツイート内で営業日が割れている場合は取り込まない**
    （どちらが正しいか判断する材料がこちらに無い）。

    ⚠️ `予想`（前夜の予測）は取り込まない。予測を正解ラベルにすると、外れた予測が
    「ホールが公表した該当台」として学習・評価に混ざる。
    """
    source = sqlite3.connect("file:%s?mode=ro" % state_db, uri=True)
    target = sqlite3.connect(analysis_db)
    target.executescript(SCHEMA)
    tracked = tracked_halls()
    now = datetime.now().astimezone().isoformat(timespec="seconds")

    added = skipped_kind = skipped_hall = skipped_date = 0
    for account, spec in PROSE_ACCOUNTS.items():
        rows = source.execute(
            "SELECT tweet_id, tweet_url, posted_at_jst, COALESCE(full_text, tweet_text, '') "
            "FROM seen_tweets WHERE handle = ?",
            (account,),
        ).fetchall()
        for tweet_id, url, posted, text in rows:
            if spec["result_marker"] not in text:
                skipped_kind += 1
                continue
            hall = _prose_hall(text, spec["halls"])
            if hall is None or hall not in tracked:
                skipped_hall += 1
                continue
            dates = {
                row[0]
                for row in source.execute(
                    "SELECT DISTINCT business_date FROM extraction_entries "
                    "WHERE tweet_id = ? AND business_date IS NOT NULL",
                    (tweet_id,),
                )
            }
            if len(dates) != 1:
                skipped_date += 1
                continue
            business_date = dates.pop().replace("-", "")

            target.execute(
                "INSERT OR REPLACE INTO external_result_reports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    tweet_id,
                    account,
                    url,
                    posted,
                    hall,
                    business_date,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    1,
                    text,
                    now,
                ),
            )
            added += 1

    target.commit()
    print("散文アカウントの速報: %d 件を登録" % added)
    print(
        "  速報でないので対象外: %d / ホールを名乗っていない: %d / 営業日が定まらない: %d"
        % (skipped_kind, skipped_hall, skipped_date)
    )
    for hall, count in target.execute(
        "SELECT hall_name, COUNT(*) FROM external_result_reports "
        "WHERE source IN (%s) GROUP BY 1 ORDER BY 2 DESC" % ",".join("?" * len(PROSE_ACCOUNTS)),
        tuple(PROSE_ACCOUNTS),
    ):
        print("  %-28s %3d 件" % (hall, count))
    return added


MIN_IMAGE_NUMBERS = 3
MIN_EXIST_RATE = 0.8


def _normalize_model(value):
    value = re.sub(r"(スマスロ|パチスロ|^[LSＬＳ]\s*)", "", str(value or ""))
    return re.sub(r"[\s　・:：\-−ー！!／/（）\(\)]", "", value).lower()


def propagate_granularity(analysis_db=ANALYSIS_DB):
    """台単位ラベルに、その台が属した仕掛けの粒度（全台 / 3台並び / 1/2 …）を付ける。

    なぜ要るか
    ----------
    粒度を分けずに位置（角番・末尾）を測ると、**並びラベルの構造的な偏りを
    ホールの意図と取り違える**。同一 section 内の連続 k 台というブロックは、
    島の端（角1）を含む配置が (n-k+1) 通り中1通りしかないのに対し、中間の
    角番は多くのブロックに現れる。したがって並びラベルだけを集めると、
    ホールが何もしなくても中間の角番が過剰に出る。

    2026-09-10 の位置検証（角1が設置比23.9%に対しラベル比11.6%）は粒度を
    分けずに測っており、この偏りを含んでいる。分けて測り直すまで、あの数字は
    「並びの構造的偏り込み」として扱う。

    決め方
    ------
    1. 本文が台番号範囲を書いていれば、それが最も確か（`number_range`）
    2. 無ければ機種名で対応づける（`model_name`）。同一報告に同じ機種が
       複数の粒度で出る場合は、**粒度が一致するときだけ**採る
    3. どちらでも一意に決まらなければ NULL のままにする。推測で埋めない

    ⚠️ 散文アカウント（`ingest-prose` 由来）の報告には機種行が無いので、
    粒度は原理的に決まらない。2026-09-10 時点で台ラベル2,247行のうち1,189行
    （53%）がこれにあたる。実装の不足ではなくデータの限界である。
    """
    connection = sqlite3.connect(analysis_db)
    existing = {row[1] for row in connection.execute("PRAGMA table_info(external_result_machines)")}
    for column in ("granularity", "granularity_source"):
        if column not in existing:
            connection.execute("ALTER TABLE external_result_machines ADD COLUMN %s TEXT" % column)

    models = {}
    for report_id, granularity, name, number_from, number_to in connection.execute(
        "SELECT report_id, granularity, model_name, number_from, number_to FROM external_result_models"
    ):
        models.setdefault(report_id, []).append((granularity, _normalize_model(name), number_from, number_to))

    counts = {"number_range": 0, "model_name": 0, "unresolved": 0, "no_models": 0}
    for report_id, number, actual in connection.execute(
        "SELECT report_id, machine_number, actual_name FROM external_result_machines"
    ).fetchall():
        rows = models.get(report_id)
        if not rows:
            counts["no_models"] += 1
            continue
        spans = [r for r in rows if r[2] is not None and r[2] <= number <= r[3]]
        if len(spans) == 1:
            resolved, source = spans[0][0], "number_range"
        else:
            target = _normalize_model(actual)
            hits = [r for r in rows if r[1] and target and (r[1][:4] in target or target[:4] in r[1])]
            granularities = {r[0] for r in hits}
            if len(granularities) == 1:
                resolved, source = granularities.pop(), "model_name"
            else:
                counts["unresolved"] += 1
                continue
        counts[source] += 1
        connection.execute(
            "UPDATE external_result_machines SET granularity = ?, granularity_source = ? "
            "WHERE report_id = ? AND machine_number = ?",
            (resolved, source, report_id, number),
        )

    connection.commit()
    print("粒度を付けた台: 台番号範囲 %d / 機種名 %d" % (counts["number_range"], counts["model_name"]))
    print("  一意に決まらず未設定: %d / 報告に機種行が無い(散文由来): %d" % (counts["unresolved"], counts["no_models"]))
    for granularity, count in connection.execute(
        "SELECT COALESCE(granularity, '(不明)'), COUNT(*) FROM external_result_machines "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
    ):
        print("  %-12s %5d" % (granularity, count))
    return counts


PANEL_MAX_GAMES_GAP = 500
PANEL_MAX_BB_GAP = 15
PANEL_MAX_RB_GAP = 5


def _panel_gap(panel, row):
    """画像の数字（閉店前のスクリーンショット）と実績（閉店後に確定）の差。条件外なら None。

    実績は画像以上になる（撮影後も打たれる）。2026-09-28 の 6/2 蒲田1 の画像で、18台中8台が完全一致、
    9台は実績の方がわずかに多かった（例: 画像 BB84/RB21/5994G → 実績 BB89/RB22/6015G）。
    """
    games, bb, rb = row
    if None in (panel["games"], panel["bb"], panel["rb"]) or games is None:
        return None
    dg, db, dr = int(games) - panel["games"], (bb or 0) - panel["bb"], (rb or 0) - panel["rb"]
    if dg < 0 or db < 0 or dr < 0:
        return None
    if dg > PANEL_MAX_GAMES_GAP or db > PANEL_MAX_BB_GAP or dr > PANEL_MAX_RB_GAP:
        return None
    return dg / PANEL_MAX_GAMES_GAP + db / PANEL_MAX_BB_GAP + dr / PANEL_MAX_RB_GAP


def _load_panels(source, image_path):
    """state.db の extraction_panels から、その画像の各台の数字を読む（表が無ければ空）。"""
    try:
        rows = source.execute(
            "SELECT machine_number, machine_name, bb, rb, games FROM extraction_panels WHERE image_path = ?",
            (image_path,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(zip(("machine_number", "machine_name", "bb", "rb", "games"), r)) for r in rows]


def _match_panel(panel, day_stats):
    """台データ画面の1台を、その日の実績の台に当てる。

    返り値 (台番号, 状態)。状態は
      exact_number … 読み取った台番号の台が数字と合う（機種名の読み誤りは無視してよい）
      corrected    … 読み取った台番号では合わず、別の台が数字で1台に決まった（台番号の読み誤り・隣とのずれ）
      unverified   … 数字で決まらない（読めない・候補が複数）。読み取った台番号をそのまま使う
    """
    read = panel.get("machine_number")
    read_n = int(read) if read and str(read).isdigit() else None
    if read_n in day_stats and _panel_gap(panel, day_stats[read_n]) is not None:
        return read_n, "exact_number"
    scored = sorted((g, n) for n, row in day_stats.items() if (g := _panel_gap(panel, row)) is not None)
    if scored and (len(scored) == 1 or scored[1][0] - scored[0][0] >= 0.2):
        return scored[0][1], "corrected"
    return read_n, "unverified"


def _name_agrees(extracted, real, day_names):
    """画像から読んだ機種名が、その台番号に当日実在した機種と折り合うか（1/0）。

    略称の対応表（backtest.model_alias）でその日の機種に当てられれば、それで判定する
    （別の機種に当たれば不一致）。当てられないときだけ、以前の先頭4文字の比較に戻る。
    2026-09-28 までは先頭4文字の比較だけで、「北斗転生」「Lカバネリ」のような略称は
    正しくても不一致になっていた。
    """
    from backtest.model_alias import clean_image_name, norm, resolve

    if not extracted or not real:
        return 0
    # 画像の機種名の飾り（頭の L/、パチスロ、型式の記号 FN/AD/SC2 等）を落としてから比べる。
    cleaned = clean_image_name(str(extracted))
    # 「バラエティ」（少数台機種のコーナー）・「2台設置BT機」・「その他」などは機種名ではないので、
    # 実在機種と比べられない。一致でも不一致でもなく None（NULL）を返す（2026-09-28 ユーザー指摘）。
    probe = resolve(cleaned, [])
    if not norm(cleaned) or (probe["parts"] and all(p["status"] == "not_model" for p in probe["parts"])):
        return None
    # それが、その台番号に実在する機種名の一部（略した書き方）なら一致とみなし、DB の機種名を
    # 正とする（2026-09-28 ユーザー判断: 画像『甲鉄城のカバネリ』→実在『海門決戦』、
    # 『ソードアート・オンライン』→実在『II』は略しているだけ）。台番号はすでに DB で引いている。
    key = norm(cleaned)
    if len(key) >= 3 and key in norm(real):
        return 1
    res = resolve(cleaned, day_names)
    if not res["names"]:
        res = resolve(str(extracted), day_names)
    # 候補付きの略称（とある2・ギアス3 等）で決め切れないとき、候補の中にその台番号の実在機種が
    # あれば一致とする（台番号が決め手になる、2026-09-28 ユーザー判断）。
    if not res["names"] and any(real in u["names"] for u in res["unresolved"]):
        return 1
    if res["names"]:
        return int(real in res["names"])
    left = str(extracted).replace(" ", "").replace("　", "").lower()
    right = str(real).replace(" ", "").replace("　", "").lower()
    return int(bool(left and right and (left[:4] in right or right[:4] in left)))


def link_machines(state_db=STATE_DB, analysis_db=ANALYSIS_DB):
    """投稿の画像から抽出済みの台番号を、本文由来のホール・日付に結び付ける。

    `infer_hall.py` は画像の (台番号, 機種名) を10ホール全部と突き合わせて所属を
    **同定** しようとするため、台数の多いホールと番号体系が偶然重なるとお手上げになる
    （2026-09-09 時点で936画像中760画像が未解決、うち289は番号一致0.8以上なのに
    機種名が合わない偶然一致だった）。

    こちらは同定をしない。ホールと営業日は本文にそのまま書いてあり、曜日で検算済みである。
    DB を引くのは **検証** のためだけに使う。10択ではなく1つの仮説の真偽を見るので、
    はるかに通りやすい。

    ⚠️ **`scrape_tweets.py` が画像を別のツイートに紐付けることがある**（2026-09-09 に確認）。
    結果報告は1投稿1ホールであり、画像のOCRも正確なのに、楽園蒲田の投稿に付いた
    `2086853029756903714_1.jpg` の中身は別投稿 2085927740696609208（新！ガーデン川口安行、
    ToLOVEる 3/3 平均+3475枚）のものだった。原因は `crawl_account` が
    `articles.nth(index)` という **遅延ロケータ** をツイートIDの読み取りと画像取得の
    二度に分けて解決していることで、仮想スクロールで記事が入れ替わると別記事を掴む。
    slokotae7 の220投稿中42件（19%）で、本文の機種名と画像の機種名が一件も重ならない。

    したがって判定は投稿単位ではなく **画像単位** で行い、本文のホールの当日データに
    存在する番号の割合が MIN_EXIST_RATE 未満の画像は丸ごと捨てる。
    スクレイパーを直しても、この検証は残す価値がある。
    """
    source = sqlite3.connect("file:%s?mode=ro" % state_db, uri=True)
    target = sqlite3.connect(analysis_db)
    target.executescript(SCHEMA)

    reports = target.execute(
        "SELECT report_id, hall_name, business_date FROM external_result_reports "
        "WHERE is_tracked_hall = 1 AND business_date IS NOT NULL "
        "  AND COALESCE(weekday_ok, 1) = 1"
    ).fetchall()
    if not reports:
        print("追跡内ホールの投稿がない。先に build を実行すること。")
        return 0

    hall_dir = os.path.join(ROOT, "db")
    target.execute(
        "CREATE TABLE IF NOT EXISTS external_result_image_warnings ("
        " report_id TEXT NOT NULL, image_path TEXT NOT NULL, hall_name TEXT, business_date TEXT,"
        " other_hall TEXT, own_rate REAL, other_rate REAL, n INTEGER, checked_at TEXT,"
        " PRIMARY KEY (report_id, image_path))"
    )
    # 台番号を数字で確かめたか（2026-09-28 追加。既存DBには ALTER で足す）
    if "panel_check" not in {r[1] for r in target.execute("PRAGMA table_info(external_result_machines)")}:
        target.execute("ALTER TABLE external_result_machines ADD COLUMN panel_check TEXT")
    sibling_cache = {}
    kept = dropped_images = missing_day = warned = 0
    for report_id, hall, date in reports:
        rows = source.execute(
            "SELECT image_path, machine_number, machine_name FROM extraction_entries WHERE tweet_id = ?", (report_id,)
        ).fetchall()
        if not rows:
            continue
        hall_db = os.path.join(hall_dir, hall + ".db")
        if not os.path.exists(hall_db):
            continue
        connection = sqlite3.connect("file:%s?mode=ro" % hall_db, uri=True)
        actual = dict(
            connection.execute(
                "SELECT machine_number, machine_name FROM machine_detailed_results WHERE date = ?", (date,)
            ).fetchall()
        )
        # 台データ画面の数字（回転数・BB・RB）と照合するための実績
        try:
            day_stats = {
                n: (g, bb, rb)
                for n, g, bb, rb in connection.execute(
                    "SELECT machine_number, games_normalized, bb_count, rb_count FROM machine_detailed_results "
                    "WHERE date = ?",
                    (date,),
                ).fetchall()
            }
        except sqlite3.OperationalError:
            day_stats = {}  # 回転数等の列が無いDB（テスト用の最小構成など）では数字の照合をしない
        connection.close()
        if not actual:
            # 本文は営業日を書いているのに実績DBにその日が無い。取り込みの穴なので
            # 黙って捨てず数える。
            missing_day += 1
            continue

        # この報告の台単位ラベルは毎回作り直す。主キーにホールを含まないので、報告のホールを
        # 付け替えたとき（2026-09-28、メガいち速報を蒲田7から蒲田1へ）や、画像が後から
        # 捨てられるようになったときに、古い行が残らないようにする。粒度は直後の
        # propagate_granularity が埋め直す。
        target.execute("DELETE FROM external_result_machines WHERE report_id = ?", (report_id,))
        target.execute("DELETE FROM external_result_image_warnings WHERE report_id = ?", (report_id,))
        by_image = {}
        for image_path, number, name in rows:
            text = str(number).strip()
            if not text.isdigit():
                continue
            by_image.setdefault(image_path or "", []).append((int(text), name))

        # 台データ画面の数字が読めている画像は、台番号を数字（回転数・BB・RB）で決め直す
        # （2026-09-28 ユーザー提案: 画質が荒く機種名・台番号の読み誤りがあるが、数字で照合すれば当たる）。
        panel_check = {}
        for image_path in list(by_image):
            panels = _load_panels(source, image_path)
            if not panels:
                continue
            fixed = []
            for panel in panels:
                number, status = _match_panel(panel, day_stats)
                if number is None:
                    continue
                fixed.append((number, panel.get("machine_name")))
                panel_check[(image_path, number)] = status
            if fixed:
                by_image[image_path] = fixed

        for image_path, entries in by_image.items():
            if len(entries) < MIN_IMAGE_NUMBERS:
                continue
            present = [e for e in entries if e[0] in actual]
            if len(present) / len(entries) < MIN_EXIST_RATE:
                dropped_images += 1
                continue
            day_names = sorted(set(actual.values()))
            warning = _sibling_hall_warning(hall, date, present, actual, hall_dir, sibling_cache)
            if warning:
                warned += 1
                target.execute(
                    "INSERT OR REPLACE INTO external_result_image_warnings "
                    "(report_id, image_path, hall_name, business_date, other_hall, own_rate, other_rate, n, checked_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        report_id,
                        image_path,
                        hall,
                        date,
                        warning["other_hall"],
                        warning["own_rate"],
                        warning["other_rate"],
                        warning["n"],
                        datetime.now().astimezone().isoformat(timespec="seconds"),
                    ),
                )
                print(
                    "  [警告] %s %s の画像 %s は %s の方がよく合う（自店 %.0f%% / %s %.0f%%、%d台）"
                    % (
                        hall,
                        date,
                        os.path.basename(image_path),
                        warning["other_hall"],
                        100 * warning["own_rate"],
                        warning["other_hall"],
                        100 * warning["other_rate"],
                        warning["n"],
                    )
                )
            for number, name in present:
                real = actual[number]
                agrees = _name_agrees(name, real, day_names)
                # 列名を明示する。位置指定にすると、粒度の列を足したときに黙って壊れる
                # （2026-09-10 に実際に壊した）。
                target.execute(
                    "INSERT OR REPLACE INTO external_result_machines "
                    "(report_id, image_path, machine_number, hall_name, business_date, "
                    " extracted_name, actual_name, name_agrees, panel_check) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        report_id,
                        image_path,
                        number,
                        hall,
                        date,
                        name,
                        real,
                        agrees,
                        panel_check.get((image_path, number)),
                    ),
                )
                kept += 1

    target.commit()
    print("台単位ラベル: %d 行を確定" % kept)
    print("  ホール違いとして捨てた画像: %d" % dropped_images)
    print("  もう一方の店の方がよく合う画像（警告のみ・付け替えない）: %d" % warned)
    print("  本文の営業日が実績DBに無い投稿: %d" % missing_day)
    # 一致率は比べられる行（name_agrees が NULL でない＝機種名が書かれている行）だけで出す。
    for hall, count, comparable, agree in target.execute(
        "SELECT hall_name, COUNT(*), COUNT(name_agrees), SUM(name_agrees) FROM external_result_machines "
        "GROUP BY hall_name ORDER BY 2 DESC"
    ):
        print(
            "  %-24s %5d 行 (機種名も一致 %.0f%%、コーナー名等で比べられない %d 行)"
            % (hall, count, 100 * (agree or 0) / comparable if comparable else 0, count - comparable)
        )
    return kept


# 同じ投稿者が両方を書くホールの組。画像がもう一方の店のものでないかを確かめる相手。
SIBLING_HALLS = {
    "マルハンメガシティ2000-蒲田7": "マルハンメガシティ2000-蒲田1",
    "マルハンメガシティ2000-蒲田1": "マルハンメガシティ2000-蒲田7",
}


def _sibling_hall_warning(hall, date, present, actual, hall_dir, cache):
    """画像の(台番号, 機種名)が、自店よりもう一方の店の実績によく合うなら警告を返す（付け替えはしない）。

    2026-09-28 に、W来店コラボの日の蒲田1の画像が蒲田7の結果として取り込まれていた。
    本文の見出しでホールを決めるよう直したが、本文にホールが書かれていない投稿や、画像と投稿の
    紐付けのずれは本文では防げないので、画像単位でも確かめる。2店は台番号が一部重なるので、
    自動で付け替えると逆に誤りうる。警告だけにする。
    """
    other = SIBLING_HALLS.get(hall)
    if not other:
        return None
    key = (other, date)
    if key not in cache:
        path = os.path.join(hall_dir, other + ".db")
        rows = {}
        if os.path.exists(path) and os.path.getsize(path) > 0:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            rows = dict(
                con.execute(
                    "SELECT machine_number, machine_name FROM machine_detailed_results WHERE date = ?", (date,)
                ).fetchall()
            )
            con.close()
        cache[key] = rows
    other_actual = cache[key]
    if not other_actual:
        return None
    own_names = sorted(set(actual.values()))
    other_names = sorted(set(other_actual.values()))
    own = [_name_agrees(name, actual[n], own_names) for n, name in present]
    oth = [_name_agrees(name, other_actual[n], other_names) for n, name in present if n in other_actual]
    own = [x for x in own if x is not None]
    oth = [x for x in oth if x is not None]
    if len(own) < MIN_IMAGE_NUMBERS or len(oth) < MIN_IMAGE_NUMBERS:
        return None
    own_rate, other_rate = sum(own) / len(own), sum(oth) / len(oth)
    if other_rate >= 0.8 and own_rate <= 0.5:
        return {"other_hall": other, "own_rate": own_rate, "other_rate": other_rate, "n": len(own)}
    return None


def quantiles(values, points=(0.05, 0.10, 0.25, 0.50, 0.75, 0.90)):
    ordered = sorted(values)
    return [ordered[min(int(len(ordered) * p), len(ordered) - 1)] for p in points]


def stats(analysis_db=ANALYSIS_DB, threshold=1800.0):
    connection = sqlite3.connect("file:%s?mode=ro" % analysis_db, uri=True)
    rows = connection.execute(
        "SELECT m.granularity, m.mean_diff FROM external_result_models m "
        "JOIN external_result_reports r ON r.report_id = m.report_id "
        "WHERE m.mean_diff IS NOT NULL AND COALESCE(r.weekday_ok, 1) = 1"
    ).fetchall()
    if not rows:
        print("データがない。先に build を実行すること。")
        return

    # 以降の差枚はすべて当方の diff_coins_normalized スケールに直してから扱う。
    by_granularity = {}
    for granularity, mean_diff in rows:
        by_granularity.setdefault(granularity, []).append(to_local_scale(mean_diff))

    print("=== 粒度別 機種平均差枚（当方スケールへ変換済み） ===")
    print("%-12s%5s%8s%8s%8s%8s" % ("粒度", "n", "p10", "p25", "中央", "p75"))
    for granularity, values in sorted(by_granularity.items(), key=lambda kv: -len(kv[1])):
        if len(values) < 8:
            continue
        _, p10, p25, p50, p75, _ = quantiles(values)
        print("%-12s%5d%8.0f%8.0f%8.0f%8.0f" % (granularity, len(values), p10, p25, p50, p75))

    everything = [value for values in by_granularity.values() for value in values]
    labels = ("p05", "p10", "p25", "p50", "p75", "p90")
    print("\n=== 全粒度 n=%d ===" % len(everything))
    print("  " + "  ".join("%s=%+.0f" % (label, value) for label, value in zip(labels, quantiles(everything))))

    print("\n=== 閾値 score=G比×平均差枚 >= %.0f の取りこぼし率 ===" % threshold)
    print("（当方ホールの実測ではない。事前分布として読む。選択バイアスにより下限）")
    print("%6s%14s%12s" % ("G比", "必要平均差枚", "取りこぼし"))
    for ratio in (1.0, 1.2, 1.4, 1.6, 2.0, 2.5):
        needed = threshold / ratio
        missed = sum(1 for value in everything if value < needed) / len(everything)
        print("%6.1f%14.0f%11.1f%%" % (ratio, needed, missed * 100))

    print("\n=== 粒度の事前分布（投稿数ベース） ===")
    blocks = connection.execute(
        "SELECT granularity, COUNT(DISTINCT report_id) FROM external_result_models GROUP BY granularity ORDER BY 2 DESC"
    ).fetchall()
    for granularity, count in blocks[:12]:
        print("  %-10s %3d 投稿" % (granularity, count))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="state.db から解析して analysis_results.db へ取り込む")
    sub.add_parser("ingest-prose", help="散文アカウントの速報をホール・営業日つきで登録する")
    sub.add_parser("link-machines", help="画像抽出の台番号を本文のホール・日付に結び付ける")
    sub.add_parser("propagate-granularity", help="台単位ラベルに仕掛けの粒度を付ける")
    stats_parser = sub.add_parser("stats", help="較正用の分布を表示する")
    stats_parser.add_argument("--threshold", type=float, default=1800.0)
    args = parser.parse_args()

    if args.command == "build":
        build()
    elif args.command == "ingest-prose":
        ingest_prose_reports()
    elif args.command == "link-machines":
        link_machines()
        propagate_granularity()
    elif args.command == "propagate-granularity":
        propagate_granularity()
    else:
        stats(threshold=args.threshold)


if __name__ == "__main__":
    main()
