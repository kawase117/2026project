"""みとや大森町店 ダイデータ当日CSVの分析レポート生成。

収集CSVにはBB/RB回数・累計スタートはあるが差枚は無い。したがって見るのは
ボーナス確率と回転数だけで、差枚の議論はしない。

区分ごとに指標を分ける(プロジェクトの確立済みルール):
- ノーマル/BT/A+AT で bonus_judgeable=1 → RB単独(BB+RBの合算は使わない)
- ジャグラー系でスペック表がある機種 → 設定推定(setting_estimator)と全台系判定
- bonus_judgeable=0 のAT機 → 回転数比(G比)のみ。RBで設定は語らない
自機種の直近90日の平均RB確率を自己ベースラインにして、台ごとにz値を出す。
"""

from __future__ import annotations

import argparse
import math
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from backtest import bonus_specs as bs  # noqa: E402
from scraper.site777 import setting_estimator as se  # noqa: E402

HALL_DB_NAME = "みとや大森町店"

DB_PATH = PROJECT_ROOT / "db" / "みとや大森町店.db"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
BASELINE_DAYS = 90
MIN_GAMES_UNIT = 2000  # 設定推定の足切り(se.MIN_GAMES_FOR_SETTING と同じ)
MIN_GAMES_RB = 1000  # RB z値を出す最低回転数
HIGH_Z = 1.5
PREFIX = r"^(スマスロ|スマート沖スロ|lb|l)"


def norm(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s　‐\-‑–—ー]+", "", text)


# ダイデータ側の機種名(切り詰め・半角カナ)→ machine_master の正式名。前方一致では一意に決まらないものだけ。
DAIDATA_ALIASES = {
    "LB異世界かるてっと": "A‐SLOT+ 異世界かるてっと",
    "L獣王": "獣王",
    "Lモンスターハンターライズ:サンブレイク": "モンスターハンターライズ：サンブレイク",
    "LBﾆｭｰｷﾝｸﾞﾊﾅﾊﾅV": "スマート沖スロ ニューキングハナハナV",
    "Lからくりｻｰｶｽ2": "からくりサーカス2",
    "L化物語": "化物語",
    "L南国育ちSPECIAL": "南国育ち SPECIAL",
    "L炎炎ﾉ消防隊2": "スマスロ炎炎ノ消防隊2",
    "L革命機ｳﾞｧﾙｳﾞﾚｲｳﾞ2": "革命機ヴァルヴレイヴ2",
    "Lｽﾏｽﾛ北斗": "スマスロ北斗の拳",
    "Lｿｰﾄﾞｱｰﾄ･ｵﾝﾗｲﾝII": "ソードアート・オンラインII",
    "Lﾊﾅﾋﾞ": "スマスロ ハナビ",
    "Lﾊﾟﾁｽﾛ ﾗﾌﾞ嬢3 Wご指名": "ラブ嬢3～Wご指名はいかがですか?～",
}


def _alias_index() -> dict[str, str]:
    return {norm(raw): target for raw, target in DAIDATA_ALIASES.items()}


def _strip_prefix(key: str) -> str:
    for _ in range(2):
        key = re.sub(PREFIX, "", key)
    return key


def load_master(conn: sqlite3.Connection) -> dict[str, dict]:
    master: dict[str, dict] = {}
    for row in conn.execute(
        "select machine_name_normalized, display_names, spec_category, bonus_judgeable, jug_flag from machine_master"
    ):
        info = {"name": row[0], "category": row[2], "judgeable": row[3], "jug": row[4]}
        keys = {norm(row[0])}
        for part in re.split(r"[|,、/]", row[1] or ""):
            if part.strip():
                keys.add(norm(part))
        for key in keys:
            master.setdefault(key, info)
    return master


def match_master(name: str, master: dict[str, dict]) -> dict | None:
    key = norm(name)
    if key in master:
        return master[key]
    alias = _alias_index().get(key)
    if alias and norm(alias) in master:
        return master[norm(alias)]
    # 「スマスロ」「L」等の接頭語差と、ダイデータ側の機種名の切り詰めを許す。
    # 前方一致が唯一の機種に決まるときだけ採用し、曖昧なら未登録にする。
    stripped = _strip_prefix(key)
    if len(stripped) < 4:
        return None
    hits = {}
    for cand, info in master.items():
        c2 = _strip_prefix(cand)
        if len(c2) >= 4 and (c2.startswith(stripped) or stripped.startswith(c2)):
            hits[info["name"]] = info
    return next(iter(hits.values())) if len(hits) == 1 else None


def load_baselines(conn: sqlite3.Connection, end_date: str) -> dict[str, tuple[int, int]]:
    """機種ごとの直近90日 (総G, RB回数)。当日は含めない。"""
    sql = """
        select machine_name, sum(games_normalized), sum(rb_count)
        from machine_detailed_results
        where date >= ? and date < ?
        group by machine_name
    """
    # DBの日付は YYYYMMDD 文字列。
    end = pd.Timestamp(end_date)
    start = (end - pd.Timedelta(days=BASELINE_DAYS)).strftime("%Y%m%d")
    base: dict[str, tuple[int, int]] = {}
    for name, games, rb in conn.execute(sql, (start, end.strftime("%Y%m%d"))):
        if games and rb is not None:
            base[norm(name)] = (int(games), int(rb))
    return base


def binom_z(rb: int, games: int, p0: float) -> float:
    """RB回数の、自己ベースライン確率p0に対する正規近似z。"""
    if games <= 0 or not 0 < p0 < 1:
        return 0.0
    return (rb - games * p0) / math.sqrt(games * p0 * (1 - p0))


def fmt_prob(games: int, count: int) -> str:
    return f"1/{games / count:.0f}" if count else "-"


def at_rb_specs() -> dict[str, dict]:
    """AT機のうちRB列にAT初当りが入ると監査(AT_RB_AUDIT.csv)で確定した機種の {正規化名: spec}。

    スマスロ北斗の拳など。DBの bonus_judgeable は変えず、この監査結果を判別可否の根拠にする。
    """
    return {
        key: spec
        for key, spec in bs.load_specs(hall=HALL_DB_NAME).items()
        if spec.get("at_judgeable") and spec.get("at_column") == "rb"
    }


def enrich(df: pd.DataFrame, master, baselines) -> pd.DataFrame:
    df = df.copy()
    infos = [match_master(m, master) for m in df["Machine"]]
    at_specs = at_rb_specs()
    df["category"] = [i["category"] if i else "未登録" for i in infos]
    df["judgeable"] = [
        1 if i and bs.normalize(i["name"]) in at_specs else (i["judgeable"] if i else None) for i in infos
    ]
    df["at_rb_key"] = [bs.normalize(i["name"]) if i and bs.normalize(i["name"]) in at_specs else None for i in infos]
    df["machine_label"] = [unicodedata.normalize("NFKC", m) for m in df["Machine"]]
    df["last_digit"] = df["Unit"].astype(int) % 10
    df["games"] = df["CumulativeStart"].astype(int)
    df["bb"] = df["BBCount"].astype(int)
    df["rb"] = df["RBCount"].astype(int)
    base_p = []
    for name, i in zip(df["Machine"], infos, strict=True):
        b = baselines.get(norm(name)) or (baselines.get(norm(i["name"])) if i else None)
        base_p.append(b[1] / b[0] if b and b[0] > 20000 and b[1] > 0 else math.nan)
    df["base_p"] = base_p
    df["rb_z"] = [
        binom_z(r, g, p) if g >= MIN_GAMES_RB and not math.isnan(p) else math.nan
        for r, g, p in zip(df["rb"], df["games"], df["base_p"], strict=True)
    ]
    return df


def md_table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "(該当なし)\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def section_hall(df: pd.DataFrame) -> str:
    total = int(df["games"].sum())
    med = float(df["games"].median())
    return (
        f"- 台数 {len(df)} / 機種 {df['Machine'].nunique()} / 総回転 {total:,}G / 台別回転の中央値 {med:,.0f}G\n"
        "- 差枚はこのデータに無い。判定はボーナス確率(RB単独)と回転数比で行う。\n"
    )


def section_judgeable(df: pd.DataFrame) -> str:
    """RB判別可能機種の機種別集計と台別z値。"""
    sub = df[df["judgeable"] == 1]
    summary = []
    for label, g in sub.groupby("machine_label"):
        games, rb = int(g["games"].sum()), int(g["rb"].sum())
        bp = g["base_p"].dropna()
        base = f"1/{1 / bp.iloc[0]:.0f}" if len(bp) else "-"
        z = binom_z(rb, games, bp.iloc[0]) if len(bp) and games >= MIN_GAMES_RB else math.nan
        summary.append(
            [
                label,
                g["category"].iloc[0],
                len(g),
                f"{games:,}",
                rb,
                fmt_prob(games, rb),
                base,
                "-" if math.isnan(z) else f"{z:+.2f}",
                int((g["rb_z"] >= HIGH_Z).sum()),
            ]
        )
    summary.sort(key=lambda r: -(float(r[7]) if r[7] != "-" else -99))
    out = [
        md_table(
            ["機種", "区分", "台数", "総G", "RB", "RB確率", "自己ベース(90日)", "機種z", f"z>={HIGH_Z}の台"], summary
        )
    ]
    top = sub.dropna(subset=["rb_z"]).sort_values("rb_z", ascending=False).head(15)
    rows = [
        [
            r.Unit,
            r.machine_label,
            f"{r.games:,}",
            r.rb,
            fmt_prob(r.games, r.rb),
            f"1/{1 / r.base_p:.0f}",
            f"{r.rb_z:+.2f}",
        ]
        for r in top.itertuples()
    ]
    out.append("\n**台別 RB z 上位15**(自機種の直近90日平均に対して)\n\n")
    out.append(md_table(["台", "機種", "G", "RB", "RB確率", "自己ベース", "z"], rows))
    return "".join(out)


def section_jug_settings(df: pd.DataFrame) -> str:
    specs = se.load_family_specs()
    if not specs:
        return "スペック表を読めなかったため設定推定を省略。\n"
    matcher = se.build_family_matcher(specs)
    unit_rows, zen_rows = [], []
    for label, g in df[df["category"] == "ノーマル"].groupby("machine_label"):
        fam = se.match_family(label, matcher)
        if not fam:
            continue
        settings = specs[fam]["settings"]
        machines = [{"games": int(r.games), "bb_count": int(r.bb), "rb_count": int(r.rb)} for r in g.itertuples()]
        zen = se.judge_model_zentaikei(machines, settings)
        if zen:
            zen_rows.append(
                [
                    label,
                    zen["n_machines"],
                    f"{zen['total_games']:,}",
                    zen["pooled_ml_setting"],
                    zen["all_high_vs_low_ratio"],
                    zen["k_map"],
                    zen["p_all_high"],
                    zen["p_half_or_more_high"],
                    zen["verdict"],
                ]
            )
        for r in g.itertuples():
            est = se.estimate_setting(int(r.games), int(r.bb), int(r.rb), settings)
            if est:
                unit_rows.append(
                    [
                        r.Unit,
                        label,
                        f"{r.games:,}",
                        r.bb,
                        r.rb,
                        fmt_prob(r.games, r.rb),
                        est["setting_band_label"],
                        est["setting_lean"],
                        est["setting_confidence"],
                        est["high_low_ratio"],
                    ]
                )
    at_specs = at_rb_specs()
    for label, g in df[df["at_rb_key"].notna()].groupby("machine_label"):
        spec = at_specs[g["at_rb_key"].iloc[0]]
        # AT初当りはRB列。BBはAT初当りではないので尤度から外す(use_bb=False)。
        settings = {
            s: {"bb_probability": 0.5, "rb_probability": v["rb_probability"], "use_bb": False}
            for s, v in spec["settings"].items()
        }
        for r in g.itertuples():
            est = se.estimate_setting(int(r.games), 0, int(r.rb), settings)
            if est:
                unit_rows.append(
                    [
                        r.Unit,
                        f"{label}(AT・RB判別)",
                        f"{r.games:,}",
                        "-",
                        r.rb,
                        fmt_prob(r.games, r.rb),
                        est["setting_band_label"],
                        est["setting_lean"],
                        est["setting_confidence"],
                        est["high_low_ratio"],
                    ]
                )
    out = ["**機種別 全台系判定**(合算尤度比と高設定台数kの事後)\n\n"]
    out.append(
        md_table(
            ["機種", "台数", "総G", "合算ML設定", "全高/全低 尤度比", "k_map", "p(全台高)", "p(半数以上)", "判定"],
            zen_rows,
        )
    )
    unit_rows.sort(key=lambda r: -(r[9] or 0))
    out.append(
        f"\n**台別 設定推定**({MIN_GAMES_UNIT}G以上、高低尤度比の上位20)。"
        "最尤設定のピンポイントは当たらない。見るのは高低寄りと信用度のみ。\n\n"
    )
    out.append(
        md_table(
            ["台", "機種", "G", "BB", "RB", "RB確率", "妥当な設定幅", "寄り", "信用度", "高/低 尤度比"], unit_rows[:20]
        )
    )
    return "".join(out)


def section_at(df: pd.DataFrame) -> str:
    sub = df[df["judgeable"] != 1]
    if sub.empty:
        return "(該当なし)\n"
    hall_med = float(df["games"].median())
    rows = []
    for label, g in sub.groupby("machine_label"):
        games = g["games"]
        rows.append(
            [
                label,
                g["category"].iloc[0],
                len(g),
                f"{games.mean():,.0f}",
                f"{games.mean() / hall_med:.2f}",
                int((games >= hall_med * 2).sum()),
            ]
        )
    rows.sort(key=lambda r: -float(r[4]))
    out = [
        f"回転数だけで見る。ホールの台別中央値は{hall_med:,.0f}G。RBでは設定を語らない。"
        "差枚が無いため、G比が高いことは設定示唆の候補にとどまる。\n\n"
    ]
    out.append(md_table(["機種", "区分", "台数", "平均G", "G比(対ホール中央値)", "G比2倍以上の台"], rows[:20]))
    heavy = sub[sub["games"] >= hall_med * 2].sort_values("games", ascending=False).head(15)
    out.append("\n**高回転台(ホール中央値の2倍以上)**\n\n")
    out.append(
        md_table(
            ["台", "機種", "G", "G比"],
            [[r.Unit, r.machine_label, f"{r.games:,}", f"{r.games / hall_med:.2f}"] for r in heavy.itertuples()],
        )
    )
    return "".join(out)


def section_tail(df: pd.DataFrame) -> str:
    sub = df[(df["judgeable"] == 1) & df["rb_z"].notna()]
    if sub.empty:
        return "(判別可能機種のデータなし)\n"
    rows = [
        [
            d,
            len(g),
            f"{g['rb_z'].mean():+.2f}",
            f"{g['rb_z'].sum() / math.sqrt(len(g)):+.2f}",
            int((g["rb_z"] >= HIGH_Z).sum()),
        ]
        for d, g in sub.groupby("last_digit")
    ]
    return "RB判別可能機種の台別z(自己ベース比)を末尾別に集計。合算zは台数の平方根で規格化。\n\n" + md_table(
        ["末尾", "台数", "平均z", "合算z", f"z>={HIGH_Z}の台"], rows
    )


def section_narabi(df: pd.DataFrame) -> str:
    """同機種で台番号が3連続する並びのz平均(台番号連番のみ。島の物理配置は見ていない)。"""
    sub = df[df["rb_z"].notna()]
    by_unit = {int(r.Unit): r for r in sub.itertuples()}
    rows = []
    for u in sorted(by_unit):
        trio = [u, u + 1, u + 2]
        if not all(t in by_unit for t in trio) or len({by_unit[t].machine_label for t in trio}) != 1:
            continue
        zs = [by_unit[t].rb_z for t in trio]
        m = sum(zs) / 3
        if min(zs) > 0 and m >= 1.0:
            rows.append([f"{u}-{u + 2}", by_unit[u].machine_label, f"{m:+.2f}", " / ".join(f"{z:+.1f}" for z in zs)])
    rows.sort(key=lambda r: -float(r[2]))
    return (
        "台番号連番の3台で、全台のRB zが正かつ平均+1.0以上。台番号の並びであり物理配置の確認はしていない。\n\n"
        + md_table(["台番号", "機種", "平均z", "各台z"], rows[:15])
    )


def build_report(df: pd.DataFrame, date: str, observed: str, unmatched: list[str]) -> str:
    parts = [
        f"# みとや大森町店 ダイデータ速報分析 {date}\n\n取得 {observed} (巡回中も更新され得る。台ごとに時刻が少しずれる)\n\n"
    ]
    parts.append("## 全体\n\n" + section_hall(df))
    parts.append("\n## RB判別可能機種(RB単独・自己ベース比)\n\n" + section_judgeable(df))
    parts.append("\n## ジャグラー系 設定推定\n\n" + section_jug_settings(df))
    parts.append("\n## 判別不可のAT機(回転数のみ)\n\n" + section_at(df))
    parts.append("\n## 末尾別\n\n" + section_tail(df))
    parts.append("\n## 台番号連番の並び候補\n\n" + section_narabi(df))
    if unmatched:
        parts.append(
            "\n## 機種マスター未登録\n\n" + "、".join(unmatched) + "\n分析区分に入れていない。要machine_master更新。\n"
        )
    parts.append(
        "\n## 注意\n\n- 日中のRB高率は最終に平均へ回帰しやすい。途中の高RBを根拠にしない。低RBで並びを否定するのも禁止。\n"
        "- 差枚が無いのでAT機の全台系は判定できない。\n"
    )
    return "".join(parts)


def analyze(csv_path: Path) -> Path:
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
    date = df["BusinessDate"].iloc[0]
    observed = df["ObservedAt"].iloc[0]
    with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as conn:
        master = load_master(conn)
        baselines = load_baselines(conn, date)
    enriched = enrich(df, master, baselines)
    unmatched = sorted(enriched.loc[enriched["category"] == "未登録", "machine_label"].unique())
    report = build_report(enriched, date, observed, unmatched)
    out = OUTPUT_DIR / f"mitoya_daidata_report_{date}.md"
    out.write_text(report, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="?", help="収集CSV。省略時は最新")
    args = ap.parse_args()
    csv_path = (
        Path(args.csv)
        if args.csv
        else max(OUTPUT_DIR.glob("mitoya_omorimachi_slots_21.3yen_*.csv"), key=lambda p: p.stat().st_mtime)
    )
    print(f"REPORT: {analyze(csv_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
