# -*- coding: utf-8 -*-
"""ボーナス確率で設定を判別できる機種のスペックと、実戦用の事後確率。

スペックはどこから来るか
------------------------
`document/machine_master_research/machine_master.csv`（一撃 1geki.jp からの収集、330機種）。
**手で転記しない。** ここから直接読む。列は

    game_type          AT / ノーマル / A+AT / A+ART / ART / A+RT
    bt_flag            ボーナストリガー機か
    bb_setting1..6     "1/185.1" 形式のBB確率
    rb_setting1..6     同 RB確率
    rtp_setting1..6    設定別の機械割
    bonus_combined_setting1..6  BB/RB個別が無い機種の合算確率

ホールDBの機種名との名寄せは、接頭辞（L/S/スマスロ/パチスロ）と記号を落とせば
現行142機種中140件（99%）が一致する。残る2件はリネーム（タコスロ／モグモグ風林火山）で、
マスター側は旧名（LBタコスロ／天晴!モグモグ風林火山）を持っている。

ART と BT を分ける
------------------
ホールDBの `machine_master` は `bt_flag` しか持たず、**ART と BT が長らく同居していた**。
一撃マスターは `game_type` と `bt_flag` を別に持つので、ここで分離する。

| category | 条件 | 例 |
|---|---|---|
| ノーマル | game_type=ノーマル かつ bt_flag=0 | ジャグラー、キングハナハナ |
| BT | bt_flag=1 | ニューパルサーBT、LBタコスロ、クレアの秘宝伝BT |
| A+AT | game_type が A+AT / A+ART / A+RT | ディスクアップ、エウレカART、うみねこ2 |
| AT | game_type=AT | 沖ドキ、北斗 |
| ART | game_type=ART | |

**ボーナス確率で設定を判別できるのは ノーマル・BT・A+AT の3つ**（AT機はボーナス自体が
AT当選契機で、設定差が別の形に出る）。`judgeable` はこの区別で決める。

⚠️ ジャグラー系は `ml/experiments/jug_rb_setting_prediction/config.py` の値を優先する。
2026-07-06 にユーザー提供の実機解析値で修正済みで、一撃の値より確かなため。

実戦での使い方
--------------
    python backtest/bonus_specs.py judge "マイジャグラーV" --games 3200 --bb 8 --rb 5
    python backtest/bonus_specs.py coverage

⚠️ **単一の最尤設定だけを見ないこと。** 合成試行では 8,000G 回しても最尤設定が真の設定に
一致するのは3〜4割（6択の偶然は16.7%）。幅で読む。
⚠️ 2,000G 未満は誤警報が2〜3割。それ未満は「まだ分からない」と出す。
"""

import argparse
import csv
import importlib.util
import math
import os
import re
import sqlite3
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB_DIR = os.path.join(ROOT, "db")
MASTER_CSV = os.path.join(ROOT, "document", "machine_master_research", "machine_master.csv")
LEGACY_SPEC_PATH = os.path.join(ROOT, "ml", "experiments", "jug_rb_setting_prediction", "config.py")

MIN_GAMES_FOR_JUDGEMENT = 2000
# ボーナス確率で設定を判別できるカテゴリ
JUDGEABLE_CATEGORIES = ("ノーマル", "BT", "A+AT")

RE_PREFIX = re.compile(r"^(LB|L|S|スマスロ|パチスロ)\s*")
RE_SYMBOL = re.compile(r"[\s　・:：\-−ー！!／/（）\(\)‐～~。、]")
RE_FRACTION = re.compile(r"1\s*/\s*([\d,.]+)")


def normalize(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    return RE_SYMBOL.sub("", RE_PREFIX.sub("", value)).casefold()


def parse_probability(text):
    """ "1/185.1" を 0.0054 にする。読めなければ None。"""
    match = RE_FRACTION.search(str(text or ""))
    if not match:
        return None
    try:
        denominator = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return 1 / denominator if denominator > 0 else None


def categorize(game_type, bt_flag):
    if str(bt_flag) in ("1", "1.0", "True"):
        return "BT"
    game_type = str(game_type or "").strip()
    if game_type == "ノーマル":
        return "ノーマル"
    if game_type in ("A+AT", "A+ART", "A+RT"):
        return "A+AT"
    if game_type == "ART":
        return "ART"
    return "AT"


def _legacy_specs():
    spec = importlib.util.spec_from_file_location("_legacy_spec", LEGACY_SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, "JUGGLER_FAMILY_SPECS", {}))


def load_specs(master_csv=MASTER_CSV):
    """{正規化名: spec} を返す。一撃マスターが基盤、ジャグラーは既存値で上書き。"""
    specs = {}
    with open(master_csv, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = row.get("canonical_machine_name") or row.get("machine_name")
            if not name:
                continue
            key = normalize(name)
            settings = {}
            for setting in range(1, 7):
                bb = parse_probability(row.get("bb_setting%d" % setting))
                rb = parse_probability(row.get("rb_setting%d" % setting))
                combined = parse_probability(row.get("bonus_combined_setting%d" % setting))
                try:
                    payout = float(row.get("rtp_setting%d" % setting) or "nan")
                except ValueError:
                    payout = float("nan")
                if bb or rb or combined:
                    settings[setting] = {
                        "bb_probability": bb,
                        "rb_probability": rb,
                        "combined_probability": combined,
                        "payout_rate": payout,
                    }
            category = categorize(row.get("game_type"), row.get("bt_flag"))
            # 設定間で確率が動かない機種は、当たり回数から設定を分けられない
            varies = (
                len({(v["bb_probability"], v["rb_probability"], v["combined_probability"]) for v in settings.values()})
                > 1
            )
            specs[key] = {
                "family_name": name,
                "category": category,
                "game_type": row.get("game_type"),
                "settings": settings,
                "judgeable": bool(settings) and varies and category in JUDGEABLE_CATEGORIES,
                "source": "1geki",
            }

    for entry in _legacy_specs().values():
        key = normalize(entry.get("machine_keyword") or entry.get("family_name"))
        settings = {}
        for setting, values in entry["settings"].items():
            settings[int(setting)] = {
                "bb_probability": values.get("bb_probability"),
                "rb_probability": values.get("rb_probability"),
                "combined_probability": None,
                "payout_rate": values.get("payout_rate", float("nan")),
            }
        previous = specs.get(key, {})
        specs[key] = {
            "family_name": entry.get("family_name"),
            "category": previous.get("category", "ノーマル"),
            "game_type": previous.get("game_type"),
            "settings": settings,
            "judgeable": True,
            "source": entry.get("source", "実機解析値(2026-07-06)"),
        }
    return specs


def find_spec(machine_name, specs=None):
    """機種名から spec を引く。完全一致 → 長い部分一致の順。"""
    specs = specs or load_specs()
    target = normalize(machine_name)
    if target in specs:
        return specs[target]
    best = None
    for key, spec in specs.items():
        if len(key) >= 4 and (key in target or target in key):
            if best is None or len(key) > len(normalize(best["family_name"])):
                best = spec
    return best


def _log_binomial(k, n, p):
    if not p or p <= 0 or p >= 1 or k is None or k < 0 or k > n:
        return None
    return k * math.log(p) + (n - k) * math.log1p(-p)


def posterior(spec, games, bb, rb):
    """設定ごとの事後確率。事前は一様。

    BB/RB が個別にあれば独立な二項として扱う（確率が小さいので多項との差は無視できる）。
    合算しか無い機種は BB+RB の合計を1つの二項として扱う。
    """
    scores = {}
    for setting, values in spec["settings"].items():
        total, used = 0.0, 0
        for count, key in ((bb, "bb_probability"), (rb, "rb_probability")):
            term = _log_binomial(count, games, values.get(key))
            if term is not None:
                total += term
                used += 1
        if not used and values.get("combined_probability") is not None:
            term = _log_binomial((bb or 0) + (rb or 0), games, values["combined_probability"])
            if term is None:
                continue
            total, used = term, 1
        if used:
            scores[setting] = total
    if not scores:
        return {}
    top = max(scores.values())
    weights = {s: math.exp(v - top) for s, v in scores.items()}
    total = sum(weights.values())
    return {s: w / total for s, w in sorted(weights.items())}


def judge(machine_name, games, bb, rb):
    specs = load_specs()
    spec = find_spec(machine_name, specs)
    if spec is None:
        print("「%s」は一撃マスターに無い。判定できない。" % machine_name)
        return None
    if not spec["judgeable"]:
        print("%s（%s）は**ボーナス確率で設定を判別できない**。" % (spec["family_name"], spec["category"]))
        print(
            "  判別できるのは %s のみ。AT機はボーナスがAT当選契機で、設定差が別の形に出る。"
            % " / ".join(JUDGEABLE_CATEGORIES)
        )
        return None

    probs = posterior(spec, games, bb, rb)
    if not probs:
        print("%s: 設定別のボーナス確率が埋まっていない。" % spec["family_name"])
        return None

    print(
        "%s（%s・%s / 出典 %s）  %dG  BB%d RB%d  合算1/%.1f"
        % (
            spec["family_name"],
            spec["category"],
            spec.get("game_type") or "-",
            spec["source"],
            games,
            bb,
            rb,
            games / max(1, bb + rb),
        )
    )
    print("%6s%10s%10s   %s" % ("設定", "事後確率", "想定出率", "この設定なら"))
    for setting, probability in probs.items():
        values = spec["settings"][setting]
        parts = []
        for label, key in (("BB", "bb_probability"), ("RB", "rb_probability"), ("合算", "combined_probability")):
            if values.get(key):
                parts.append("%s1/%.0f" % (label, 1 / values[key]))
        print(
            "%6d%9.1f%%%9.1f%%   %-24s%s"
            % (
                setting,
                100 * probability,
                values.get("payout_rate", float("nan")),
                " ".join(parts),
                "#" * int(round(probability * 36)),
            )
        )

    high = sum(p for s, p in probs.items() if s >= 5)
    mid = probs.get(4, 0.0)
    print("\n  設定5以上 %.1f%% / 設定4 %.1f%% / 設定1-3 %.1f%%" % (100 * high, 100 * mid, 100 * (1 - high - mid)))
    if games < MIN_GAMES_FOR_JUDGEMENT:
        print(
            "  ⚠️ %dG は判定に足りない（%dG未満は誤警報が2〜3割）。まだ判断しない。" % (games, MIN_GAMES_FOR_JUDGEMENT)
        )
    elif high >= 0.5:
        print("  → 続行。設定5以上が優勢。")
    elif high + mid >= 0.5:
        print("  → 続行寄り。ただし設定4止まりの可能性が高い。")
    else:
        print("  → 撤退を検討。設定1-3が優勢。")
    print("\n  ⚠️ 最尤設定だけを信じない。8,000G回しても的中は3〜4割（6択の偶然は16.7%）。")
    return probs


def coverage(halls=None):
    """現行設置機種を、判別可否とカテゴリ別に台数順で出す。"""
    specs = load_specs()
    names = halls or [
        os.path.splitext(f)[0] for f in sorted(os.listdir(DB_DIR)) if f.endswith(".db") and "analysis" not in f
    ]
    counts = {}
    for hall in names:
        try:
            connection = sqlite3.connect("file:%s?mode=ro" % os.path.join(DB_DIR, hall + ".db"), uri=True)
            rows = connection.execute(
                "SELECT machine_name, COUNT(DISTINCT machine_number) "
                "FROM machine_detailed_results "
                "WHERE date = (SELECT MAX(date) FROM machine_detailed_results) "
                "GROUP BY 1"
            ).fetchall()
        except sqlite3.Error:
            continue
        for name, count in rows:
            counts[name] = counts.get(name, 0) + count

    buckets = {}
    for name, count in counts.items():
        spec = find_spec(name, specs)
        if spec is None:
            key = "マスターに無い"
        elif spec["judgeable"]:
            key = "判別可（%s）" % spec["category"]
        else:
            key = "判別不可（%s）" % spec["category"]
        buckets.setdefault(key, []).append((count, name))

    total = sum(counts.values())
    print("現行設置 %d台 / %d機種（全ホール最新日）\n" % (total, len(counts)))
    for key in sorted(buckets, key=lambda k: -sum(c for c, _ in buckets[k])):
        rows = sorted(buckets[key], reverse=True)
        share = sum(c for c, _ in rows)
        print("■ %s  %d台 (%.0f%%) / %d機種" % (key, share, 100 * share / total, len(rows)))
        if key.startswith("判別可"):
            continue
        for count, name in rows[:8]:
            print("     %-38s%4d台" % (str(name)[:38], count))
    print("\n※ 判別できるのは %s。AT機はボーナスがAT当選契機なので対象外。" % " / ".join(JUDGEABLE_CATEGORIES))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    j = sub.add_parser("judge", help="打っている台の設定事後確率を出す")
    j.add_argument("machine_name")
    j.add_argument("--games", type=int, required=True)
    j.add_argument("--bb", type=int, required=True)
    j.add_argument("--rb", type=int, required=True)
    sub.add_parser("coverage", help="判別可否をカテゴリ別に見る")
    args = parser.parse_args()

    if args.command == "judge":
        judge(args.machine_name, args.games, args.bb, args.rb)
    else:
        coverage()


if __name__ == "__main__":
    main()
