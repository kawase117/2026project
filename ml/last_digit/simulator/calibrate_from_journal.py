"""
calibrate_from_journal.py
稼働日誌CSVからシミュレーターパラメータを実測値で校正する。

出力:
  1. calibration_summary.txt   — P_move, α係数, セッション番号別勝率 (テキスト)
  2. session_win_rate.csv      — session_num × 勝率詳細
  3. daily_session_count.csv   — 日ごとのセッション数分布
  4. cumulative_balance.csv    — 日ごとの累積収支（設定狙いのみ）

使用方法:
  python -m ml.last_digit.simulator.calibrate_from_journal \
      --csv "path/to/稼働日誌DB_all.csv" \
      --output-dir ml/last_digit/simulator/output

フィルタリング方針:
  除外: 属性に「エナ」または「ゾーン」を含む行
  保持: それ以外の全行（設定狙い, 末尾狙い, リセ, 高配分狙い, 全狙い, 台番号狙い 等）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import numpy as np


# ─────────────────────────────────────────
# 除外キーワード（属性列に含まれる場合その行を除外）
# ─────────────────────────────────────────
EXCLUDE_ATTR_PATTERNS = ["エナ", "ゾーン"]


def parse_japanese_datetime(s: str) -> pd.Timestamp | None:
    """
    "2026年4月1日 16:46 (JST)" → Timestamp
    "2026年5月1日 14:30 (JST)" 等に対応
    """
    if pd.isna(s) or not isinstance(s, str):
        return None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", s)
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    try:
        return pd.Timestamp(year=y, month=mo, day=d, hour=h, minute=mi)
    except ValueError:
        return None


def load_and_filter(csv_path: Path) -> pd.DataFrame:
    """CSVを読み込み、エナ・ゾーン行を除外して返す"""
    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 列名正規化（前後スペース除去）
    df.columns = [c.strip() for c in df.columns]

    # 必須列の確認
    required = {"属性", "勝敗", "収支", "開始時刻"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"[ERROR] 必須列が見つかりません: {missing}\n実列名: {list(df.columns)}")

    # 属性列をstr化
    df["属性"] = df["属性"].fillna("").astype(str)

    # 除外フィルタ: パターンのいずれかが属性に含まれる行を除外
    exclude_mask = df["属性"].apply(
        lambda attr: any(pat in attr for pat in EXCLUDE_ATTR_PATTERNS)
    )
    n_before = len(df)
    df = df[~exclude_mask].copy()
    n_after = len(df)
    print(f"[filter] 除外: {n_before - n_after}行 / 残: {n_after}行 / 総計: {n_before}行")
    print(f"         除外パターン: {EXCLUDE_ATTR_PATTERNS}")

    return df


def assign_session_num(df: pd.DataFrame) -> pd.DataFrame:
    """
    開始時刻をパースし、同一日内のセッション順(1始まり)を付与する。
    同一日 = 開始時刻の「日付部分」が等しい行
    """
    df = df.copy()

    df["start_ts"] = df["開始時刻"].apply(parse_japanese_datetime)
    n_unparsed = df["start_ts"].isna().sum()
    if n_unparsed > 0:
        print(f"[warn] 開始時刻をパースできなかった行: {n_unparsed}件（除外）")
        df = df.dropna(subset=["start_ts"]).copy()

    df["date"] = df["start_ts"].dt.date

    # 同一日内で開始時刻順にソートしてserial番号付与
    df = df.sort_values(["date", "start_ts"]).copy()
    df["session_num"] = df.groupby("date").cumcount() + 1

    return df


def parse_balance(series: pd.Series) -> pd.Series:
    """収支列を数値化（カンマ・非数値を除去）"""
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("[^\\-0-9]", "", regex=True)
        .pipe(pd.to_numeric, errors="coerce")
    )


def compute_win_flag(series: pd.Series) -> pd.Series:
    """勝敗列をbool化: Yes→True, No→False"""
    return series.astype(str).str.strip().str.lower().isin(["yes"])


def analyze(df: pd.DataFrame) -> dict:
    """
    各種統計を計算して辞書で返す。
    """
    df = df.copy()
    df["win"] = compute_win_flag(df["勝敗"])
    df["balance"] = parse_balance(df["収支"])

    # ── P_move: 2台以上打った日の割合 ──
    daily_max_session = df.groupby("date")["session_num"].max()
    n_days_total = len(daily_max_session)
    n_days_multi = (daily_max_session >= 2).sum()
    p_move = n_days_multi / n_days_total if n_days_total > 0 else 0.0

    # ── セッション番号別勝率 ──
    win_by_session = (
        df.groupby("session_num")["win"]
        .agg(win_count="sum", n="count")
        .assign(win_rate=lambda x: x["win_count"] / x["n"])
    )

    # ── α係数の推定 ──
    # セッション1の勝率を基準にした各セッションの相対値
    # α_k = win_rate(k+1) / win_rate(k) （session 1→2 のみ報告）
    alpha_12 = None
    if 1 in win_by_session.index and 2 in win_by_session.index:
        wr1 = win_by_session.loc[1, "win_rate"]
        wr2 = win_by_session.loc[2, "win_rate"]
        if wr1 > 0:
            alpha_12 = wr2 / wr1

    # ── 日別セッション数分布 ──
    session_dist = daily_max_session.value_counts().sort_index()

    # ── 日別累積収支 ──
    df_daily = (
        df.groupby("date")["balance"]
        .sum()
        .reset_index()
        .rename(columns={"balance": "daily_balance"})
    )
    df_daily["cumulative_balance"] = df_daily["daily_balance"].cumsum()

    return {
        "p_move": p_move,
        "n_days_total": n_days_total,
        "n_days_multi": int(n_days_multi),
        "alpha_12": alpha_12,
        "win_by_session": win_by_session,
        "session_dist": session_dist,
        "daily_balance": df_daily,
        "total_sessions": len(df),
        "total_win_rate": df["win"].mean(),
        "total_balance": df["balance"].sum(),
    }


def print_summary(r: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("  シミュレーターパラメータ校正レポート（設定狙い限定）")
    lines.append("=" * 60)

    lines.append(f"\n■ 対象セッション数: {r['total_sessions']}")
    lines.append(f"■ 対象稼働日数:     {r['n_days_total']}")
    lines.append(f"■ 全体勝率:         {r['total_win_rate']:.1%}")
    lines.append(f"■ 全体収支合計:     {r['total_balance']:+,.0f}円")

    lines.append("\n─ P_move（1日に2台以上打った日の割合）─")
    lines.append(f"  P_move = {r['p_move']:.3f}  ({r['n_days_multi']} / {r['n_days_total']}日)")

    lines.append("\n─ セッション番号別勝率 ─")
    lines.append(f"  {'Session':>8}  {'N':>5}  {'Wins':>5}  {'WinRate':>8}")
    for snum, row in r["win_by_session"].iterrows():
        marker = " ← base" if snum == 1 else ""
        lines.append(
            f"  {snum:>8}  {int(row['n']):>5}  {int(row['win_count']):>5}  {row['win_rate']:>7.1%}{marker}"
        )

    lines.append("\n─ α係数（劣化係数）推定 ─")
    if r["alpha_12"] is not None:
        lines.append(f"  α (session1→2) = {r['alpha_12']:.3f}")
        lines.append(
            f"  解釈: 再チャレンジ1回で勝率が基準の {r['alpha_12']:.1%} 倍に変化"
        )
        if r["alpha_12"] > 1.0:
            lines.append(
                "  [!] alpha > 1: session2の勝率がsession1より高い（情報蓄積・台選択改善の可能性）"
            )
        elif r["alpha_12"] < 1.0:
            lines.append(
                "  [!] alpha < 1: session2の勝率がsession1より低い（高設定台の可用性低下）"
            )
    else:
        lines.append("  計算不可（session1またはsession2のデータが不足）")

    lines.append("\n─ 日別セッション数分布 ─")
    for snum, cnt in r["session_dist"].items():
        lines.append(f"  {snum}台打ち: {int(cnt):3d}日")

    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="稼働日誌からシミュレーターパラメータを校正する")
    parser.add_argument("--csv", required=True, type=Path, help="稼働日誌CSVファイルパス")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("ml/last_digit/simulator/output"),
        help="出力ディレクトリ (default: ml/last_digit/simulator/output)",
    )
    args = parser.parse_args()

    if not args.csv.exists():
        sys.exit(f"[ERROR] CSVが見つかりません: {args.csv}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[load] {args.csv}")
    df = load_and_filter(args.csv)
    df = assign_session_num(df)

    print(f"[analyze] {len(df)}セッション / {df['date'].nunique()}日")
    r = analyze(df)

    # ── 画面出力 ──
    summary_text = print_summary(r)
    print(summary_text)

    # ── ファイル出力 ──
    # 1. サマリーテキスト
    txt_path = args.output_dir / "calibration_summary.txt"
    txt_path.write_text(summary_text, encoding="utf-8")
    print(f"\n[output] {txt_path}")

    # 2. セッション別勝率CSV
    csv1 = args.output_dir / "session_win_rate.csv"
    r["win_by_session"].reset_index().to_csv(csv1, index=False, encoding="utf-8-sig")
    print(f"[output] {csv1}")

    # 3. 日別セッション数分布CSV
    csv2 = args.output_dir / "daily_session_count.csv"
    r["session_dist"].reset_index().rename(
        columns={"session_num": "max_session_per_day", "count": "n_days"}
    ).to_csv(csv2, index=False, encoding="utf-8-sig")
    print(f"[output] {csv2}")

    # 4. 日別累積収支CSV
    csv3 = args.output_dir / "cumulative_balance.csv"
    r["daily_balance"].to_csv(csv3, index=False, encoding="utf-8-sig")
    print(f"[output] {csv3}")


if __name__ == "__main__":
    main()
