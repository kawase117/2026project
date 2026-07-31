#!/usr/bin/env python3
"""
model_edge_briefing.py — 機種別エッジの1画面サマリ（全ホール共通）

`eda/results/briefing/model_monthly_edge.csv`（`model_monthly_edge.py` が生成）を読み、
ホール別に「今どの機種が強いか」を安定性フラグ付きで1画面に要約する。

## なぜ必要か
model_monthly_edge.csv は 12,000行超・5MB あり、人間が読める形をしていない。
そのため 2026-07 の楽園で東京喰種・北斗の拳転生・モンキーターンV・化物語・
ネオアイムジャグラーEX が上位に並んでいたにもかかわらず、この発見が
推薦にも事前登録にも届かないまま放置された。
本スクリプトはその橋渡し専用であり、新しい統計を計算しない。
DBには一切アクセスしない（CSVの読み取りと整形のみ）。

## 使い方
    venv\\Scripts\\python.exe eda/model_edge_briefing.py
    venv\\Scripts\\python.exe eda/model_edge_briefing.py --hall 楽園 --top 15
    venv\\Scripts\\python.exe eda/model_edge_briefing.py --month 202606 --save

## 判定フラグの読み方
    ◎ 安定    CI下限>0 かつ 上位3台を除いてもプラス → 機種全体に効果がある
    ○ 少数台  CI下限>0 だが 上位3台を除くと消える   → 機種ではなく数台の当たりを見ている
    △ 要観察  CI下限が0以下 or 算出不能              → 判定保留

    注記 撤去済  月末時点で設置なし     → 当日判断には使えない
    注記 鉄台N日 鉄台の稼働日が含まれる → 常時高設定台が平均を押し上げている可能性
    注記 台数N   母数が MIN_MACHINES 未満

edge_pp は「同日同カテゴリ比の機械割エッジ(パーセントポイント)」。
差枚ベースの baseline 比とは指標が異なり、両者が食い違うことがある
（2026-07-31時点、楽園アイムジャグラーで実際に食い違いが未解決）。
本ブリーフィングは機械割ベースであることを意識して読むこと。

同じ機種名が複数行に出るのは設置コホート（増台ブロック）が分かれているため。
machine_number_range 列で区別する。
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = ROOT / "eda" / "results" / "briefing" / "model_monthly_edge.csv"
OUT_DIR = ROOT / "eda" / "results" / "briefing"

# 台数がこれ未満の機種は母数不足として注記する
MIN_MACHINES = 8

# 稼働率 = n_machine_days / (n_machines * n_days)
# コホートの一部が月中で撤去されると 1.0 を大きく下回る。
# active_until_month_end はコホートの一部でも残っていると True になるため、
# 部分撤去を検出できない。稼働率はその穴を塞ぐ。
# 実測（202607, 658行）の中央値は 1.00、第1四分位は 0.93。
COVERAGE_WARN = 0.90  # これ未満は注記する
COVERAGE_BAD = 0.70  # これ未満は判定を △ に落とす


def use_utf8_stdout() -> None:
    """Windows コンソールで日本語が化けるのを防ぐ。"""
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def classify(row: pd.Series) -> str:
    """安定性フラグを返す。判定順は厳しい順。

    稼働率が低い行（コホートの一部が月中で撤去された等）は、
    残った少数台や撤去直前の数日だけを見ている可能性が高いため △ に落とす。
    """
    if row["coverage"] < COVERAGE_BAD:
        return "△ 要観察"

    ci_lo = row["edge_ci95_lo"]
    excl3 = row["edge_excl_top3"]

    if pd.isna(ci_lo) or ci_lo <= 0:
        return "△ 要観察"
    if pd.isna(excl3) or excl3 <= 0:
        return "○ 少数台"
    return "◎ 安定"


def annotate(row: pd.Series) -> str:
    """補足注記（撤去済み・稼働率低下・鉄台混入・台数不足）をまとめる。"""
    notes = []
    if not bool(row["active_until_month_end"]):
        notes.append("撤去済")
    if row["coverage"] < COVERAGE_WARN:
        notes.append(f"稼働率{row['coverage']:.2f}")
    if int(row["n_iron_machine_days"]) > 0:
        notes.append(f"鉄台{int(row['n_iron_machine_days'])}日")
    if int(row["n_machines"]) < MIN_MACHINES:
        notes.append(f"台数{int(row['n_machines'])}")
    return " / ".join(notes)


# 判定の並び順（◎を先頭に出す。edge_pp だけで並べると小標本ノイズが上位を占める）
VERDICT_RANK = {"◎ 安定": 0, "○ 少数台": 1, "△ 要観察": 2}


def _table(rows: pd.DataFrame) -> list[str]:
    lines = [
        "| 判定 | 機種 | 区分 | 台数 | 台番範囲 | 稼働率 | edge_pp | CI下限 | 上位3台除外後 | 注記 |",
        "|:--|:--|:--|--:|:--|--:|--:|--:|--:|:--|",
    ]
    for _, r in rows.iterrows():
        ci_lo = "—" if pd.isna(r["edge_ci95_lo"]) else f"{r['edge_ci95_lo']:+.2f}"
        excl3 = "—" if pd.isna(r["edge_excl_top3"]) else f"{r['edge_excl_top3']:+.2f}"
        lines.append(
            f"| {r['判定']} | {r['machine_name']} | {r['category']} | "
            f"{int(r['n_machines'])} | {r['machine_number_range']} | "
            f"{r['coverage']:.2f} | "
            f"{r['edge_pp']:+.2f} | {ci_lo} | {excl3} | {r['注記']} |"
        )
    return lines


def render_hall(df_hall: pd.DataFrame, hall: str, month: str, top: int, show_all: bool) -> str:
    """1ホール分のMDテーブルを組み立てる。

    既定では「当日の判断に使える行」だけを出す:
    撤去済み（月末時点で設置なし）と母数不足（n < MIN_MACHINES）を除外する。
    --all 指定時は除外分も別表として続けて出す。
    """
    cur = df_hall[df_hall["year_month"] == month].copy()
    if cur.empty:
        return f"### {hall}\n\n{month} のデータなし\n"

    cur["判定"] = cur.apply(classify, axis=1)
    cur["注記"] = cur.apply(annotate, axis=1)
    cur["_rank"] = cur["判定"].map(VERDICT_RANK)

    usable_mask = cur["active_until_month_end"].astype(bool) & (cur["n_machines"] >= MIN_MACHINES)
    usable = cur[usable_mask].sort_values(["_rank", "edge_pp"], ascending=[True, False]).head(top)
    excluded = cur[~usable_mask].sort_values("edge_pp", ascending=False).head(top)

    lines = [f"### {hall}  ({month})", ""]
    if usable.empty:
        lines.append(f"設置継続かつ n>={MIN_MACHINES} の機種なし")
        lines.append("")
    else:
        lines += _table(usable)
        lines.append("")

    if show_all and not excluded.empty:
        lines.append(f"<details><summary>除外分（撤去済み / n&lt;{MIN_MACHINES}）</summary>")
        lines.append("")
        lines += _table(excluded)
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    use_utf8_stdout()

    p = argparse.ArgumentParser(description="機種別エッジの1画面サマリ")
    p.add_argument("--hall", default=None, help="ホール名の部分一致（未指定なら全ホール）")
    p.add_argument("--month", default=None, help="YYYYMM（未指定なら最新月）")
    p.add_argument("--top", type=int, default=10, help="ホールあたりの表示件数")
    p.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help=f"撤去済み・n<{MIN_MACHINES} の除外分も表示する",
    )
    p.add_argument("--save", action="store_true", help="MDファイルにも保存する")
    args = p.parse_args()

    if not SRC_PATH.exists():
        print(f"[ERROR] {SRC_PATH} が無い。先に model_monthly_edge.py を実行すること。")
        return 1

    df = pd.read_csv(SRC_PATH)
    df["year_month"] = df["year_month"].astype(str)

    # 稼働率。分母0のときは判定不能なので 0 扱い（=△に落ちる）にする。
    denom = df["n_machines"] * df["n_days"]
    df["coverage"] = (df["n_machine_days"] / denom).where(denom > 0, 0.0)

    month = args.month or df["year_month"].max()
    halls = sorted(str(h) for h in df["hall"].unique())
    if args.hall:
        matched = [h for h in halls if args.hall in h]
        if not matched:
            print(f"[ERROR] ホール '{args.hall}' に一致なし。候補: {halls}")
            return 1
        halls = matched

    blocks = [
        f"# 機種別エッジ ブリーフィング（{month}）",
        "",
        "指標は同日同カテゴリ比の機械割エッジ(pp)。差枚ベースの baseline 比とは別指標。",
        "◎安定=CI下限>0かつ上位3台除外後もプラス / ○少数台=上位3台に依存 / △要観察=CI下限0以下",
        "同一機種が複数行あるのは設置コホート違い。machine_number_range で区別する。",
        f"稼働率 = 実データ台日数 / (台数×営業日数)。{COVERAGE_BAD:.2f}未満は月中で"
        "部分撤去された疑いがあるため判定を△に落とす（撤去直前の数日を拾っている可能性）。",
        f"既定では撤去済み・n<{MIN_MACHINES} を除外（--all で表示）。並びは判定順→edge_pp順。",
        "",
        "探索用。多重比較補正なし。判定は事前登録+フォワード（backtest/prereg.py）で行うこと。",
        "",
    ]
    for hall in halls:
        blocks.append(render_hall(df[df["hall"].astype(str) == hall], hall, month, args.top, args.show_all))

    report = "\n".join(blocks)
    print(report)

    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUT_DIR / f"model_edge_briefing_{month}.md"
        out_path.write_text(report, encoding="utf-8")
        print(f"\n[saved] {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
