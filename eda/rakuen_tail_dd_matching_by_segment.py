"""「末尾をDDに寄せる」仮説を、カテゴリ×フロアで層別して並べ替え検定で再検証する。

背景:
    `eda/rakuen_dd_tail_digit_matching_scan.py` は全カテゴリをプールし、DDごとに
    個別検定した結果ほぼ不支持だった（31検定中有意2件＝偶然の範囲、
    rakuen_theory.md §3.1c）。

    しかし §3.1a で「楽園はカテゴリごとに別のイベントカレンダーを持つ」ことが
    実証されている。仮にジャグだけ、あるいは技術介入だけで末尾ルールが動いていても、
    全カテゴリプールでは他カテゴリのノイズに薄められて消える。カテゴリ×フロアで
    層別する再検定は、確立済みの発見から導かれる筋の通った追試である
    （ユーザー提案、2026-07-29）。

多重比較の扱い（ここが本スクリプトの肝）:
    素朴にカテゴリ4×フロア5×DD31で割ると検定数が約600になり、§3.1c より状況が悪化する。
    「どこかで有意が出る」のは確実で、それは何の証拠にもならない。そこで2つ手を打つ。

    (1) **31日を1つの統計量に集約する。** セル（カテゴリ×フロア）ごとに
        lift = mean(resid_d | ルールが指す末尾) - mean(resid_d | それ以外)
        を全31日プールで計算する。検定数はセル数まで落ちる。

    (2) **並べ替え検定。** 末尾ラベル 0-9 の対応表 σ をランダムに入れ替えた
        「構造は同じだが数字が違う」対応表を N 通り作り、実際の対応表の lift が
        その帰無分布のどこに来るかで p 値を出す。これにより
        「どの数字が何日ぶんマッチ対象になるか」という**露出頻度の偏り**
        （例: 十の位に 1,2,3 が多く登場する）が自動的に統制される。
        DD11/22 の「末尾ゾロ目」は数字の置換で不変なため、置換対象から外して固定する。

桁分解ルール（ユーザー確定、§3.1c と同一）:
    DD 1-9          → 対象末尾 = {DD}
    DD 2桁・両桁相異 → 対象末尾 = {十の位, 一の位}
    DD 11・22        → 対象は「末尾ゾロ目全般」（台番号下2桁が同じ台）

指標:
    resid_d = 機械割 - その日の同カテゴリ全台平均（同日内残差）。
    日レベルの交絡（客入り・天候・イベント日の全体的な強さ）が完全に落ちる。
    技術介入は BB+RB(回/1000G) の同日内残差も併記する
    （打ち手の技量ではボーナス確率は動かないため、設定投入の署名になる。§2.1b）。

    min_games による足切りはしない（games は設定の下流。CLAUDE.md）。

期間は工事前エポック 20250101〜20260705。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_tail_dd_matching_by_segment
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
HEATMAP_DIR = PROJECT_ROOT / "Heatmap"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_tail_dd_matching_by_segment"

DATE_START = "20250101"
DATE_END = "20260705"

N_PERM = 1000
SEED = 20260729
MIN_ROWS = 300  # セルの最小行数。これ未満は検出力がなく解釈できないので出力から外す


def load_floor_map() -> pd.Series:
    frames = [
        pd.read_csv(p, usecols=["floor", "machine_number"])
        for p in sorted(HEATMAP_DIR.glob("*_floor_coordinates_rakuen.csv"))
    ]
    fm = pd.concat(frames, ignore_index=True).drop_duplicates("machine_number")
    return fm.set_index("machine_number")["floor"]


def load() -> pd.DataFrame:
    query = """
        SELECT r.date, r.machine_number, r.machine_name,
               r.games_normalized AS games,
               r.diff_coins_normalized AS diff_coins,
               r.bb_count, r.rb_count,
               m.jug_flag, m.hana_flag, m.bt_flag
        FROM machine_detailed_results r
        LEFT JOIN machine_master m
          ON r.machine_name = m.machine_name_normalized
        WHERE r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
    """
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(DATE_START, DATE_END))

    for col in ("jug_flag", "hana_flag", "bt_flag"):
        df[col] = df[col].fillna(0).astype(int)
    df["category"] = np.select(
        [df["jug_flag"] == 1, df["hana_flag"] == 1, df["bt_flag"] == 1],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df["rate"] = 100 + df["diff_coins"] / (3 * df["games"]) * 100
    df["bbrb"] = (df["bb_count"].fillna(0) + df["rb_count"].fillna(0)) / df["games"] * 1000
    dt = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = dt.dt.day

    df["resid_d"] = df["rate"] - df.groupby(["date", "category"])["rate"].transform("mean")
    df["bbrb_d"] = df["bbrb"] - df.groupby(["date", "category"])["bbrb"].transform("mean")

    df["last_digit"] = df["machine_number"] % 10
    two = df["machine_number"] % 100
    df["is_tail_zorome"] = (two // 10) == (two % 10)
    df["floor"] = df["machine_number"].map(load_floor_map())
    return df


def dd_target_digits(dd: int) -> set[int] | None:
    """DDごとの対象末尾。None は「末尾ゾロ目全般」（DD11/22）を意味する。"""
    if dd <= 9:
        return {dd}
    tens, ones = divmod(dd, 10)
    if tens == ones:
        return None
    return {tens, ones}


def build_match_mask(df: pd.DataFrame, sigma: dict[int, int]) -> np.ndarray:
    """末尾ラベルの置換 sigma のもとで「その日のルールに合致する行」の真偽値を返す。

    sigma は 0-9 の置換。恒等置換なら実際の仮説、ランダム置換なら帰無仮説の1標本。
    DD11/22 のゾロ目は数字の置換で不変なので sigma を適用しない。
    """
    dd = df["dd"].to_numpy()
    ld = df["last_digit"].to_numpy()
    zo = df["is_tail_zorome"].to_numpy()
    out = np.zeros(len(df), dtype=bool)
    for d in np.unique(dd):
        tgt = dd_target_digits(int(d))
        sel = dd == d
        if tgt is None:
            out[sel] = zo[sel]
        else:
            mapped = [sigma[t] for t in tgt]
            out[sel] = np.isin(ld[sel], mapped)
    return out


def lift_of(values: np.ndarray, mask: np.ndarray) -> float:
    if mask.sum() == 0 or (~mask).sum() == 0:
        return np.nan
    return values[mask].mean() - values[~mask].mean()


def permutation_test(sub: pd.DataFrame, col: str, rng: np.random.Generator) -> tuple[float, float, int, int]:
    """実際の対応表 vs ランダム置換 N 通り。(lift, p値, 順位, マッチ行数) を返す。"""
    vals_all = sub[col].to_numpy()
    ok = ~np.isnan(vals_all)
    sub_ok = sub.loc[ok]
    vals = vals_all[ok]

    identity = {d: d for d in range(10)}
    real_mask = build_match_mask(sub_ok, identity)
    real_lift = lift_of(vals, real_mask)
    if np.isnan(real_lift):
        return (np.nan, np.nan, -1, 0)

    null = np.full(N_PERM, np.nan)
    for i in range(N_PERM):
        perm = rng.permutation(10)
        sigma = {d: int(perm[d]) for d in range(10)}
        null[i] = lift_of(vals, build_match_mask(sub_ok, sigma))
    null = null[~np.isnan(null)]
    # 両側p値: 実測の絶対値以上の帰無標本の割合
    p = float((np.abs(null) >= abs(real_lift)).mean())
    rank = int((null > real_lift).sum()) + 1
    return (float(real_lift), p, rank, int(real_mask.sum()))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    pd.set_option("display.width", 200)

    df = load()
    print(f"{len(df):,}行 / {df['date'].nunique()}日 / {df['machine_number'].nunique()}台")
    print(df.groupby(["category", "floor"]).machine_number.nunique().to_string())

    rows = []

    # レベル1: カテゴリのみ（フロア統合）
    for cat, sub in df.groupby("category"):
        if len(sub) < MIN_ROWS:
            continue
        lift, p, rank, n_match = permutation_test(sub, "resid_d", rng)
        rec = {
            "level": "カテゴリ",
            "category": cat,
            "floor": "-",
            "n_machines": sub["machine_number"].nunique(),
            "n_match_rows": n_match,
            "n_other_rows": len(sub) - n_match,
            "lift": lift,
            "perm_p": p,
            "perm_rank": rank,
        }
        if cat == "技術介入":
            bl, bp, _, _ = permutation_test(sub, "bbrb_d", rng)
            rec["bbrb_lift"], rec["bbrb_p"] = bl, bp
        rows.append(rec)

    # レベル2: カテゴリ×フロア
    for (cat, fl), sub in df.groupby(["category", "floor"]):
        if len(sub) < MIN_ROWS:
            continue
        lift, p, rank, n_match = permutation_test(sub, "resid_d", rng)
        rec = {
            "level": "カテゴリ×フロア",
            "category": cat,
            "floor": fl,
            "n_machines": sub["machine_number"].nunique(),
            "n_match_rows": n_match,
            "n_other_rows": len(sub) - n_match,
            "lift": lift,
            "perm_p": p,
            "perm_rank": rank,
        }
        if cat == "技術介入":
            bl, bp, _, _ = permutation_test(sub, "bbrb_d", rng)
            rec["bbrb_lift"], rec["bbrb_p"] = bl, bp
        rows.append(rec)

    res = pd.DataFrame(rows)
    res["sig"] = np.where(res["perm_p"] < 0.05, "*", "")
    res = res.sort_values(["level", "perm_p"])
    res.to_csv(OUT_DIR / "segment_permutation_result.csv", index=False, encoding="utf-8-sig")

    print("\n=== 並べ替え検定（末尾ラベル0-9をランダム置換した1000通りと比較） ===")
    print("lift = ルールが指す末尾の同日内残差 - それ以外の同日内残差（機械割pp）")
    cols = ["level", "category", "floor", "n_machines", "n_match_rows", "lift", "perm_p", "perm_rank", "sig"]
    if "bbrb_lift" in res.columns:
        cols += ["bbrb_lift", "bbrb_p"]
    print(res[cols].to_string(index=False, float_format=lambda v: f"{v:,.4f}"))

    n_sig = int((res["perm_p"] < 0.05).sum())
    print(f"\n有意セル: {n_sig}/{len(res)}（5%水準・偶然の期待値 約{len(res) * 0.05:.1f}）")

    # 参考: 有意セルの内訳をDD別に見る（事後の説明用。検定ではない）
    detail = []
    for _, r in res[res["perm_p"] < 0.05].iterrows():
        sub = df[df["category"] == r["category"]]
        if r["floor"] != "-":
            sub = sub[sub["floor"] == r["floor"]]
        for dd_val in sorted(sub["dd"].unique()):
            tgt = dd_target_digits(int(dd_val))
            day = sub[sub["dd"] == dd_val]
            other = sub[sub["dd"] != dd_val]
            if tgt is None:
                m = day["is_tail_zorome"]
                label = "ゾロ目"
            else:
                m = day["last_digit"].isin(tgt)
                label = ",".join(str(t) for t in sorted(tgt))
            if m.sum() < 5:
                continue
            detail.append(
                {
                    "category": r["category"],
                    "floor": r["floor"],
                    "dd": dd_val,
                    "target": label,
                    "n_match": int(m.sum()),
                    "lift": day.loc[m, "resid_d"].mean() - other["resid_d"].mean(),
                }
            )
    if detail:
        dt = pd.DataFrame(detail)
        dt.to_csv(OUT_DIR / "per_dd_within_segment.csv", index=False, encoding="utf-8-sig")
        print("\n=== 有意セルのDD別内訳（事後の説明用・検定ではない、上位10） ===")
        print(
            dt.sort_values("lift", ascending=False).head(10).to_string(index=False, float_format=lambda v: f"{v:,.4f}")
        )

    print(f"\n出力: {OUT_DIR}")


if __name__ == "__main__":
    main()
