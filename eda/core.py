"""
EDA Core — データ読み込み・統計計算・Tier分類・ラグ分析

[2026-06-09 修正]
daily_hall_summary の日付フィーチャー列（day_of_week, is_x_day 等）は
date_info_calculator.py が全日付で実行されておらず大半がNULL。
load_hall_df ではこれらを daily_hall_summary JOIN に依存せず
machine_detailed_results.date 文字列から Python で直接計算する。
"""
import calendar as _cal
import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kruskal, spearmanr

warnings.filterwarnings("ignore")

DB_DIR = Path(__file__).parent.parent / "db"

HALL_DBS = {
    "みとや":        "みとや大森町店.db",
    "蒲田7":         "マルハンメガシティ2000-蒲田7.db",
    "蒲田1":         "マルハンメガシティ2000-蒲田1.db",
    "楽園":          "楽園蒲田店.db",
    "レイトギャップ": "レイトギャップ平和島.db",
    "ARROW":        "ARROW池上店.db",
    "ヒロキ":        "ヒロキ東口店.db",
    "ザシティ":      "ザ-シティ-ベルシティ雑色店.db",
    "金時":          "金時京急蒲田店.db",
}

# hall_config.json の event_digits（date_info_calculator に依存しない）
HALL_EVENT_DIGITS: dict = {
    "みとや":        [4, 14, 24, 7, 17, 27],
    "蒲田7":         [1, 11, 31, 7, 17, 27],
    "蒲田1":         [1, 11, 31, 22, 7, 17, 27],
    "楽園":          [11, 22],
    "レイトギャップ": [6, 16, 26],
    "ARROW":        [8, 18, 28, 11, 22],
    "ヒロキ":        [6, 16, 26],
    "ザシティ":      [5, 15, 25, 8, 18, 28],
    "金時":          [5, 15, 25, 20],
}

_WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日']
_WEEKDAY_EN = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

MIN_GAMES = 400  # この未満の台は除外


# ── 統計ヘルパー ──────────────────────────────────────────────────────────────

def _epsilon_squared(H: float, k: int, n: int) -> float:
    """Kruskal-Wallis 効果量 ε²。small≈0.01, medium≈0.06, large≈0.14"""
    if n <= k:
        return 0.0
    return max(0.0, (H - k + 1) / (n - k))


def _bootstrap_ci(values: np.ndarray, n_boot: int = 1000, ci: float = 95) -> tuple:
    """平均の Bootstrap 信頼区間 (lo, hi)。サンプル不足時は (nan, nan)。"""
    if len(values) < 3:
        return np.nan, np.nan
    rng = np.random.default_rng(42)
    means = [rng.choice(values, size=len(values), replace=True).mean()
             for _ in range(n_boot)]
    lo = (100 - ci) / 2
    return float(np.percentile(means, lo)), float(np.percentile(means, 100 - lo))


def _classify_tier(n: int, plus_rate: float, avg_diff: float,
                   p_value: float, epsilon_sq: float,
                   baseline_plus_rate: float = 50.0) -> str:
    """
    Tier A/B/C/Avoid/insufficient を返す。

    baseline_plus_rate を基準に相対判定するため、全機種集計でも正しく機能する。

    Tier A: 実行レベル  — n>=10, plus_rate>=baseline+15, avg_diff>300, p<0.10, e2>0.02
    Tier B: 参考レベル  — n>=5,  plus_rate>=baseline+5,  avg_diff>100
    Avoid:  回避推奨    — plus_rate<=baseline-10 and avg_diff<-200 (n>=5)
    C:      観察中
    """
    if n < 3:
        return "insufficient"
    if n >= 5 and plus_rate <= baseline_plus_rate - 10.0 and avg_diff < -200:
        return "Avoid"
    p_ok = np.isnan(p_value) or p_value < 0.10
    e_ok = np.isnan(epsilon_sq) or epsilon_sq > 0.02
    if n >= 10 and plus_rate >= baseline_plus_rate + 15.0 and avg_diff > 300 and p_ok and e_ok:
        return "A"
    if n >= 5 and plus_rate >= baseline_plus_rate + 5.0 and avg_diff > 100:
        return "B"
    return "C"


# ── データ読み込み ─────────────────────────────────────────────────────────────

def load_hall_df(hall_name: str) -> pd.DataFrame:
    """
    machine_detailed_results から台レベルデータを読み込み、
    日付フィーチャーを Python で直接計算して返す。
    games_normalized < MIN_GAMES の台は除外。

    [2026-06-09] daily_hall_summary の JOIN に依存しない設計に変更。
    day_of_week / is_x_day / is_weekend 等を m.date 文字列から計算。

    追加列:
      plus         : diff > 0 フラグ (0/1)
      year_month   : 'YYYYMM'
      dd           : 日付の日 (1-31)
      dd_mod10     : dd % 10
      date_digit   : dd % 10 (= dd_mod10, 旧来の名前を維持)
      dd_group     : '4系' / '7系' / 'その他'
      day_of_week  : '月'〜'日'
      weekday_nth  : 'Mon1'〜'Sun5'
      is_weekend   : 0/1
      is_x_day     : 0/1 (ホール固有イベント日)
      is_any_event : 0/1 (= is_weekend OR is_x_day)
      is_month_start/end : 0/1
      hall         : ホール名
    """
    if hall_name not in HALL_DBS:
        raise ValueError(f"不明なホール: {hall_name!r}. 利用可能: {list(HALL_DBS)}")

    db_path = DB_DIR / HALL_DBS[hall_name]
    conn = sqlite3.connect(db_path)

    # machine_detailed_results のみ使用（daily_hall_summary JOIN 廃止）
    query = f"""
    SELECT
        m.date,
        m.machine_name,
        m.machine_number,
        m.last_digit            AS machine_digit,
        m.diff_coins_normalized AS diff,
        m.games_normalized      AS games,
        m.is_zorome             AS machine_zorome,
        CAST(SUBSTR(m.date,7,2) AS INTEGER) AS dd
    FROM machine_detailed_results m
    WHERE m.games_normalized >= {MIN_GAMES}
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    # ── Python で日付フィーチャーを直接計算 ──────────────────────────────
    dates = pd.to_datetime(df["date"], format="%Y%m%d")
    wd    = dates.dt.weekday  # 0=月 … 6=日

    df["plus"]         = (df["diff"] > 0).astype(int)
    df["year_month"]   = df["date"].str[:6]
    df["dd_mod10"]     = df["dd"] % 10
    df["date_digit"]   = df["dd_mod10"]          # 旧来列名を維持
    df["dd_group"]     = df["dd"].apply(
        lambda x: "4系" if x % 10 == 4 else ("7系" if x % 10 == 7 else "その他")
    )

    df["day_of_week"]  = wd.map(lambda x: _WEEKDAY_JP[x])
    df["weekday_nth"]  = dates.apply(
        lambda d: f"{_WEEKDAY_EN[d.weekday()]}{(d.day - 1) // 7 + 1}"
    )
    df["is_weekend"]   = (wd >= 5).astype(int)

    event_digits       = HALL_EVENT_DIGITS.get(hall_name, [])
    df["is_x_day"]     = df["dd"].isin(event_digits).astype(int)
    df["is_any_event"] = ((df["is_weekend"] == 1) | (df["is_x_day"] == 1)).astype(int)

    month_end = dates.apply(
        lambda d: _cal.monthrange(d.year, d.month)[1]
    )
    df["is_month_start"] = (df["dd"] == 1).astype(int)
    df["is_month_end"]   = (df["dd"] == month_end.values).astype(int)

    df["hall"] = hall_name

    return df


# ── 次元スキャン ──────────────────────────────────────────────────────────────

def scan_dimension(hall_name: str,
                   group_cols: list,
                   filters: dict = None,
                   min_n: int = 5,
                   df: pd.DataFrame = None) -> pd.DataFrame:
    """
    指定次元の組み合わせを集計し、Tier・統計量付きの結果を返す。

    Parameters
    ----------
    hall_name  : HALL_DBS のキー
    group_cols : グループ化列リスト、例 ['day_of_week', 'date_digit']
    filters    : 行フィルタ dict、例 {'is_x_day': 1}
    min_n      : グループの最小観測数
    df         : 事前読み込み済み DataFrame（省略時は自動読込）

    Returns
    -------
    avg_diff 降順の DataFrame（Tier・p値・ε²・Bootstrap CI・Spearman ρ 付き）
    """
    if df is None:
        df = load_hall_df(hall_name)
    else:
        df = df.copy()

    if filters:
        for col, val in filters.items():
            if col in df.columns:
                df = df[df[col] == val]

    if df.empty:
        return pd.DataFrame()

    # ホール全体の baseline plus_rate を計算（相対Tier判定に使用）
    baseline_plus_rate = float((df["diff"] > 0).mean() * 100)

    # 集計
    agg = (
        df.groupby(group_cols)
        .agg(
            n           = ("diff", "count"),
            avg_diff    = ("diff", "mean"),
            median_diff = ("diff", "median"),
            std_diff    = ("diff", "std"),
            plus_rate   = ("plus", "mean"),
        )
        .reset_index()
    )

    agg["plus_rate"]   = (agg["plus_rate"] * 100).round(1)
    agg["avg_diff"]    = agg["avg_diff"].round(0).astype(int)
    agg["median_diff"] = agg["median_diff"].round(0).astype(int)
    agg = agg[agg["n"] >= min_n].copy()

    if agg.empty:
        return pd.DataFrame()

    # Kruskal-Wallis（次元全体の有意性）
    group_arrays = [
        grp["diff"].values
        for _, grp in df.groupby(group_cols)
        if len(grp) >= 2
    ]
    if len(group_arrays) >= 2:
        try:
            H, p_value = kruskal(*group_arrays)
            k      = len(group_arrays)
            n_total = sum(len(g) for g in group_arrays)
            eps_sq  = _epsilon_squared(H, k, n_total)
        except Exception:
            H, p_value, eps_sq = np.nan, np.nan, np.nan
    else:
        H, p_value, eps_sq = np.nan, np.nan, np.nan

    agg["kruskal_H"]  = round(H, 3)      if not np.isnan(H)       else np.nan
    agg["p_value"]    = round(p_value, 4) if not np.isnan(p_value) else np.nan
    agg["epsilon_sq"] = round(eps_sq, 4)  if not np.isnan(eps_sq)  else np.nan

    # Bootstrap CI（グループごと）
    ci_los, ci_his = [], []
    for _, row in agg.iterrows():
        mask = pd.Series(True, index=df.index)
        for col in group_cols:
            mask &= df[col] == row[col]
        vals = df.loc[mask, "diff"].values
        lo, hi = _bootstrap_ci(vals)
        ci_los.append(int(lo) if not np.isnan(lo) else np.nan)
        ci_his.append(int(hi) if not np.isnan(hi) else np.nan)

    agg["ci_lo"] = ci_los
    agg["ci_hi"] = ci_his

    # Spearman 月間安定性（グループごと）
    months = sorted(df["year_month"].unique())
    spearman_rhos = []
    if len(months) >= 3:
        for _, row in agg.iterrows():
            mask = pd.Series(True, index=df.index)
            for col in group_cols:
                mask &= df[col] == row[col]
            monthly = df[mask].groupby("year_month")["diff"].mean()
            if len(monthly) >= 3:
                rho, _ = spearmanr(range(len(monthly)), monthly.values)
                spearman_rhos.append(round(rho, 3))
            else:
                spearman_rhos.append(np.nan)
    else:
        spearman_rhos = [np.nan] * len(agg)

    agg["spearman_rho"] = spearman_rhos

    # Tier 分類（ホール baseline plus_rate を基準に相対判定）
    agg["baseline_plus_rate"] = round(baseline_plus_rate, 1)
    agg["tier"] = agg.apply(
        lambda r: _classify_tier(
            r["n"], r["plus_rate"], r["avg_diff"], r["p_value"], r["epsilon_sq"],
            baseline_plus_rate=baseline_plus_rate,
        ),
        axis=1,
    )

    agg["hall"] = hall_name

    return agg.sort_values("avg_diff", ascending=False).reset_index(drop=True)


# ── クロスホール比較 ───────────────────────────────────────────────────────────

def cross_hall_scan(group_cols: list,
                    filters: dict = None,
                    min_n: int = 5,
                    halls: list = None) -> pd.DataFrame:
    """
    複数ホールで同一次元をスキャンし、共通・固有パターンを判定する。

    追加列:
      pattern_key    : group_cols 値を '_' 結合した文字列
      n_halls_tier_ab: Tier A/B を示すホール数
      universality   : 'universal'(2+ホール) / 'hall_specific'(1ホール)
    """
    if halls is None:
        halls = list(HALL_DBS.keys())

    results = []
    for hall in halls:
        print(f"  {hall} ...", end=" ", flush=True)
        try:
            raw = load_hall_df(hall)
            res = scan_dimension(hall, group_cols, filters=filters, min_n=min_n, df=raw)
            if not res.empty:
                results.append(res)
            print("OK")
        except Exception as e:
            print(f"SKIP ({e})")

    if not results:
        return pd.DataFrame()

    combined = pd.concat(results, ignore_index=True)

    combined["pattern_key"] = combined[group_cols].apply(
        lambda r: "_".join(str(r[c]) for c in group_cols), axis=1
    )

    ab_counts = (
        combined[combined["tier"].isin(["A", "B"])]
        .groupby("pattern_key")["hall"]
        .nunique()
    )
    combined["n_halls_tier_ab"] = (
        combined["pattern_key"].map(ab_counts).fillna(0).astype(int)
    )
    combined["universality"] = combined["n_halls_tier_ab"].apply(
        lambda x: "universal" if x >= 2 else "hall_specific"
    )

    return combined.sort_values(
        ["n_halls_tier_ab", "avg_diff"], ascending=[False, False]
    ).reset_index(drop=True)


# ── ラグ分析（据え・上げ・リバウンド）─────────────────────────────────────────

def lag_analysis(hall_name: str,
                 group_col: str,
                 lag: int = 1,
                 min_n: int = 5) -> pd.DataFrame:
    """
    前日→翌日の連続性を分析する（据え・上げ・リバウンド検証）。

    Returns
    -------
    group_col 別の遷移統計:
      avg_diff_after_plus  : 前日プラス翌日の平均差枚
      streak_rate          : 前日プラス→翌日プラスになる確率 (%)
      avg_diff_after_minus : 前日マイナス翌日の平均差枚
      rebound_rate         : 前日マイナス→翌日プラスになる確率 (%) ← リバウンド
    """
    df = load_hall_df(hall_name)

    daily = (
        df.groupby(["date", group_col])
        .agg(avg_diff=("diff", "mean"), n=("diff", "count"))
        .reset_index()
    )
    daily = daily[daily["n"] >= min_n].sort_values("date")

    daily["prev_diff"] = daily.groupby(group_col)["avg_diff"].shift(lag)
    daily["prev_plus"] = (daily["prev_diff"] > 0).astype(float)
    daily = daily.dropna(subset=["prev_diff"])

    rows = []
    for val, grp in daily.groupby(group_col):
        after_plus  = grp[grp["prev_plus"] == 1]["avg_diff"]
        after_minus = grp[grp["prev_plus"] == 0]["avg_diff"]

        rows.append({
            group_col:               val,
            "n_transitions":         len(grp),
            "n_after_plus":          len(after_plus),
            "avg_diff_after_plus":   round(after_plus.mean(), 0)       if len(after_plus)  >= 3 else np.nan,
            "streak_rate":           round((after_plus  > 0).mean() * 100, 1) if len(after_plus)  >= 3 else np.nan,
            "n_after_minus":         len(after_minus),
            "avg_diff_after_minus":  round(after_minus.mean(), 0)      if len(after_minus) >= 3 else np.nan,
            "rebound_rate":          round((after_minus > 0).mean() * 100, 1) if len(after_minus) >= 3 else np.nan,
        })

    result = pd.DataFrame(rows).sort_values("rebound_rate", ascending=False)
    result["hall"] = hall_name
    return result.reset_index(drop=True)


# ── 導入日フィーチャー ─────────────────────────────────────────────────────────

def compute_debut_features(df: pd.DataFrame,
                           db_start_grace_days: int = 0) -> pd.DataFrame:
    """
    ホール別の「機種初登場日（debut）」を付与する。

    DBの最初の日付から db_start_grace_days 以内に初登場した機種は
    「DBスタート時に既存だった機種」として pre_existing=True に設定し、
    days_since_debut を NaN にする（分析から除外可能にする）。

    追加列
    ------
    debut_date      : 機種のホール内初登場日（YYYYMMDD文字列）
    days_since_debut: 初登場からの経過日数（pre_existing は NaN）
    pre_existing    : DBスタート時点で既存だった機種か (bool)
    machine_count   : その日のホール内設置台数（同機種のユニーク台番号数）

    Parameters
    ----------
    df                  : load_hall_df の出力（hall 列必須）
    db_start_grace_days : DB最初の日付から何日以内をpre_existingとするか
    """
    df = df.copy()

    # ── DB開始日（ホール全体の最古日付）──
    db_start = pd.to_datetime(df["date"], format="%Y%m%d").min()

    # ── 機種ごとの初登場日（ホール内） ──
    debut_map = (
        df.groupby("machine_name")["date"]
        .min()
        .reset_index()
        .rename(columns={"date": "debut_date"})
    )
    df = df.merge(debut_map, on="machine_name", how="left")

    # ── 日付変換 ──
    df["date_dt"]    = pd.to_datetime(df["date"],        format="%Y%m%d")
    df["debut_dt"]   = pd.to_datetime(df["debut_date"],  format="%Y%m%d")

    # ── pre_existing フラグ ──
    df["pre_existing"] = (df["debut_dt"] - db_start).dt.days <= db_start_grace_days

    # ── days_since_debut (pre_existing は NaN) ──
    days = (df["date_dt"] - df["debut_dt"]).dt.days
    df["days_since_debut"] = days.where(~df["pre_existing"], other=np.nan)

    # ── machine_count：その日・同機種のユニーク台番号数 ──
    mc = (
        df.groupby(["date", "machine_name"])["machine_number"]
        .nunique()
        .reset_index()
        .rename(columns={"machine_number": "machine_count"})
    )
    df = df.merge(mc, on=["date", "machine_name"], how="left")

    df = df.drop(columns=["date_dt", "debut_dt"])
    return df


# ── ANOMALY 検出 ───────────────────────────────────────────────────────────────

def anomaly_detection(hall_name: str,
                      baseline_days: int = 30,
                      min_games: int = 1000,
                      anomaly_threshold: float = 2.0,
                      min_baseline_obs: int = 10,
                      db_start_grace_days: int = 0,
                      df: pd.DataFrame = None) -> pd.DataFrame:
    """
    台レベルで「直近N日ベースラインから大幅に逸脱した日」を検出する。

    アルゴリズム
    ------------
    1. 台ごと（machine_number）に前日までの rolling_mean / rolling_std を計算
    2. anomaly_score = (今日のdiff - rolling_mean) / rolling_std
    3. anomaly_score >= anomaly_threshold かつ games >= min_games を is_anomaly とする
    4. days_since_debut / machine_count / pre_existing を付与

    ベースラインは shift(1) で計算するため当日データのリークはない。

    Returns
    -------
    全行（is_anomaly=True/False 両方）の DataFrame。
    カラム:
      date, machine_name, machine_number, diff, games,
      baseline_mean, baseline_std, anomaly_score, is_anomaly,
      days_since_debut, pre_existing, machine_count,
      days_since_debut_bucket (導入日数帯ラベル)
    """
    if df is None:
        df = load_hall_df(hall_name)
    else:
        df = df.copy()

    # ── 導入日フィーチャーを付与 ──
    df = compute_debut_features(df, db_start_grace_days=db_start_grace_days)

    # ── 台ごとに日付ソート ──
    df = df.sort_values(["machine_number", "date"]).reset_index(drop=True)

    # ── rolling baseline（前日までのN日間） ──
    baseline_mean_list = []
    baseline_std_list  = []

    for mn, grp in df.groupby("machine_number", sort=False):
        diff_series = grp["diff"].reset_index(drop=True)
        rolled_mean = (
            diff_series
            .shift(1)
            .rolling(window=baseline_days, min_periods=min_baseline_obs)
            .mean()
        )
        rolled_std = (
            diff_series
            .shift(1)
            .rolling(window=baseline_days, min_periods=min_baseline_obs)
            .std()
        )
        baseline_mean_list.append(rolled_mean)
        baseline_std_list.append(rolled_std)

    df["baseline_mean"] = pd.concat(baseline_mean_list).values
    df["baseline_std"]  = pd.concat(baseline_std_list).values

    # ── anomaly_score ──
    # std=0 （全日同値）は NaN に
    df["baseline_std"] = df["baseline_std"].replace(0, np.nan)
    df["anomaly_score"] = (
        (df["diff"] - df["baseline_mean"]) / df["baseline_std"]
    ).round(2)

    # ── is_anomaly フラグ ──
    df["is_anomaly"] = (
        (df["anomaly_score"] >= anomaly_threshold)
        & (df["games"] >= min_games)
        & df["anomaly_score"].notna()
    )

    # ── days_since_debut_bucket ──
    bins   = [-1, 7, 14, 30, 60, 90, 180, 365, 9999]
    labels = ["0-7日", "8-14日", "15-30日", "31-60日",
              "61-90日", "91-180日", "181-365日", "365日超"]
    df["days_since_debut_bucket"] = pd.cut(
        df["days_since_debut"], bins=bins, labels=labels
    )

    # 必要列のみ返す
    keep = [
        "date", "machine_name", "machine_number",
        "diff", "games", "plus",
        "day_of_week", "dd", "dd_group", "is_x_day", "is_any_event",
        "baseline_mean", "baseline_std", "anomaly_score", "is_anomaly",
        "days_since_debut", "days_since_debut_bucket",
        "pre_existing", "machine_count",
        "debut_date",
    ]
    keep = [c for c in keep if c in df.columns]
    return df[keep].sort_values(["date", "machine_number"]).reset_index(drop=True)
