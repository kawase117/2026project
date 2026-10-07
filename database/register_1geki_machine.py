"""一撃(1geki.jp)のページURLを指定して、機種マスターCSVに1機種を登録する。

`sync_new_machine_master.py` は「ホールDBに現れた新台(発売60日以内)」を自動で拾う。
こちらはユーザーが機種とURLを指定する経路で、過去シリーズ(戦国コレクション5など)や、
まだホールDBに現れていない機種を登録するために使う。発売日の窓は見ない。

既定は確認のみ(ドライラン)。--apply で machine_master.csv に追記する。
旧書式のページはメーカー・タイプ・ボーナス確率を取れないことがあり、その場合は登録を拒否する
(欠けた行でマスターを汚さないため)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database.sync_new_machine_master import MASTER_CSV, make_row  # noqa: E402
from scraper import fetch_rtp_via_llm as research  # noqa: E402
from scraper import machine_master_research_url_mapper as url_mapper  # noqa: E402

REQUIRED = ("manufacturer", "machine_type", "release_date", "rtp1", "rtp6")


def build(name: str, url: str, official: str | None, html: str | None = None) -> tuple[dict | None, str]:
    html = html if html is not None else url_mapper.fetch_html(url, timeout=15)
    result = research.extract_specs_from_html(name, html, url)
    result["official_name"] = official or result.get("official_name") or name
    missing = [key for key in REQUIRED if not result.get(key)]
    if missing:
        return None, "missing:" + ",".join(missing)
    return result, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="ホールでの機種名(machine_name)")
    parser.add_argument("--url", required=True, help="一撃のページURL")
    parser.add_argument("--official", help="正式名(省略時はページから、取れなければ --name)")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    result, reason = build(args.name, args.url, args.official)
    if result is None:
        print(f"登録しません: {reason}")
        return 1
    header, rows = research.read_csv(MASTER_CSV)
    if any(row[header.index("machine_name")] == args.name for row in rows):
        print("登録済みです")
        return 0
    shown = {
        k: result.get(k)
        for k in (
            "official_name",
            "manufacturer",
            "machine_type",
            "release_date",
            "rtp1",
            "rtp6",
            "bb1",
            "bb6",
            "rb1",
            "rb6",
        )
    }
    print(shown)
    rows.append(make_row(header, args.name, result))
    if errors := research.validate_master(header, rows):
        print(f"検証に失敗: {errors[:3]}")
        return 1
    if args.apply:
        research._write_csv_atomic(MASTER_CSV, header, rows)
        print("追記しました")
    else:
        print("(ドライラン。--apply で追記)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
