"""
EDA Auto-Explorer — 全次元の総当たりスキャン
"""
from itertools import combinations

import pandas as pd

from .core import HALL_DBS, load_hall_df, scan_dimension

# スキャン対象の全次元
ALL_DIMENSIONS = [
    "day_of_week",    # 曜日
    "date_digit",     # 日付末尾 (0-9)
    "dd",             # 日付の日 (1-31)
    "dd_mod10",       # dd % 10 (4系/7系判定)
    "dd_group",       # '4系'/'7系'/'その他'
    "machine_digit",  # 台番号末尾 (0-9)
    "machine_name",   # 機種名
    "is_x_day",       # イベント日フラグ
    "is_weekend",     # 週末フラグ
    "is_any_event",   # 任意イベント日
    "weekday_nth",    # 第N曜日
]

# よく使うフィルタプリセット
FILTERS = {
    "all":          None,
    "x_day_only":   {"is_x_day": 1},
    "event_only":   {"is_any_event": 1},
    "weekend_only": {"is_weekend": 1},
    "non_event":    {"is_any_event": 0},
}

# 1次元スキャンでは値域が狭くスキップすべき二値フラグ列
_BINARY_DIMS = {"is_x_day", "is_weekend", "is_any_event", "is_month_start", "is_month_end"}


def full_scan(hall_name: str,
              max_dims: int = 2,
              min_n: int = 8,
              filters: dict = None,
              dimensions: list = None,
              verbose: bool = True) -> dict:
    """
    指定ホールで全次元組み合わせをスキャンし、Tier A/B が存在する結果のみ返す。

    Parameters
    ----------
    hall_name  : HALL_DBS のキー
    max_dims   : 最大次元数 (1 or 2 を推奨)
    min_n      : グループの最小観測数
    filters    : FILTERS プリセットの値 or dict 直指定
    dimensions : スキャンする列リスト（省略時は ALL_DIMENSIONS）
    verbose    : 進捗を表示するか

    Returns
    -------
    {dim_combo_str: result_DataFrame} の dict
    """
    dims = dimensions or ALL_DIMENSIONS

    if verbose:
        print(f"[full_scan] {hall_name} — データ読み込み中...")

    df = load_hall_df(hall_name)

    total = sum(len(list(combinations(dims, k))) for k in range(1, max_dims + 1))
    done = 0
    results = {}

    for n_dims in range(1, max_dims + 1):
        for combo in combinations(dims, n_dims):
            done += 1
            key = " × ".join(combo)

            # 二値フラグのみの1次元はスキップ
            if n_dims == 1 and combo[0] in _BINARY_DIMS:
                if verbose:
                    print(f"  [{done}/{total}] {key} — SKIP (binary)")
                continue

            if verbose:
                print(f"  [{done}/{total}] {key} ...", end=" ", flush=True)

            try:
                res = scan_dimension(
                    hall_name, list(combo),
                    filters=filters, min_n=min_n, df=df.copy()
                )
                if not res.empty and res["tier"].isin(["A", "B"]).any():
                    results[key] = res
                    if verbose:
                        a = (res["tier"] == "A").sum()
                        b = (res["tier"] == "B").sum()
                        print(f"TierA={a}, TierB={b}")
                else:
                    if verbose:
                        print("no signal")
            except Exception as e:
                if verbose:
                    print(f"ERROR: {e}")

    if verbose:
        print(f"\n✓ スキャン完了: {len(results)} / {total} 次元にシグナルあり")

    return results


def summarize_scan(scan_results: dict,
                   tier_filter: list = None) -> pd.DataFrame:
    """
    full_scan の結果から指定 Tier の行を抽出し avg_diff 降順で返す。

    Parameters
    ----------
    scan_results : full_scan() の戻り値
    tier_filter  : 抽出する Tier リスト。省略時は ['A', 'B']
    """
    if tier_filter is None:
        tier_filter = ["A", "B"]

    rows = []
    for dim_key, df in scan_results.items():
        subset = df[df["tier"].isin(tier_filter)].copy()
        subset["dimension"] = dim_key
        rows.append(subset)

    if not rows:
        print("指定 Tier のパターンが見つかりませんでした。")
        return pd.DataFrame()

    combined = pd.concat(rows, ignore_index=True)
    return combined.sort_values("avg_diff", ascending=False).reset_index(drop=True)


def cross_full_scan(group_cols: list,
                    halls: list = None,
                    filters: dict = None,
                    min_n: int = 5) -> pd.DataFrame:
    """指定次元を全ホールでスキャンし共通/固有パターンをフラグ付きで返す。"""
    from .core import cross_hall_scan
    return cross_hall_scan(
        group_cols=group_cols,
        filters=filters,
        min_n=min_n,
        halls=halls,
    )
