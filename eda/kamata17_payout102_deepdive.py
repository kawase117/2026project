"""
蒲田1・蒲田7(payout_rate>=102%)の深堀り検証

[[strategy1-9hall-validation]] で「蒲田1・蒲田7は法則①(diff_std>=median &
payout_rate>=102%)が日曜限定でsplit-half頑健」と確定したが、以下4点を
追加検証する。

1. 候補機種の内訳分析: 戦略1候補(diff_std>=median & payout>=102%)に
   毎週ヒットする機種は固定的か、ローテーションするか。
2. 日曜限定の妥当性検証: 他の曜日でも同様の効果があるか(曜日別に
   walk-forwardのQ5-Q1を算出)。
3. 蒲田1+蒲田7統合での増サンプル検証: 2ホールをpoolしてQ5-Q1の
   ブートストラップ信頼区間を算出する。
4. 直近データでのOOSテスト: 直近25%期間をholdoutとして切り出し、
   102%ルールが直近でも再現するか確認する。
"""
import sqlite3
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

DB_DIR = Path(__file__).resolve().parents[1] / "db"

COINS_PER_GAME = 3
MIN_DAYS = 10
PAYOUT_TH = 102

HALLS = {
    "蒲田1": "マルハンメガシティ2000-蒲田1",
    "蒲田7": "マルハンメガシティ2000-蒲田7",
}

WEEKDAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"]


def load_at_machines(db_name: str) -> pd.DataFrame:
    db_path = DB_DIR / f"{db_name}.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    master = pd.read_sql_query(
        "SELECT machine_name_normalized AS machine_name, jug_flag, hana_flag, "
        "oki_flag, bt_flag FROM machine_master",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df.merge(master, on="machine_name", how="left")
    is_at = (
        (df["jug_flag"].fillna(0) == 0)
        & (df["hana_flag"].fillna(0) == 0)
        & (df["oki_flag"].fillna(0) == 0)
        & (df["bt_flag"].fillna(0) == 0)
    )
    df["dow"] = df["date"].dt.dayofweek
    return df[is_at].copy()


def compute_history_agg(hist: pd.DataFrame) -> pd.DataFrame:
    agg = (
        hist.groupby("machine_name")
        .agg(
            diff_sum=("diff_coins_normalized", "sum"),
            games_sum=("games_normalized", "sum"),
            n_days=("diff_coins_normalized", "size"),
        )
    )
    agg = agg[agg["n_days"] >= MIN_DAYS].copy()
    if agg.empty:
        return agg
    agg["payout_rate"] = (
        (agg["games_sum"] * COINS_PER_GAME + agg["diff_sum"])
        / (agg["games_sum"] * COINS_PER_GAME)
        * 100
    )
    daily_std = (
        hist.groupby(["machine_name", "date"])["diff_coins_normalized"]
        .sum()
        .groupby("machine_name")
        .std()
    )
    agg["diff_std"] = daily_std
    return agg


def run_backtest(
    sub: pd.DataFrame,
    payout_th: int = PAYOUT_TH,
    exclude_machines: tuple = (),
    return_candidates: bool = False,
) -> pd.DataFrame:
    """walk-forwardで戦略1(diff_std>=median & payout>=payout_th)候補を抽出"""
    dates = sorted(sub["date"].unique())
    results = []
    candidate_sets = {}

    for target_date in dates:
        hist = sub[sub["date"] < target_date]
        if hist["date"].nunique() < MIN_DAYS:
            continue
        agg = compute_history_agg(hist)
        if len(agg) < 5:
            continue

        today = sub[sub["date"] == target_date]
        today_agg = today.groupby("machine_name")["diff_coins_normalized"].sum()
        if len(today_agg) < 5:
            continue
        quintile = pd.qcut(today_agg, 5, labels=False, duplicates="drop") + 1

        median_std = agg["diff_std"].median()
        cand = agg[(agg["diff_std"] >= median_std) & (agg["payout_rate"] >= payout_th)]
        cand_names = [m for m in cand.index if m not in exclude_machines]
        candidate_sets[target_date] = set(cand_names)
        for mname in cand_names:
            if mname in quintile.index:
                results.append({
                    "date": target_date,
                    "machine_name": mname,
                    "quintile": quintile.loc[mname],
                })

    res_df = pd.DataFrame(results)
    if return_candidates:
        return res_df, candidate_sets
    return res_df


def summarize(res_df: pd.DataFrame, label: str) -> str:
    if res_df.empty or len(res_df) < 10:
        return f"  [{label}] n={len(res_df)} (不足)"
    n = len(res_df)
    q1 = (res_df["quintile"] == 1).mean()
    q5 = (res_df["quintile"] == 5).mean()
    return f"  [{label}] n={n}, Q1={q1:.3f}, Q5={q5:.3f}, Q5-Q1={q5-q1:+.3f}"


# ---------------------------------------------------------------------------
# 1. 候補機種の内訳分析(日曜)
# ---------------------------------------------------------------------------
def analyze_candidate_breakdown(name: str, sub_sun: pd.DataFrame) -> None:
    print(f"\n--- [1] 候補機種内訳 ({name}, 日曜) ---")
    res = run_backtest(sub_sun)
    if res.empty:
        print("  候補なし")
        return
    counts = Counter(res["machine_name"])
    n_weeks = res["date"].nunique()
    total = len(res)
    print(f"  対象週数={n_weeks}, 候補延べ数={total}, ユニーク機種数={len(counts)}")
    by_machine = res.groupby("machine_name").agg(
        n=("quintile", "size"),
        q5_rate=("quintile", lambda x: (x == 5).mean()),
        q1_rate=("quintile", lambda x: (x == 1).mean()),
    ).sort_values("n", ascending=False)
    for mname, row in by_machine.head(10).iterrows():
        coverage = row["n"] / n_weeks
        print(f"    {mname[:30]:30s} n={int(row['n']):3d} ({coverage:.0%}週) "
              f"Q5={row['q5_rate']:.2f} Q1={row['q1_rate']:.2f}")
    top1_share = by_machine["n"].iloc[0] / total if not by_machine.empty else 0
    print(f"  最頻出機種の占有率: {top1_share:.1%}")


# ---------------------------------------------------------------------------
# 2. 日曜限定の妥当性検証(曜日別Q5-Q1)
# ---------------------------------------------------------------------------
def analyze_by_weekday(name: str, df_all: pd.DataFrame) -> None:
    print(f"\n--- [2] 曜日別 Q5-Q1 ({name}, payout>={PAYOUT_TH}%) ---")
    for dow in range(7):
        sub = df_all[df_all["dow"] == dow].copy()
        if sub["date"].nunique() < MIN_DAYS + 5:
            print(f"  {WEEKDAY_NAMES[dow]}曜: データ不足({sub['date'].nunique()}日)")
            continue
        res = run_backtest(sub)
        label = f"{WEEKDAY_NAMES[dow]}曜 (対象{sub['date'].nunique()}日)"
        print(summarize(res, label))


# ---------------------------------------------------------------------------
# 3. 蒲田1+蒲田7 統合(日曜) ブートストラップCI
# ---------------------------------------------------------------------------
def bootstrap_ci(res_df: pd.DataFrame, n_boot: int = 2000, seed: int = 42) -> tuple:
    rng = np.random.default_rng(seed)
    n = len(res_df)
    is_q5 = (res_df["quintile"] == 5).to_numpy()
    is_q1 = (res_df["quintile"] == 1).to_numpy()
    diffs = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        diffs.append(is_q5[idx].mean() - is_q1[idx].mean())
    diffs = np.array(diffs)
    return np.percentile(diffs, 2.5), np.percentile(diffs, 97.5)


def analyze_pooled(sub_k1: pd.DataFrame, sub_k7: pd.DataFrame) -> None:
    print("\n--- [3] 蒲田1+蒲田7 統合(日曜) ブートストラップCI ---")
    res1 = run_backtest(sub_k1)
    res7 = run_backtest(sub_k7)
    print(summarize(res1, "蒲田1単独"))
    print(summarize(res7, "蒲田7単独"))
    pooled = pd.concat([res1, res7], ignore_index=True)
    print(summarize(pooled, "統合"))
    if len(pooled) >= 10:
        q1 = (pooled["quintile"] == 1).mean()
        q5 = (pooled["quintile"] == 5).mean()
        lo, hi = bootstrap_ci(pooled)
        print(f"  Q5-Q1={q5-q1:+.3f}, 95%CI=[{lo:+.3f}, {hi:+.3f}]"
              + (" (0を含まず有意)" if lo > 0 or hi < 0 else " (0を含み有意でない)"))


# ---------------------------------------------------------------------------
# 4. 直近データでのOOSテスト(日曜、直近25%をholdout)
# ---------------------------------------------------------------------------
def analyze_recent_oos(name: str, sub_sun: pd.DataFrame) -> None:
    print(f"\n--- [4] 直近OOSテスト ({name}, 日曜, 直近25%) ---")
    dates = sorted(sub_sun["date"].unique())
    n = len(dates)
    if n < MIN_DAYS + 8:
        print(f"  データ不足({n}日)")
        return
    cutoff_idx = int(n * 0.75)
    cutoff_date = dates[cutoff_idx]
    train = sub_sun[sub_sun["date"] < cutoff_date]
    recent = sub_sun[sub_sun["date"] >= cutoff_date]
    print(f"  全{n}日 / 学習期間{train['date'].nunique()}日 / "
          f"直近holdout{recent['date'].nunique()}日 (cutoff={cutoff_date.date()})")
    res_full = run_backtest(sub_sun)
    res_recent = run_backtest(recent)
    print(summarize(res_full, "全期間"))
    print(summarize(res_recent, "直近25%のみ"))


# ---------------------------------------------------------------------------
# 5. 全曜日pooled検証(蒲田1単独/蒲田7単独/統合)
# ---------------------------------------------------------------------------
def analyze_all_weekday_pooled(data: dict) -> None:
    print("\n--- [5] 全曜日pooled検証 ---")
    res1 = run_backtest(data["蒲田1"])
    res7 = run_backtest(data["蒲田7"])
    print(summarize(res1, "蒲田1単独(全曜日)"))
    print(summarize(res7, "蒲田7単独(全曜日)"))
    for name, res in [("蒲田1", res1), ("蒲田7", res7)]:
        if len(res) >= 10:
            q1 = (res["quintile"] == 1).mean()
            q5 = (res["quintile"] == 5).mean()
            lo, hi = bootstrap_ci(res)
            print(f"    {name} Q5-Q1={q5-q1:+.3f}, 95%CI=[{lo:+.3f}, {hi:+.3f}]"
                  + (" (有意)" if lo > 0 or hi < 0 else " (有意でない)"))

    pooled = pd.concat([res1, res7], ignore_index=True)
    print(summarize(pooled, "蒲田1+蒲田7 統合(全曜日)"))
    if len(pooled) >= 10:
        q1 = (pooled["quintile"] == 1).mean()
        q5 = (pooled["quintile"] == 5).mean()
        lo, hi = bootstrap_ci(pooled)
        print(f"    統合 Q5-Q1={q5-q1:+.3f}, 95%CI=[{lo:+.3f}, {hi:+.3f}]"
              + (" (有意)" if lo > 0 or hi < 0 else " (有意でない)"))


# ---------------------------------------------------------------------------
# 6. 候補集合のローテーション予測可能性(週次persistence)
# ---------------------------------------------------------------------------
def analyze_candidate_persistence(name: str, sub_sun: pd.DataFrame) -> None:
    print(f"\n--- [6] 候補集合の週次persistence ({name}, 日曜) ---")
    _, cand_sets = run_backtest(sub_sun, return_candidates=True)
    dates = sorted(cand_sets.keys())
    if len(dates) < 2:
        print("  データ不足")
        return
    overlaps = []
    jaccards = []
    for prev, curr in zip(dates[:-1], dates[1:]):
        s_prev, s_curr = cand_sets[prev], cand_sets[curr]
        if not s_prev or not s_curr:
            continue
        inter = s_prev & s_curr
        union = s_prev | s_curr
        overlaps.append(len(inter) / len(s_prev))
        jaccards.append(len(inter) / len(union))
    print(f"  週数={len(dates)}, 平均候補数={sum(len(s) for s in cand_sets.values())/len(dates):.1f}")
    print(f"  前週候補のうち翌週も残存する割合(平均): {sum(overlaps)/len(overlaps):.1%}")
    print(f"  Jaccard類似度(平均): {sum(jaccards)/len(jaccards):.1%}")


# ---------------------------------------------------------------------------
# 7. 蒲田7: モンキーターンV除外時のQ5-Q1
# ---------------------------------------------------------------------------
def analyze_kamata7_excl_monkeyturn(sub_sun: pd.DataFrame, sub_all: pd.DataFrame) -> None:
    print("\n--- [7] 蒲田7: モンキーターンV除外時のQ5-Q1 ---")
    target = "モンキーターンV"

    res_sun_with = run_backtest(sub_sun)
    res_sun_excl = run_backtest(sub_sun, exclude_machines=(target,))
    print(summarize(res_sun_with, "日曜・含む"))
    print(summarize(res_sun_excl, "日曜・除外"))

    res_all_with = run_backtest(sub_all)
    res_all_excl = run_backtest(sub_all, exclude_machines=(target,))
    print(summarize(res_all_with, "全曜日・含む"))
    print(summarize(res_all_excl, "全曜日・除外"))


# ---------------------------------------------------------------------------
# 8. 全曜日pooledでの直近OOSテスト(モンキーターンV除外版含む)
# ---------------------------------------------------------------------------
def split_recent(sub: pd.DataFrame, frac: float = 0.75) -> tuple:
    dates = sorted(sub["date"].unique())
    cutoff_idx = int(len(dates) * frac)
    cutoff_date = dates[cutoff_idx]
    recent = sub[sub["date"] >= cutoff_date].copy()
    return recent, cutoff_date


def analyze_all_weekday_recent_oos(data: dict) -> None:
    print("\n--- [8] 全曜日pooledでの直近OOSテスト ---")

    recent_sets = {}
    for name, sub_all in data.items():
        recent, cutoff = split_recent(sub_all)
        recent_sets[name] = recent
        n_total = sub_all["date"].nunique()
        n_recent = recent["date"].nunique()
        print(f"\n  [{name}] 全{n_total}日 / 直近holdout{n_recent}日 (cutoff={cutoff.date()})")

        res_full = run_backtest(sub_all)
        res_recent = run_backtest(recent)
        print(summarize(res_full, "全期間"))
        print(summarize(res_recent, "直近25%のみ"))

        if name == "蒲田7":
            target = "モンキーターンV"
            res_full_excl = run_backtest(sub_all, exclude_machines=(target,))
            res_recent_excl = run_backtest(recent, exclude_machines=(target,))
            print(summarize(res_full_excl, "全期間・モンキーターンV除外"))
            print(summarize(res_recent_excl, "直近25%のみ・モンキーターンV除外"))

    # 統合(直近holdoutをpool)
    print("\n  [統合・直近holdout]")
    pooled_recent = pd.concat(
        [run_backtest(recent_sets["蒲田1"]), run_backtest(recent_sets["蒲田7"])],
        ignore_index=True,
    )
    print(summarize(pooled_recent, "統合・直近25%"))
    if len(pooled_recent) >= 10:
        q1 = (pooled_recent["quintile"] == 1).mean()
        q5 = (pooled_recent["quintile"] == 5).mean()
        lo, hi = bootstrap_ci(pooled_recent)
        print(f"    Q5-Q1={q5-q1:+.3f}, 95%CI=[{lo:+.3f}, {hi:+.3f}]"
              + (" (有意)" if lo > 0 or hi < 0 else " (有意でない)"))

    pooled_recent_excl = pd.concat(
        [
            run_backtest(recent_sets["蒲田1"]),
            run_backtest(recent_sets["蒲田7"], exclude_machines=("モンキーターンV",)),
        ],
        ignore_index=True,
    )
    print(summarize(pooled_recent_excl, "統合・直近25%・モンキーターンV除外"))
    if len(pooled_recent_excl) >= 10:
        q1 = (pooled_recent_excl["quintile"] == 1).mean()
        q5 = (pooled_recent_excl["quintile"] == 5).mean()
        lo, hi = bootstrap_ci(pooled_recent_excl)
        print(f"    Q5-Q1={q5-q1:+.3f}, 95%CI=[{lo:+.3f}, {hi:+.3f}]"
              + (" (有意)" if lo > 0 or hi < 0 else " (有意でない)"))


# ---------------------------------------------------------------------------
# 9. 実用可能4ホールの候補機種リスト重複確認
# ---------------------------------------------------------------------------
X_DDS = [4, 7, 14, 17, 24, 27]


def load_xgroup_all_machines(db_name: str) -> pd.DataFrame:
    db_path = DB_DIR / f"{db_name}.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT date, machine_name, diff_coins_normalized, "
        "games_normalized FROM machine_detailed_results",
        conn,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["dd"] = df["date"].dt.day
    return df[df["dd"].isin(X_DDS)].copy()


def candidate_set_full_period(hist: pd.DataFrame, payout_th: int) -> set:
    agg = compute_history_agg(hist)
    if agg.empty:
        return set()
    median_std = agg["diff_std"].median()
    cand = agg[(agg["diff_std"] >= median_std) & (agg["payout_rate"] >= payout_th)]
    return set(cand.index)


def analyze_candidate_overlap(data: dict) -> None:
    print("\n--- [9] 実用可能4ホールの候補機種リスト重複確認 ---")

    cand_sets = {
        "蒲田1": candidate_set_full_period(data["蒲田1"], payout_th=102),
        "蒲田7": candidate_set_full_period(data["蒲田7"], payout_th=102),
        "みとや": candidate_set_full_period(load_xgroup_all_machines("みとや大森町店"), payout_th=100),
        "楽園蒲田": candidate_set_full_period(load_xgroup_all_machines("楽園蒲田店"), payout_th=100),
    }

    for name, s in cand_sets.items():
        print(f"  {name}: 候補{len(s)}機種")

    names = list(cand_sets.keys())
    print("\n  -- ペアごとの重複(機種名一致数) --")
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            inter = cand_sets[a] & cand_sets[b]
            print(f"  {a} ∩ {b}: {len(inter)}機種"
                  + (f" -> {sorted(inter)}" if inter else ""))

    print("\n  -- 3ホール以上で重複する機種 --")
    from collections import Counter
    counter = Counter()
    for s in cand_sets.values():
        for m in s:
            counter[m] += 1
    multi = {m: c for m, c in counter.items() if c >= 3}
    if multi:
        for m, c in sorted(multi.items(), key=lambda x: -x[1]):
            print(f"    {m}: {c}ホールで候補")
    else:
        print("    なし")


# ---------------------------------------------------------------------------
# 10. 実用可能4ホール(蒲田1・蒲田7・みとや・楽園蒲田)統合walk-forward
# ---------------------------------------------------------------------------
def analyze_4hall_pooled(data: dict) -> None:
    print("\n--- [10] 実用可能4ホール統合walk-forward(各ホールの推奨ルール) ---")

    res_k1 = run_backtest(data["蒲田1"], payout_th=102)
    res_k7 = run_backtest(data["蒲田7"], payout_th=102)
    res_mitoya = run_backtest(load_xgroup_all_machines("みとや大森町店"), payout_th=100)
    res_rakuen = run_backtest(load_xgroup_all_machines("楽園蒲田店"), payout_th=100)

    results = {
        "蒲田1(全曜日, payout>=102%)": res_k1,
        "蒲田7(全曜日, payout>=102%)": res_k7,
        "みとや(Xgroup, payout>=100%)": res_mitoya,
        "楽園蒲田(Xgroup, payout>=100%)": res_rakuen,
    }
    for label, res in results.items():
        print(summarize(res, label))
        if len(res) >= 10:
            q1 = (res["quintile"] == 1).mean()
            q5 = (res["quintile"] == 5).mean()
            lo, hi = bootstrap_ci(res)
            print(f"    95%CI=[{lo:+.3f}, {hi:+.3f}]"
                  + (" (有意)" if lo > 0 or hi < 0 else " (有意でない)"))

    pooled = pd.concat(list(results.values()), ignore_index=True)
    print()
    print(summarize(pooled, "4ホール統合"))
    if len(pooled) >= 10:
        q1 = (pooled["quintile"] == 1).mean()
        q5 = (pooled["quintile"] == 5).mean()
        lo, hi = bootstrap_ci(pooled)
        print(f"    95%CI=[{lo:+.3f}, {hi:+.3f}]"
              + (" (有意)" if lo > 0 or hi < 0 else " (有意でない)"))


# ---------------------------------------------------------------------------
# 11. 機種別Q1/Q5滞在率(全曜日, 候補集合内訳)
# ---------------------------------------------------------------------------
def analyze_machine_level_reliability(data: dict) -> None:
    print("\n--- [11] 機種別Q1/Q5滞在率(全曜日, payout>=102%候補) ---")

    rules = {
        "蒲田1": (data["蒲田1"], 102),
        "蒲田7": (data["蒲田7"], 102),
    }

    for name, (sub, payout_th) in rules.items():
        res = run_backtest(sub, payout_th=payout_th)
        if res.empty:
            continue
        by_machine = res.groupby("machine_name").agg(
            n=("quintile", "size"),
            q5_rate=("quintile", lambda x: (x == 5).mean()),
            q1_rate=("quintile", lambda x: (x == 1).mean()),
        )
        by_machine["q5_minus_q1"] = by_machine["q5_rate"] - by_machine["q1_rate"]
        by_machine = by_machine[by_machine["n"] >= 20]

        print(f"\n  [{name}] (n>=20機種のみ, {len(by_machine)}機種)")
        print("  -- Q1滞在率が低い順(Top5) --")
        for mname, row in by_machine.sort_values("q1_rate").head(5).iterrows():
            print(f"    {mname[:28]:28s} n={int(row['n']):4d} "
                  f"Q1={row['q1_rate']:.3f} Q5={row['q5_rate']:.3f} "
                  f"Q5-Q1={row['q5_minus_q1']:+.3f}")
        print("  -- Q5滞在率が高い順(Top5) --")
        for mname, row in by_machine.sort_values("q5_rate", ascending=False).head(5).iterrows():
            print(f"    {mname[:28]:28s} n={int(row['n']):4d} "
                  f"Q1={row['q1_rate']:.3f} Q5={row['q5_rate']:.3f} "
                  f"Q5-Q1={row['q5_minus_q1']:+.3f}")
        print("  -- Q5-Q1が高い順(Top5) --")
        for mname, row in by_machine.sort_values("q5_minus_q1", ascending=False).head(5).iterrows():
            print(f"    {mname[:28]:28s} n={int(row['n']):4d} "
                  f"Q1={row['q1_rate']:.3f} Q5={row['q5_rate']:.3f} "
                  f"Q5-Q1={row['q5_minus_q1']:+.3f}")


def main() -> None:
    data = {name: load_at_machines(db) for name, db in HALLS.items()}

    sun = {name: df[df["dow"] == 6].copy() for name, df in data.items()}

    for name in HALLS:
        print(f"\n===== {name} =====")
        analyze_candidate_breakdown(name, sun[name])
        analyze_by_weekday(name, data[name])
        analyze_recent_oos(name, sun[name])

    analyze_pooled(sun["蒲田1"], sun["蒲田7"])
    analyze_all_weekday_pooled(data)
    for name in HALLS:
        analyze_candidate_persistence(name, sun[name])
    analyze_kamata7_excl_monkeyturn(sun["蒲田7"], data["蒲田7"])
    analyze_all_weekday_recent_oos(data)
    analyze_candidate_overlap(data)
    analyze_4hall_pooled(data)
    analyze_machine_level_reliability(data)


if __name__ == "__main__":
    main()
