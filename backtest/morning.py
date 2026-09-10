# -*- coding: utf-8 -*-
"""朝、店に入る前に見る「今日の材料」を1枚にまとめる。

何をしないか
------------
**座る台の予測はしない。** 抽選番号から座れる台を読むのは現場の有機的な判断で、
ユーザーの持ち場。ここが出すのは「今日どの機種を見るか」「座った後どう判定するか」
の材料だけ。

各項目の根拠（2026-09-11 実測）
-------------------------------
【2】増台 — `model_inventory` の change_kind='increase'（既存機種の台数増）に限る。
  同じ改装日に触られていない機種を対照にしたイベントスタディ（10ホール、n=160）:

      事前30日  +0.53pp / 当日〜7日 +2.45pp / 8〜30日 +0.41pp
      差分の差 +1.90pp、改装日クラスタbootstrap 95% [+1.23, +2.64]

  3点が確認できている。
    - 改装日はホール全体で出す日ではない（全台平均で見て全体 -0.10pp、9ホール中7が負）。
      よって上乗せは「改装日効果」の言い換えではない。
    - 増台機種がもともと強いわけでもない（事前30日 +0.53pp）。
    - **効果は7日で消える**（8〜30日 +0.41pp）。なので窓を7日に切る。

  ⚠️ **新台（change_kind='new'）は別物で、当日〜7日でも +0.53pp しかなく、
  8〜30日は -0.46pp と沈む。** 増台と混ぜると効果が薄まるので分けてある。
  なお新台は設定不問で高回転するため、回転数系の分析からは従来どおり除外すること。

  効き幅の目安: +2.45pp × 4,000G × 3枚 ≈ +294枚 ≈ +5,900円/日。ただしこれは
  機種平均であって、その機種の中のどの台に座るかは別問題。

【3】判別可能機種 — `spec_category` が ノーマル / BT / A+AT のもの。現行設置の
  約36%しかない。AT機はボーナス確率で設定を割れないので、やめどきの判断材料にならない。

使い方
------
    venv/Scripts/python.exe -X utf8 -m backtest.morning "楽園蒲田店"
    venv/Scripts/python.exe -X utf8 -m backtest.morning "楽園蒲田店" --date 20260910
"""

import argparse
import io
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from backtest.integrated import ANALYSIS_DB, machine_frame  # noqa: E402,F401

WEEKDAYS = "月火水木金土日"
INCREASE_WINDOW_DAYS = 7  # 効果が消える日数。事前30日と8〜30日はどちらもほぼゼロ
MIN_DELTA = 3  # これ未満の増減は入替の端数と区別がつかない

# 「直近7日の増台機種を1つ選ぶ」を過去日で回したときの、その日のホール機種平均との差。
# 2026-09-11 時点の凍結値。全体は +1.83pp（n=725, 勝率56%, bootstrap 95% [+1.17,+2.53]）
# だが、**ホール差が大きく共通の数値として使えない**ので店ごとに出す。
# 対照ルールの成績: 新台 +1.14pp / 前日の最強機種 +1.10pp（ただし中央値 -4.74pp・勝率41%
# で、少数の万枚台が平均を作っているだけ）/ 無作為 -0.06pp。
HALL_INCREASE_EDGE = {
    "レイトギャップ平和島": (+4.31, 70, 128),
    "みとや大森町店": (+4.65, 69, 49),
    "ヒロキ東口店": (+4.03, 59, 32),
    "楽園蒲田店": (+1.32, 60, 231),
    "マルハンメガシティ2000-蒲田1": (+1.05, 44, 64),
    "金時京急蒲田店": (+0.59, 57, 7),
    "マルハンメガシティ2000-蒲田7": (+0.46, 44, 115),
    "ARROW池上店": (+0.07, 47, 58),
    "ザ-シティ-ベルシティ雑色店": (-0.30, 41, 41),
}


def _ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def _shift(date, days):
    return (datetime.strptime(date, "%Y%m%d") + timedelta(days=days)).strftime("%Y%m%d")


def announcements(analysis, hall, date):
    return analysis.execute(
        "SELECT c.claim_type, c.machine_name, c.n_models, c.ratio, c.field, c.values_json, c.note "
        "  FROM announce_claims c JOIN announce_reports r ON r.announce_id = c.announce_id "
        " WHERE r.hall_name = ? AND r.target_date = ? AND COALESCE(r.retroactive, 0) = 0 "
        " ORDER BY c.seq",
        (hall, date),
    ).fetchall()


def recent_increases(analysis, hall, date, window=INCREASE_WINDOW_DAYS):
    """効果が生きている窓（当日を1日目として window 日）に入る増台だけを返す。"""
    since = _shift(date, -(window - 1))
    return analysis.execute(
        "SELECT date, machine_name, n_machines, delta FROM model_inventory "
        " WHERE hall_name = ? AND date <= ? AND date >= ? "
        "   AND change_kind = 'increase' AND delta >= ? "
        " ORDER BY date DESC, delta DESC",
        (hall, date, since, MIN_DELTA),
    ).fetchall()


def fading_increases(analysis, hall, date, window=INCREASE_WINDOW_DAYS):
    """窓を過ぎた増台。効果は消えているので「もう追わない」ことを示すために出す。"""
    lo = _shift(date, -30)
    hi = _shift(date, -window)
    return analysis.execute(
        "SELECT date, machine_name, delta FROM model_inventory "
        " WHERE hall_name = ? AND date <= ? AND date >= ? "
        "   AND change_kind = 'increase' AND delta >= ? "
        " ORDER BY date DESC",
        (hall, hi, lo, MIN_DELTA),
    ).fetchall()


def new_models(analysis, hall, date, window=INCREASE_WINDOW_DAYS):
    since = _shift(date, -(window - 1))
    return analysis.execute(
        "SELECT date, machine_name, n_machines FROM model_inventory "
        " WHERE hall_name = ? AND date <= ? AND date >= ? "
        "   AND change_kind = 'new' AND delta >= ? "
        " ORDER BY date DESC",
        (hall, date, since, MIN_DELTA),
    ).fetchall()


def judgeable_models(hall, date, analysis_db=ANALYSIS_DB):
    """直近の設置実績がある機種のうち、ボーナス確率で設定を絞れるものを台数順に返す。"""
    path = os.path.join(ROOT, "db", hall + ".db")
    if not os.path.exists(path):
        return None
    with _ro(path) as hall_db:
        category = dict(
            hall_db.execute(
                "SELECT machine_name_normalized, spec_category FROM machine_master WHERE bonus_judgeable = 1"
            ).fetchall()
        )
        last = hall_db.execute("SELECT MAX(date) FROM machine_detailed_results WHERE date < ?", (date,)).fetchone()[0]
        if not last:
            return None
        rows = hall_db.execute(
            "SELECT machine_name, COUNT(DISTINCT machine_number) FROM machine_detailed_results "
            " WHERE date = ? GROUP BY machine_name",
            (last,),
        ).fetchall()
    models = [(name, n, category[name]) for name, n in rows if name in category]
    models.sort(key=lambda row: -row[1])
    return last, models


def baserate(analysis, hall, date):
    row = analysis.execute(
        "SELECT payload_json FROM announce_reports "
        " WHERE hall_name = ? AND target_date = ? AND COALESCE(retroactive, 0) = 0",
        (hall, date),
    ).fetchone()
    if not row:
        return None
    return (json.loads(row[0]) or {}).get("baserate_before_target") or {}


def sheet(hall, date, analysis_db=ANALYSIS_DB):
    analysis = _ro(analysis_db)
    weekday = WEEKDAYS[datetime.strptime(date, "%Y%m%d").weekday()]
    print("=" * 72)
    print("  %s  %s（%s）" % (hall, date, weekday))
    print("=" * 72)

    print("\n【1】今日の予告（事前登録済みのみ。遡及登録は出さない）")
    rows = announcements(analysis, hall, date)
    for kind, name, n_models, ratio, field, values, note in rows:
        detail = name or (("%d機種" % n_models) if n_models else "")
        if field:
            detail = "%s = %s" % (field, values)
        if ratio:
            detail += "（比率 %s）" % ratio
        print("   ・%-20s %s" % (kind, detail))
        if note:
            print("       %s" % note)
    if not rows:
        print("   （なし。予告が無い日は【2】【3】で組み立てる）")

    print("\n【2】直近%d日の増台（効果が生きている窓）" % INCREASE_WINDOW_DAYS)
    hot = recent_increases(analysis, hall, date)
    for day, name, n_machines, delta in hot:
        age = (datetime.strptime(date, "%Y%m%d") - datetime.strptime(day, "%Y%m%d")).days
        print("   %-28s %2d台 (%+d)  %s  経過%d日" % (str(name)[:28], n_machines, delta, day, age))
    if not hot:
        print("   （なし）")
    edge = HALL_INCREASE_EDGE.get(hall)
    if edge is None:
        print("   → このホールは実測が無い。全体は +1.83pp だがホール差が大きいので当てにしない")
    elif edge[0] >= 1.0 and edge[1] >= 55:
        print("   → %s の実測 %+.2f pp・勝率%d%%（n=%d）。このホールでは効く" % (hall, edge[0], edge[1], edge[2]))
    else:
        print(
            "   → ⚠️ %s の実測は %+.2f pp・勝率%d%%（n=%d）。**このホールでは効かない**。"
            "増台を根拠に選ばないこと" % (hall, edge[0], edge[1], edge[2])
        )
    print("      （全ホール平均 +1.83pp [+1.17,+2.53], n=725。8日目以降は消えるので窓は7日）")

    cold = fading_increases(analysis, hall, date)
    if cold:
        print("\n   ── 窓を過ぎた増台（もう追わない）")
        for day, name, delta in cold[:6]:
            print("      %-28s (%+d)  %s" % (str(name)[:28], delta, day))

    fresh = new_models(analysis, hall, date)
    if fresh:
        print("\n   ── 新台（増台とは別物。上乗せ +0.53pp どまり、8日以降は負）")
        for day, name, n_machines in fresh:
            print("      %-28s %2d台  %s" % (str(name)[:28], n_machines, day))

    print("\n【3】打ちながら設定を絞れる機種（ノーマル / BT / A+AT）")
    result = judgeable_models(hall, date, analysis_db)
    if result:
        last, models = result
        for name, n_machines, category in models[:10]:
            print("   %-28s %2d台  [%s]" % (str(name)[:28], n_machines, category))
        print("   （設置は %s 時点）" % last)
        print("   → 座ったら 2,000G 以降に backtest/bonus_specs.py judge。AT機は判定対象外")
    else:
        print("   （spec_category 未整備。database/migrate_machine_master_categories.py --apply）")

    print("\n【4】ベースレート（予告登録時に凍結した値）")
    base = baserate(analysis, hall, date)
    if base:
        over = base.get("models_over_threshold_per_day") or {}
        print(
            "   候補機種/日 %.1f   閾値超え %.2f 機種/日"
            % (base.get("candidate_models_per_day", 0), over.get("mean", 0))
        )
        print(
            "   P(1機種以上)=%.3f  P(2以上)=%.3f  P(3以上)=%.3f"
            % (base.get("p_at_least_1", 0), base.get("p_at_least_2", 0), base.get("p_at_least_3", 0))
        )
        print("   ⚠️ 閾値+1800は取りこぼしが32〜36%あるので、超えなかった＝仕掛け無しではない")
    else:
        print("   （この日の事前登録予告が無いのでベースレートも無い）")
    analysis.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hall")
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--analysis-db", default=ANALYSIS_DB)
    args = parser.parse_args()
    sheet(args.hall, args.date, args.analysis_db)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    main()
