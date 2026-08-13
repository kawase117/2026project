"""差枚の打ち切り（censoring）検出。

何が起きているか:
    楽園蒲田店の `diff_coins_normalized` は **両側で打ち切られている**。
    実測値は区間 [-5095, +15477] の外に一切出ず、両端に値が積み上がる。

        +15477 ちょうど … 173 行 / 131 日（隣接値 +15429 は 6 行）
        -5095  ちょうど … 823 行 / 306 日（隣接値 -5047  は 73 行）

    2025-01 から 2026-08 まで **毎月** 最小値 = -5095、最大値 = +15477 で一致する。
    データ側の偶然ではなく固定された上限・下限である。

発生源は元サイト（ana-slo.com）:
    我々のスクレイパー（`scraper/anaslo-scraper_multi.py:580`）は HTML テーブルの
    「差枚」テキストをそのまま `safe_int` するだけで、投入側の
    `json_processor.normalize_diff_coins` も符号処理しかしていない。clip は無い。

    決定的な証拠は値の量子化である。楽園の全期間のユニーク値はちょうど **431 個** で、
    隣接値の差は 47 か 48 しか現れない（(15477 - (-5095)) / 430 ≒ 47.8）。
    つまり 431 ピクセル高のグラフ画像を 1px ≒ 47.8 枚として読み取った値であり、
    y 軸レンジが [-5095, +15477] に固定されているために、それを超えた台は
    軸の端に張り付いて同一値に潰れる。

    比較のため他ホールは打ち切られていない（`CENSOR_BOUNDS` に載っていない）。
    蒲田1・蒲田7 は 100 枚刻みの実数値、ARROW・みとや・ベルシティ・レイトギャップ・
    ヒロキは最大値・最小値が 1〜2 行しか無く、端への積み上がりが起きていない。

なぜ値を補正しないか:
    打ち切られた台の真の差枚は分からないが、**無限に大きいわけではない**。
    現行のスロット規則（6号機）では 1 日の差枚上限は 19000 枚程度に規制されている
    （`REGULATORY_MAX_DIFF`）。よって右打ち切り台の真値は
    区間 [+15477, +19000] の中にしかなく、平均差枚の見誤りは台あたり
    最大 `19000 - 15477 = 3523` 枚（`max_understatement_hi()`）に収まる。
    「無限に過小評価している」わけではなく「せいぜいこの幅だけ過小評価しうる」
    という上限付きの誤差である。

    それでも値を埋めないのは、[15477, 19000] のどこが真値かは依然として不明で、
    条件付き期待値を当てるのは観測していない量を捏造することになるからである。
    代わりに「打ち切られている」という事実と、見誤りの最大幅をフラグとして
    持ち回り、集計値がどちら向きに・どこまで歪みうるかを明示する。

    実務上の帰結は単純である。右打ち切りを含む機種の平均差枚・全台系スコアは
    **真の値の下界**（最大 3523 枚/台の下振れ）になる。よって

        - 閾値を超えた           → そのまま正しい（下界が超えているなら真値も超える）
        - 閾値との差が 3523 枚以内 → 判定不能。打ち切りが無ければ超えていた可能性がある
        - 閾値との差が 3523 枚超  → 打ち切りを考慮しても届かない。外れと確定してよい

    2番目のケースを「外れ」として集計すると全台系の検出力を取りこぼす。
    `announce.py` の `_judge_claims` はこの区別のために `censoring` を結果へ残す。

    左打ち切り（-5095）は逆に平均を **過大** 評価する。楽園では右より 5 倍近く
    頻度が高く、機種平均差枚を押し上げる方向に効いている点に注意。負け側の
    規制上限は無い（差枚は投資額とゲーム数の積で理論上開いている）ため、
    左打ち切りには右打ち切りのような最大誤差の上限を付けられない。

境界の再検証:
    ana-slo 側が軸レンジを変えれば `CENSOR_BOUNDS` は陳腐化する。`detect_bounds()`
    が実データから打ち切り候補を再検出するので、定数と食い違ったら更新すること
    （`test/backtest/test_censoring.py` が実 DB に対して固定窓で検証している）。
"""

from __future__ import annotations

import pandas as pd

# ホール名 -> (下側打ち切り値, 上側打ち切り値)。値は実データから detect_bounds() で
# 検出し、モジュール docstring の根拠に基づいて凍結したもの。
# 打ち切りが検出されなかったホールは **載せない**（載っていない = 打ち切り無し）。
CENSOR_BOUNDS: dict[str, tuple[int, int]] = {
    # 全期間 2025-01-01 .. 2026-08-12 / 305,615 行で確認。
    "楽園蒲田店": (-5095, 15477),
}

# detect_bounds() の判定閾値。端の値が「隣接値の PILE_UP_RATIO 倍以上」出現し、
# かつ MIN_PILE_UP 行以上あるとき打ち切りと見なす。
PILE_UP_RATIO = 5.0
MIN_PILE_UP = 10

# 現行スロット規則（6号機）における1日差枚の実質上限。データからの検出値ではなく
# ドメイン知識として与えられた値。右打ち切りの真値はこれを超えないので、
# max_understatement_hi() の上限として使う。左側（負け）にはこの種の規制上限が無い。
REGULATORY_MAX_DIFF = 19000


def bounds_for(hall: str) -> tuple[int, int] | None:
    """ホール名に対する打ち切り境界。打ち切りが無いホールは None。"""
    return CENSOR_BOUNDS.get(hall)


def add_censor_flags(df: pd.DataFrame, hall: str) -> pd.DataFrame:
    """`censored_lo` / `censored_hi` の bool 列を付けて返す（in-place 変更）。

    打ち切りが無いホールでも列は必ず作る。呼び出し側が列の有無で分岐せずに
    済むようにするためで、その場合は全行 False になる。
    """
    b = bounds_for(hall)
    if b is None:
        df["censored_lo"] = False
        df["censored_hi"] = False
    else:
        lo, hi = b
        v = df["diff_coins_normalized"]
        df["censored_lo"] = v == lo
        df["censored_hi"] = v == hi
    return df


def max_understatement_hi(hall: str) -> int | None:
    """右打ち切り1台あたりの平均差枚の見誤りの最大幅（枚）。

    真値は [打ち切り値, REGULATORY_MAX_DIFF] のどこかにあるので、見誤りの
    上限は `REGULATORY_MAX_DIFF - 打ち切り値`。打ち切りが無いホールは None。
    左打ち切りには規制上限による対応物が無いため、この関数は右側専用。
    """
    b = bounds_for(hall)
    if b is None:
        return None
    _, hi = b
    return REGULATORY_MAX_DIFF - hi


def censoring_summary(day: pd.DataFrame) -> dict:
    """フレーム 1 つ分の打ち切り件数。`add_censor_flags` 済みでなくても落ちない。"""
    if "censored_hi" not in day.columns:
        return {"n_censored_hi": 0, "n_censored_lo": 0, "machines_hi": [], "machines_lo": []}
    hi = day[day["censored_hi"]]
    lo = day[day["censored_lo"]]
    return {
        "n_censored_hi": int(len(hi)),
        "n_censored_lo": int(len(lo)),
        "machines_hi": sorted(hi["machine_name"].unique().tolist()) if len(hi) else [],
        "machines_lo": sorted(lo["machine_name"].unique().tolist()) if len(lo) else [],
    }


def warning_text(summary: dict, hall: str, context: str = "") -> str | None:
    """警告文。打ち切りが無ければ None（呼び出し側は黙る）。"""
    if not summary["n_censored_hi"] and not summary["n_censored_lo"]:
        return None
    b = bounds_for(hall)
    where = f" {context}" if context else ""
    parts = [f"[censoring]{where} {hall} の差枚は元サイト側で {b} に打ち切られている。"]
    if summary["n_censored_hi"]:
        cap = max_understatement_hi(hall)
        cap_txt = f"（規制上限{REGULATORY_MAX_DIFF}枚を根拠に最大{cap}枚/台）" if cap is not None else ""
        parts.append(
            f"右打ち切り {summary['n_censored_hi']} 台"
            f"（{', '.join(summary['machines_hi'])}）→ 該当機種の平均差枚・スコアは真値の下界"
            f"{cap_txt}。閾値との差がこの幅以内なら『外れ』と断定しないこと。"
        )
    if summary["n_censored_lo"]:
        parts.append(
            f"左打ち切り {summary['n_censored_lo']} 台"
            f"（{', '.join(summary['machines_lo'])}）→ 該当機種の平均差枚は過大評価。"
        )
    return " ".join(parts)


def detect_bounds(df: pd.DataFrame) -> dict:
    """実データから打ち切り候補を再検出する（CENSOR_BOUNDS の検算用）。

    最小値・最大値がそれぞれ「隣の値より `PILE_UP_RATIO` 倍以上、かつ
    `MIN_PILE_UP` 行以上」出現していれば打ち切りと判定する。回転数 0 の行は
    休止台で差枚も 0 になるため除外する。
    """
    d = df[(df["games_normalized"] > 0) & df["diff_coins_normalized"].notna()]
    res: dict = {"lo": None, "hi": None, "n_rows": int(len(d))}
    if d.empty:
        return res
    vc = d["diff_coins_normalized"].value_counts().sort_index()
    if len(vc) < 3:
        return res

    for side, idx, nxt in (("lo", 0, 1), ("hi", -1, -2)):
        edge_v, edge_n = int(vc.index[idx]), int(vc.iloc[idx])
        neighbor_n = int(vc.iloc[nxt])
        if edge_n >= MIN_PILE_UP and edge_n >= PILE_UP_RATIO * neighbor_n:
            res[side] = {"value": edge_v, "count": edge_n, "neighbor_count": neighbor_n}
    return res
