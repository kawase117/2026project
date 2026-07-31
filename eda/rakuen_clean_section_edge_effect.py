"""楽園蒲田店: section を物理的な列に再定義した後の端番効果を測る。

前提（2026-07-28 のセッションで確定）:
    section を実配置の列単位に振り直し、さらに列を4種に分類した
    （`eda/rakuen_section_classification.py`）。

      clean          端の定義が自明な列。2列背中合わせ島の各列・通路で切れていない
                     単列・S字。**端番効果の本命の計測対象**
      frame          フロア外周（壁際）。途中に柱があり複数 section に分断されている。
                     ホールが分断を投入単位として扱っているか不明なので本命から外す
      interior_split 外周でないが内部通路で分断（U字島 1100-1121 / 単列 1122-1134）
      special        三角形 2126-2128、L字 2076-2090。端の定義が自明でない

測るもの:
    (1) clean 列だけでの端番効果（カテゴリ別）。frame / interior_split と比較する
    (2) 柱帰属テスト — 外周の壁面一続きに対し、柱で分断された各ピースの端
        （＝柱に隣接する台）が、壁面の真の端と同じように優遇されているか。
        優遇されていれば「ホールは柱の分断を投入単位として扱っている」、
        中間台と区別がつかなければ「柱を無視して壁一続きを1列として扱っている」
    (3) 端からの深さの勾配 — 端/非端の二値でなく、端から何番目かで効果が減衰するか
    (4) 背中合わせペアの連動 — 島の表裏で同じ位置の台の設定が連動しているか

方法（プロジェクトの確立された規約に従う）:
    * 主指標は「**同日×同機種**平均からの残差（機種内残差）」。機種構成の混入と
      日ごとのホール全体の振れを同時に落とす（FINDINGS.md:123）
    * 機械割(%) = 100 + diff_coins_normalized / (3 * games_normalized) * 100、効果量は pp
    * BB+RB は bb_count/rb_count から直接計算（回/1000G）。rb_probability_decimal は
      rb_count==0 の行で NULL になり RB0回の日を非ランダムに落とすため使わない（追試9）
    * **min_games フィルタは使わない**。games は設定の下流なので足切りは選択バイアス
      を生む（CLAUDE.md）
    * CI は台×機種（設置スペル）単位のクラスタブートストラップ。同じ台の連日の
      観測は独立でないため、行単位のCIは狭すぎる

期間は工事前エポック 20250101〜20260705（310,944行）。工事後は22日/11,740行しか
なく単独では検出力が足りない。

使い方:
    venv\\Scripts\\python.exe -m eda.rakuen_clean_section_edge_effect
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from eda.rakuen_section_classification import PRE_EPOCH, classify

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "db" / "楽園蒲田店.db"
OUT_DIR = Path(__file__).parent / "results" / "rakuen_clean_edge"
HALL_NAME = "楽園蒲田店"

DATE_START = "20250101"
DATE_END = "20260705"

N_BOOT = 2000
SEED = 20260728

# 外周の「壁面ひと続き」。柱で分断されて複数 section になっているものだけを挙げる。
# ピースは物理的に端から順に並べる（工事前エポックの section 名）。
WALL_RUNS: list[tuple[str, list[str]]] = [
    ("1F左壁 1135-1151", ["1145-1151", "1139-1144", "1135-1138"]),
    ("2F左壁 2100-2110", ["2106-2110", "2100-2105"]),
    ("3F左壁 3107-3116", ["3113-3116", "3107-3112"]),
    ("3F右壁 3174-3185", ["3174-3179", "3180-3185"]),
    ("新2F左壁 2000-2007", ["2004-2007", "2000-2003"]),
]


def load_frame() -> pd.DataFrame:
    query = """
        SELECT r.date, r.machine_number, r.machine_name,
               r.games_normalized AS games,
               r.diff_coins_normalized AS diff_coins,
               r.bb_count, r.rb_count,
               l.section, l.rank_from_min, l.rank_from_max, l.x, l.y,
               m.jug_flag, m.hana_flag, m.bt_flag
        FROM machine_detailed_results r
        JOIN machine_layout_history l
          ON r.machine_number = l.machine_number
         AND r.date >= l.valid_from
         AND (l.valid_to IS NULL OR r.date <= l.valid_to)
        LEFT JOIN machine_master m
          ON r.machine_name = m.machine_name_normalized
        WHERE l.hall_name = ?
          AND l.valid_from = ?
          AND r.date BETWEEN ? AND ?
          AND r.games_normalized > 0
    """
    with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as con:
        df = pd.read_sql_query(query, con, params=(HALL_NAME, PRE_EPOCH, DATE_START, DATE_END))

    df["machine_rate"] = 100 + df["diff_coins"] / (3 * df["games"]) * 100
    df["bbrb"] = (df["bb_count"].fillna(0) + df["rb_count"].fillna(0)) / df["games"] * 1000

    for col in ("jug_flag", "hana_flag", "bt_flag"):
        df[col] = df[col].fillna(0).astype(int)

    # 優先度つきの排他カテゴリ。ジャグ・ハナハナは bt_flag と重なりうるので先に取る。
    df["category"] = np.select(
        [df["jug_flag"] == 1, df["hana_flag"] == 1, df["bt_flag"] == 1],
        ["ジャグ", "ハナハナ", "技術介入"],
        default="AT一般",
    )
    df["group"] = df["section"].map(lambda s: classify(s, PRE_EPOCH))
    df["section_size"] = df.groupby("section")["machine_number"].transform("nunique")
    df["is_edge"] = (df["rank_from_min"] == 1) | (df["rank_from_max"] == 1)
    # 端からの深さ: 端が1、その隣が2。列の中央で最大になる。
    df["depth"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    return df


def add_within_model_residual(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """同日×同機種平均からの残差。対照が取れない群（1台のみ）は落とす。

    同じ日・同じ機種の中で比べるので、機種構成の違いとその日のホール全体の
    出方が同時に落ちる。1台しかない群は残差が恒等的に0になり、効果を
    薄める方向にしか働かないので除外する。
    """
    grp = df.groupby(["date", "machine_name"])
    df = df.assign(_n_in_group=grp["machine_number"].transform("size"))
    for col in cols:
        df[f"resid_{col}"] = df[col] - grp[col].transform("mean")
    return df.loc[df["_n_in_group"] >= 2].drop(columns="_n_in_group")


def cluster_bootstrap_diff(
    df: pd.DataFrame, value_col: str, flag_col: str, rng: np.random.Generator
) -> dict[str, float]:
    """flag_col が True の群と False の群の平均差を、**物理台単位**で再標本化して評価。

    同じ台の連日の観測は独立でない。行単位で CI を作ると幅が数分の一になり、
    実際には効いていない差を有意に見せてしまう。

    クラスタは台×機種スペルではなく `machine_number` に取る。端かどうかは
    物理的な位置に固定された属性で、機種が入れ替わっても同じ台は同じ位置に
    居続ける。スペル単位で再標本化すると1台が複数回独立に数えられ、
    設置台数が少ないカテゴリ（clean のジャグは端が実8台）で CI が
    実力以上に狭くなる。
    """
    unit = df.groupby("machine_number").agg(
        value=(value_col, "mean"),
        flag=(flag_col, "first"),
        n_days=(value_col, "size"),
    )
    treat = unit.loc[unit["flag"]]
    control = unit.loc[~unit["flag"]]
    if treat.empty or control.empty:
        return {}

    def weighted(sub: pd.DataFrame) -> float:
        return float(np.average(sub["value"], weights=sub["n_days"]))

    point = weighted(treat) - weighted(control)

    t_val, t_w = treat["value"].to_numpy(), treat["n_days"].to_numpy()
    c_val, c_w = control["value"].to_numpy(), control["n_days"].to_numpy()
    draws = np.empty(N_BOOT)
    for i in range(N_BOOT):
        ti = rng.integers(0, len(t_val), len(t_val))
        ci = rng.integers(0, len(c_val), len(c_val))
        draws[i] = np.average(t_val[ti], weights=t_w[ti]) - np.average(c_val[ci], weights=c_w[ci])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {
        "effect": round(point, 3),
        "ci_lo": round(float(lo), 3),
        "ci_hi": round(float(hi), 3),
        "sig": "*" if (lo > 0 or hi < 0) else "ns",
        "n_treat": int(len(treat)),
        "n_control": int(len(control)),
        "n_rows": int(len(df)),
    }


def analyze_edge_by_group(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(1) 列の分類 × カテゴリ ごとの端番効果。"""
    records = []
    for group in ("clean", "frame", "interior_split"):
        sub_g = df.loc[df["group"] == group]
        for category in ("ジャグ", "技術介入", "ハナハナ", "AT一般", "＜全体＞"):
            sub = sub_g if category == "＜全体＞" else sub_g.loc[sub_g["category"] == category]
            if sub.empty:
                continue
            for metric, label in (
                ("resid_machine_rate", "機械割pp"),
                ("resid_bbrb", "BB+RB/1000G"),
            ):
                res = cluster_bootstrap_diff(sub, metric, "is_edge", rng)
                if res:
                    records.append({"group": group, "category": category, "metric": label, **res})
    return pd.DataFrame(records)


def build_pillar_frame(df: pd.DataFrame) -> pd.DataFrame:
    """外周の壁面ひと続きに属する行に、柱基準の位置ラベルを付ける。

    wall_end     壁面全体の真の端（柱を無視しても端）
    pillar_adj   柱に隣接する台（ピース単位で見たときだけ端）
    middle       どちらでもない
    """
    labels: dict[int, str] = {}
    run_of: dict[int, str] = {}
    for run_name, pieces in WALL_RUNS:
        piece_ends: list[int] = []
        for section in pieces:
            lo, hi = (int(v) for v in section.split("-"))
            piece_ends += [lo, hi]
        # 壁面全体の端は、ピースの端のうち最小と最大の台番号。
        wall_ends = {min(piece_ends), max(piece_ends)}
        for machine_number in piece_ends:
            labels[machine_number] = "wall_end" if machine_number in wall_ends else "pillar_adj"
        for section in pieces:
            run_of[section] = run_name

    run_sections = set(run_of)
    sub = df.loc[df["section"].isin(run_sections)].copy()
    sub["pos"] = sub["machine_number"].map(labels).fillna("middle")
    sub["wall_run"] = sub["section"].map(run_of)
    return sub


def analyze_pillar_attribution(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(2) 柱帰属テスト。

    `pillar_adj` が `middle` より優遇されていれば、ホールは柱の分断を
    投入単位の境界として扱っている可能性が高い。区別がつかなければ、
    柱を無視して壁一続きを1列として扱っていることになる。

    ただし実台数が12台/10台と薄く、柱そのものでなく「柱付近に置かれがちな
    列・機種・導線」の効果である可能性は本テストでは排除できない。
    """
    sub = build_pillar_frame(df)
    records = []
    for target in ("wall_end", "pillar_adj"):
        pair = sub.loc[sub["pos"].isin([target, "middle"])].copy()
        pair["flag"] = pair["pos"] == target
        for metric, label in (
            ("resid_machine_rate", "機械割pp"),
            ("resid_bbrb", "BB+RB/1000G"),
        ):
            res = cluster_bootstrap_diff(pair, metric, "flag", rng)
            if res:
                records.append({"comparison": f"{target} vs middle", "metric": label, **res})
    return pd.DataFrame(records)


def analyze_depth_gradient(df: pd.DataFrame) -> pd.DataFrame:
    """(3) 端からの深さごとの残差。二値でなく勾配があるか見る。

    列の長さで depth の取りうる範囲が変わるので、長さ10台以上の clean 列に限る。
    """
    sub = df.loc[(df["group"] == "clean") & (df["section_size"] >= 10)]
    records = []
    for category in ("ジャグ", "技術介入", "ハナハナ", "AT一般"):
        cat = sub.loc[sub["category"] == category]
        for depth in range(1, 7):
            d = cat.loc[cat["depth"] == depth]
            if len(d) < 100:
                continue
            unit = d.groupby(["machine_number", "machine_name"])["resid_machine_rate"].mean()
            records.append(
                {
                    "category": category,
                    "depth": depth,
                    "n_rows": int(len(d)),
                    "n_units": int(len(unit)),
                    "mean_pp": round(float(d["resid_machine_rate"].mean()), 3),
                }
            )
    return pd.DataFrame(records)


def analyze_position_profile(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(3b) 端から k 番目それぞれに固有の効果があるか。

    (3) の depth 別平均には3つの欠陥があった:

      * CI が無く、depth 2 と 3 の差が有意か判定できなかった
      * `depth = min(rank_from_min, rank_from_max)` で**両端を畳んでいた**。
        台番号の小さい側の端と大きい側の端で扱いが違えば打ち消し合う
      * 参照が「自分を含む同日×同機種平均」なので、ゼロ和制約で位置間の
        差が潰れる

    ここでは参照群を `depth >= REF_DEPTH`（列の中央側）に固定し、各位置を
    それとの差として測る。参照群は各位置と互いに素なのでゼロ和の自己参照が
    起きない。両端を畳んだ版と、台番号の小さい側/大きい側に分けた版の両方を出す。

    列の長さで取りうる位置が変わるため、`depth >= REF_DEPTH` が必ず存在する
    長さ（`MIN_SIZE`台以上）の clean 列に限る。
    """
    REF_DEPTH = 4
    MIN_SIZE = 9

    sub = df.loc[(df["group"] == "clean") & (df["section_size"] >= MIN_SIZE)].copy()
    reference = sub["depth"] >= REF_DEPTH

    records = []
    for category in ("ジャグ", "技術介入", "AT一般", "＜全体＞"):
        cat_mask = True if category == "＜全体＞" else (sub["category"] == category)
        cat = sub.loc[cat_mask] if category != "＜全体＞" else sub
        ref = cat.loc[cat["depth"] >= REF_DEPTH]
        if ref.empty:
            continue

        # 軸1: 両端を畳んだ depth（従来と同じ定義だが参照群を固定）
        # 軸2/3: 台番号の小さい側の端から k 番目 / 大きい側の端から k 番目
        axes = [
            ("端から(両端込)", cat["depth"]),
            ("小さい番号側から", cat["rank_from_min"]),
            ("大きい番号側から", cat["rank_from_max"]),
        ]
        for axis_name, series in axes:
            for k in range(1, REF_DEPTH):
                target = cat.loc[series == k]
                if target.empty:
                    continue
                pair = pd.concat([target, ref])
                pair = pair.assign(_flag=pair.index.isin(target.index))
                res = cluster_bootstrap_diff(pair, "resid_machine_rate", "_flag", rng)
                if res:
                    records.append({"category": category, "axis": axis_name, "k": k, **res})
    return pd.DataFrame(records)


def analyze_position_omnibus(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(3c) 「端以外の位置にも法則性があるか」を参照群の仮定なしに検定する。

    (3b) は参照群を `depth >= 4` と決め打ちしており、そこ自体に構造があれば
    全ての推定が歪む。また位置×カテゴリで多数の検定を走らせるので、
    どれか1つが有意になるのは偶然でも起きる。

    ここでは omnibus 置換検定を使う。統計量は「位置別平均のばらつき（分散）」。
    帰無仮説は「列の中で、どの台がどの位置にいるかは残差と無関係」。
    **同じ列の中で位置ラベルだけを並べ替える**ことで、列そのものの良し悪し・
    列の長さ・機種構成は保存したまま、位置と成績の対応だけを壊す。

    2通り走らせる:
      with_edge     全位置。端効果があるので有意になるはず（検定の健全性確認）
      without_edge  **端(depth=1)の台を全て除いた上で**、残りの位置に
                    構造が残るか。ユーザーの問い「2番目・3番目にも法則が
                    あるか」への直接の答えはこちら
    """
    N_PERM = 2000
    sub = df.loc[df["group"] == "clean"]

    records = []
    for category in ("ジャグ", "技術介入", "AT一般", "＜全体＞"):
        cat = sub if category == "＜全体＞" else sub.loc[sub["category"] == category]
        if cat.empty:
            continue
        # 台単位に潰す。位置は台に固定された属性なので、これが自然な単位。
        unit = cat.groupby("machine_number").agg(
            section=("section", "first"),
            depth=("depth", "first"),
            value=("resid_machine_rate", "mean"),
            n_days=("resid_machine_rate", "size"),
        )

        for scope, keep in (("with_edge", unit["depth"] >= 1), ("without_edge", unit["depth"] >= 2)):
            u = unit.loc[keep]
            # 位置が2種類以上ある列だけが情報を持つ
            sizes = u.groupby("section")["depth"].nunique()
            u = u.loc[u["section"].isin(sizes[sizes >= 2].index)]
            if u["depth"].nunique() < 2 or len(u) < 10:
                continue

            def stat(depths: np.ndarray) -> float:
                """位置別の重み付き平均のばらつき。"""
                frame = pd.DataFrame({"d": depths, "v": u["value"].to_numpy(), "w": u["n_days"].to_numpy()})
                means = frame.groupby("d").apply(lambda g: np.average(g["v"], weights=g["w"]), include_groups=False)
                counts = frame.groupby("d")["w"].sum()
                return float(np.average((means - np.average(means, weights=counts)) ** 2, weights=counts))

            observed = stat(u["depth"].to_numpy())

            section_codes = u["section"].to_numpy()
            null = np.empty(N_PERM)
            for i in range(N_PERM):
                shuffled = u["depth"].to_numpy().copy()
                for section in np.unique(section_codes):
                    idx = np.flatnonzero(section_codes == section)
                    shuffled[idx] = rng.permutation(shuffled[idx])
                null[i] = stat(shuffled)

            p = float((null >= observed).mean())
            records.append(
                {
                    "category": category,
                    "scope": scope,
                    "n_machines": int(len(u)),
                    "n_positions": int(u["depth"].nunique()),
                    "observed_var": round(observed, 4),
                    "null_median": round(float(np.median(null)), 4),
                    "p_value": round(p, 4),
                    "sig": "*" if p < 0.05 else "ns",
                }
            )
    return pd.DataFrame(records)


def analyze_backtoback_pairs(df: pd.DataFrame) -> pd.DataFrame:
    """(4) 背中合わせペアの連動。

    2列島の表裏で、同じ深さにある台の日次残差が相関するか。ホールが
    「島の端」を単位に入れているなら表裏が連動し、「列の端」を単位に
    入れているなら独立に近くなる。

    台番号の連続だけで対にすると、隣の島の手前の列と組んでしまう
    （1027-1036 と 1037-1046 は別の島）。座標で「X が隣接し Y の範囲が
    一致する」ものだけを真の背中合わせとし、隣接島どうしの組は対照として
    別ラベルで併記する。
    """
    sub = df.loc[df["group"] == "clean"].copy()

    geom: dict[str, tuple[frozenset, frozenset]] = {}
    for section, g in sub.groupby("section"):
        geom[section] = (frozenset(g["x"].unique()), frozenset(g["y"].unique()))

    sections = sorted(sub["section"].unique(), key=lambda s: int(s.split("-")[0]))
    pairs: list[tuple[str, str, str]] = []
    for a, b in zip(sections, sections[1:]):
        if int(b.split("-")[0]) != int(a.split("-")[1]) + 1:
            continue
        (ax, ay), (bx, by) = geom[a], geom[b]
        # 縦列の島: X が1つずつでちょうど隣、Y の並びが同じ。
        vertical = len(ax) == 1 == len(bx) and abs(min(ax) - min(bx)) == 1 and ay == by
        # 横列の島（S字）: Y が1つずつでちょうど隣、X の並びが同じ。
        horizontal = len(ay) == 1 == len(by) and abs(min(ay) - min(by)) == 1 and ax == bx
        kind = "背中合わせ" if (vertical or horizontal) else "隣接島（対照）"
        pairs.append((a, b, kind))

    records = []
    for a, b, kind in pairs:
        da = sub.loc[sub["section"] == a]
        db = sub.loc[sub["section"] == b]
        if da.empty or db.empty:
            continue
        # 表裏の対応: 蛇行なので a の depth d と b の depth d が物理的に隣接する。
        ma = da.groupby(["date", "depth"])["resid_machine_rate"].mean()
        mb = db.groupby(["date", "depth"])["resid_machine_rate"].mean()
        joined = pd.concat([ma.rename("a"), mb.rename("b")], axis=1).dropna()
        if len(joined) < 100:
            continue
        records.append(
            {
                "kind": kind,
                "island": f"{a} | {b}",
                "n_obs": int(len(joined)),
                "corr": round(float(joined["a"].corr(joined["b"])), 3),
            }
        )
    return pd.DataFrame(records)


def analyze_robustness(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """(5) 頑健性: split-half・月次安定性・leave-one-column-out。

    多数の切り方を試した後なので、事前固定した定義のまま「期間を割っても」
    「どの列を抜いても」効果が残るかを見る。1本の列や特定の時期が
    効果を単独で作っているなら、ここで崩れる。
    """
    pillar = build_pillar_frame(df)
    pillar = pillar.loc[pillar["pos"].isin(["pillar_adj", "middle"])].copy()
    pillar["is_edge"] = pillar["pos"] == "pillar_adj"

    specs = [
        ("clean/ジャグ", df.loc[(df["group"] == "clean") & (df["category"] == "ジャグ")]),
        ("clean/技術介入", df.loc[(df["group"] == "clean") & (df["category"] == "技術介入")]),
        ("柱隣接 vs 中間", pillar),
    ]

    records = []
    for name, sub in specs:
        if sub.empty:
            continue
        metric = "resid_machine_rate"

        base = cluster_bootstrap_diff(sub, metric, "is_edge", rng)
        records.append({"spec": name, "test": "全期間", "detail": "-", **base})

        # split-half: 期間の中央で2分割
        mid = sub["date"].sort_values().iloc[len(sub) // 2]
        for label, part in (
            ("前半", sub.loc[sub["date"] < mid]),
            ("後半", sub.loc[sub["date"] >= mid]),
        ):
            res = cluster_bootstrap_diff(part, metric, "is_edge", rng)
            if res:
                records.append({"spec": name, "test": "split-half", "detail": label, **res})

        # 月次: 符号の一貫性だけ見る（各月のCIは薄いので点推定のみ）
        monthly = sub.assign(month=sub["date"].str[:6]).groupby(["month", "is_edge"])[metric].mean().unstack()
        if {True, False}.issubset(monthly.columns):
            diff = (monthly[True] - monthly[False]).dropna()
            records.append(
                {
                    "spec": name,
                    "test": "月次符号一貫性",
                    "detail": f"{int((diff > 0).sum())}/{len(diff)}ヶ月が正",
                    "effect": round(float(diff.mean()), 3),
                }
            )

        # leave-one-column-out: 端側の列を1本ずつ抜く
        worst = None
        for section in sorted(sub.loc[sub["is_edge"], "section"].unique()):
            res = cluster_bootstrap_diff(sub.loc[sub["section"] != section], metric, "is_edge", rng)
            if res and (worst is None or res["effect"] < worst[1]["effect"]):
                worst = (section, res)
        if worst:
            records.append(
                {
                    "spec": name,
                    "test": "leave-one-column-out(最悪)",
                    "detail": f"{worst[0]}を除外",
                    **worst[1],
                }
            )

    return pd.DataFrame(records)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)

    df = load_frame()
    print(
        f"読み込み {len(df):,} 行 / {df['machine_number'].nunique()} 台 / "
        f"{df['machine_name'].nunique()} 機種 ({DATE_START}-{DATE_END})"
    )
    print(df.groupby("group")["machine_number"].nunique().to_string())

    df = add_within_model_residual(df, ["machine_rate", "bbrb"])
    print(f"機種内残差が取れた行: {len(df):,}\n")

    edge = analyze_edge_by_group(df, rng)
    edge.to_csv(OUT_DIR / "edge_by_group_category.csv", index=False, encoding="utf-8-sig")
    print("=== (1) 列分類 × カテゴリ 別 端番効果 ===")
    print(edge.to_string(index=False))

    pillar = analyze_pillar_attribution(df, rng)
    pillar.to_csv(OUT_DIR / "pillar_attribution.csv", index=False, encoding="utf-8-sig")
    print("\n=== (2) 柱帰属テスト（外周の壁面ひと続き） ===")
    print(pillar.to_string(index=False))

    depth = analyze_depth_gradient(df)
    depth.to_csv(OUT_DIR / "depth_gradient.csv", index=False, encoding="utf-8-sig")
    print("\n=== (3) 端からの深さ勾配（clean・10台以上の列） ===")
    print(depth.to_string(index=False))

    profile = analyze_position_profile(df, rng)
    profile.to_csv(OUT_DIR / "position_profile.csv", index=False, encoding="utf-8-sig")
    print("\n=== (3b) 端からk番目の効果（参照=列の中央側 depth>=4、CI付き） ===")
    print(profile.to_string(index=False))

    omnibus = analyze_position_omnibus(df, rng)
    omnibus.to_csv(OUT_DIR / "position_omnibus.csv", index=False, encoding="utf-8-sig")
    print("\n=== (3c) 位置構造の omnibus 置換検定（列内で位置ラベルを並べ替え） ===")
    print(omnibus.to_string(index=False))

    pairs = analyze_backtoback_pairs(df)
    pairs.to_csv(OUT_DIR / "backtoback_pairs.csv", index=False, encoding="utf-8-sig")
    print("\n=== (4) 背中合わせペアの日次残差相関 ===")
    print(pairs.to_string(index=False))

    robust = analyze_robustness(df, rng)
    robust.to_csv(OUT_DIR / "robustness.csv", index=False, encoding="utf-8-sig")
    print("\n=== (5) 頑健性検査 ===")
    print(robust.to_string(index=False))

    print(f"\n出力先: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
