# -*- coding: utf-8 -*-
"""現場の報告（演出での設定確認・現地組の報告）を台帳に残す。

なぜ要るか
----------
差枚や RB 確率は設定の推定でしかなく、実際に打った人が演出で「設定5以上」を
確認した台は、数値がどうであれ設定が入っていた。2026-09-27 の楽園蒲田では
エウレカ 3227 が差枚 -714 だったが演出で設定5以上が確定し、モンハンライズは
現地組が「全」と報告した（DB では9台中5台プラス）。こうした情報は
その場の会話で終わり、次の予測に戻らなかった。

情報の重み（2026-09-28 ユーザー決定）
--------------------------------------
演出での設定確認 > 主催者の結果発表ラベル > 現地組の報告 > 実績の数値。
答え合わせ表（`event_days.py history`）はこの順で台ごとの判断を出し、
下位の情報と食い違ったことは消さずに残す。

⚠️ 結果を知ってからの情報なので、予告として `announce.py` に登録してはならない
（的中率が定義上100%になる）。

台帳: backtest/field_obs/field_obs.jsonl（追記専用。訂正は supersedes で前の行を指す）

使い方:
    venv\\Scripts\\python.exe -m backtest.field_obs add --hall 楽園蒲田店 --date 20260927 \\
        --machine-number 3227 --kind effect_confirmed --setting 5以上 \\
        --observation "演出で設定5以上確定" --reporter "実際に打った人（ユーザー伝聞）"
    venv\\Scripts\\python.exe -m backtest.field_obs add --hall 楽園蒲田店 --date 20260927 \\
        --machine-name モンハンライズ --kind field_group --observation "全" --reporter 現地組
    venv\\Scripts\\python.exe -m backtest.field_obs list --hall 楽園蒲田店
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "backtest", "field_obs", "field_obs.jsonl")
JST = timezone(timedelta(hours=9))

# 情報源の種類。重みの順は event_days._setting_verdict を参照。
SOURCE_KINDS = {
    "effect_confirmed": "演出での設定確認（実際に打った人が確認）",
    "field_group": "現地組の報告（台ごとの確認ではない伝聞）",
    "sns": "SNS上の報告",
}


def _load(path=LEDGER):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _resolve_machine(hall, business_date, machine_number, machine_name):
    """その日の実績DBの正式な機種名に直す。DBにその日が無ければ入力のまま返す。"""
    from backtest.event_days import _history_matches
    from backtest.run_backtest import load_frame

    try:
        frame = load_frame(hall)
    except (FileNotFoundError, ValueError) as exc:
        print("[WARN] 実績DBを読めないため機種名を照合しない: %s" % exc, file=sys.stderr)
        return machine_name, None
    day = frame[frame["date"].astype(str) == business_date]
    if day.empty:
        print("[WARN] %s の実績がDBに無いため機種名を照合しない" % business_date, file=sys.stderr)
        return machine_name, None
    if machine_number is not None:
        hit = day[day["machine_number"] == machine_number]
        if hit.empty:
            raise SystemExit("%s の %s に台番号 %d が無い" % (hall, business_date, machine_number))
        return str(hit.iloc[0]["machine_name"]), None
    names = sorted(day["machine_name"].dropna().unique().tolist())
    matched = _history_matches(hall, machine_name, names)
    if len(matched) != 1:
        raise SystemExit("機種名『%s』がその日の機種に1つに決まらない: %s" % (machine_name, matched or "該当なし"))
    return matched[0], machine_name


def add(
    hall,
    business_date,
    observation,
    source_kind,
    reporter,
    machine_number=None,
    machine_name=None,
    setting_text=None,
    note=None,
    supersedes=None,
    path=LEDGER,
    resolve=True,
):
    from backtest.event_days import _normalize_hall

    if not re.fullmatch(r"\d{8}", business_date):
        raise SystemExit("日付は YYYYMMDD で指定すること: %r" % business_date)
    if source_kind not in SOURCE_KINDS:
        raise SystemExit("--kind は %s のどれか" % ", ".join(SOURCE_KINDS))
    if machine_number is None and not machine_name:
        raise SystemExit("--machine-number か --machine-name のどちらかが要る")
    hall = _normalize_hall(hall)
    reported_name = None
    if resolve:
        machine_name, reported_name = _resolve_machine(hall, business_date, machine_number, machine_name)
    rows = _load(path)
    row = {
        "obs_id": "fo-%04d" % (len(rows) + 1),
        "hall": hall,
        "business_date": business_date,
        "machine_number": machine_number,
        "machine_name": machine_name,
        "reported_name": reported_name,
        "observation": observation,
        "setting_text": setting_text,
        "source_kind": source_kind,
        "reporter": reporter,
        "note": note,
        "registered_at": datetime.now(JST).isoformat(timespec="seconds"),
        "supersedes": supersedes,
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add", help="現場の報告を1件登録する")
    s.add_argument("--hall", required=True)
    s.add_argument("--date", required=True, help="営業日 YYYYMMDD")
    s.add_argument("--machine-number", type=int)
    s.add_argument("--machine-name", help="機種で報告されたとき（例: モンハンライズ 全）")
    s.add_argument("--kind", required=True, choices=sorted(SOURCE_KINDS))
    s.add_argument("--observation", required=True, help="報告の中身（例: 演出で設定5以上確定 / 全）")
    s.add_argument("--setting", help="確認できた設定の範囲（例: 5以上 / 偶数 / 6）。6と決めつけず範囲のまま書く")
    s.add_argument("--reporter", required=True, help="報告した人（例: 実際に打った人 / 現地組）")
    s.add_argument("--note")
    s.add_argument("--supersedes", help="訂正する前の obs_id")
    s = sub.add_parser("list", help="登録済みの報告を表示する")
    s.add_argument("--hall")
    a = p.parse_args(argv)
    if a.cmd == "add":
        row = add(
            a.hall,
            a.date,
            a.observation,
            a.kind,
            a.reporter,
            machine_number=a.machine_number,
            machine_name=a.machine_name,
            setting_text=a.setting,
            note=a.note,
            supersedes=a.supersedes,
        )
        print(json.dumps(row, ensure_ascii=False))
    else:
        for row in _load():
            if a.hall and row.get("hall") != a.hall:
                continue
            print(json.dumps(row, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
