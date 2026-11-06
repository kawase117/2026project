"""ホール軸スキャンの共通ランナー。theory 文書の再検証に使い、台帳と結果ファイルを残す。

なぜ要るか:
    `hall-axis-scan` の軸カタログは、位置×時間(`axis_scan`)と単位×時間(`unit_time_scan`)しか
    実装がなかった。全ホールで同じ手順を回し、未実施の軸も理由つきで残すために1本にまとめた。

実装した軸と、既存モジュールの使い分け:
    L1-L5, P5, P6   水準。ここで実装(同じ日の中の比較、7日ブロックブートストラップ)。
    S1, V1, N1      ここで実装。
    H1-H6           ここで実装(暦日で結合し、対象日より前だけで特徴量を作る。basis=as_of)。
    T1-T10          ホール全体・タイプ別の時間軸。ここで実装(`unit_time_scan` の水準と入れ替えを再利用)。
    P1-P3, X1       `axis_scan.run_scan` の出力を台帳に載せる。
    M1, M2, P4, X2  `unit_time_scan.scan_units` の出力を台帳に載せる。
    F1              水準・時間軸の上位候補を、事前に決めた隣接条件と比べる。
    CLAIM           theory 文書の説(`backtest/theory_claims/<key>.json`)を、直近90日とそれ以前で比べる。
                    比較の統計量は `deathwatch` の関数を再利用する。
未実施(台帳に理由を書く):
    T11(登録がないホール)、T12(データなし)、P4:座標(壁側・通路側の定義がない)、X3の一部、X4(事前仮説なし)。

使い方:
    venv/Scripts/python.exe -X utf8 -m backtest.theory_rescan --key mitoya
    venv/Scripts/python.exe -X utf8 -m backtest.theory_rescan --key mitoya --only CLAIM
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path

import jpholiday
import numpy as np
import pandas as pd

from backtest import axis_scan as ax
from backtest import bonus_specs as bs
from backtest import deathwatch as dw
from backtest import monthly_report as mr
from backtest import unit_time_scan as ut
from backtest.run_backtest import apply_eligibility, block_bootstrap_means, load_frame

ROOT = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT / "output" / "axis_scan"
CLAIMS_DIR = Path(__file__).resolve().parent / "theory_claims"

HALLS = {
    "mitoya": {
        "hall": "みとや大森町店",
        "regime": "20260427",
        "regime_note": "店長交代(theory文書 2026-07-23 追記のユーザー情報)",
    },
    "rakuen": {"hall": "楽園蒲田店", "regime": "20260706", "regime_note": "島配列の工事(machine_layout_history の版)"},
    "kamata7": {"hall": "マルハンメガシティ2000-蒲田7", "regime": None, "regime_note": "履歴から境界を確定できない"},
    "kamata1": {
        "hall": "マルハンメガシティ2000-蒲田1",
        "regime": "20260825",
        "regime_note": "店長異動(ユーザー情報、memory)",
    },
    "hiroki": {"hall": "ヒロキ東口店", "regime": None, "regime_note": "境界の情報なし"},
    "arrow": {"hall": "ARROW池上店", "regime": None, "regime_note": "境界の情報なし"},
    "kintoki": {"hall": "金時京急蒲田店", "regime": None, "regime_note": "境界の情報なし"},
    "lategap": {"hall": "レイトギャップ平和島", "regime": None, "regime_note": "境界の情報なし"},
    "thecity": {"hall": "ザ-シティ-ベルシティ雑色店", "regime": None, "regime_note": "境界の情報なし"},
}

LEDGER_COLUMNS = [
    "axis_id", "axis", "unit", "metrics", "window", "status", "scope", "planned", "done",
    "excluded", "basis", "runner", "result_file", "reason", "updated",
]  # fmt: skip
CELL_COLUMNS = [
    "axis_id", "unit_kind", "unit", "level", "metric", "contrast", "window", "n_days", "n_units",
    "effect", "ci_lo", "ci_hi", "p", "q", "family", "basis", "note",
]  # fmt: skip
EXCLUDED_COLUMNS = ["axis_id", "unit_kind", "unit", "level", "metric", "contrast", "window", "reason_code"]

# 分析の開始時に固定する閾値(結果を見てから動かさない)。
V1_GAMES = (5000, 6000, 7000)
V1_LOSS_COINS = -2000
V1_LOSS_PT = -10.0
S1_GOOD_GAMES = 3000
S1_GOOD_PAYOUT = 105.0
S1_MIN_ACTIVE = 4
S1_WIDE_SHARE = 0.60
S1_CONC_TOP2 = 0.50
HIGH_POSTERIOR = 0.5
HIGH_MIN_GAMES = 3000
BLOCK = 7
HISTORY_WINDOWS = {"H1": (1, 1), "H2": (7, 7), "H3": (14, 14), "H4": (1, 30), "H5": (1, 60), "H6": (1, 90)}
LONG_RUN_DAYS = 180

CATALOG = {
    "L1": "機種の水準", "L2": "島の水準", "L3": "位置の水準", "L4": "台番号の水準", "L5": "末尾の水準",
    "S1": "全体型/機種集中", "V1": "大負け×高回転", "F1": "反証確認", "N1": "新台の導入後7日",
    "T1": "曜日", "T2": "日の下一桁", "T3": "DD", "T4": "ゾロ目", "T5": "月内の週・給料日", "T6": "祝日・連休",
    "T7": "イベント日", "T8": "イベント系列・公約", "T9": "イベント種別", "T10": "レジーム前後",
    "T11": "ホール固有の日付", "T12": "近隣イベント・天気",
    "H1": "前日", "H2": "7日前", "H3": "14日前", "H4": "直近1か月", "H5": "直近2か月", "H6": "直近3か月",
    "P1": "末尾×時間", "P2": "角番×時間", "P3": "並び×時間", "P4": "島×時間", "P4:座標": "座標(壁側・通路側)",
    "P5": "機種の台数", "P6": "機種の境界",
    "M1": "機種×時間", "M2": "機種タイプ×時間", "X1": "位置×時間", "X2": "機種・島・タイプ×時間", "X3": "末尾×機種・角番×機種", "X4": "3軸以上",
    "CHK2": "高設定推定の絶対数", "CLAIM": "文書の説の再判定",
}  # fmt: skip


# ---------------------------------------------------------------- 日付
def to_date(ds: str) -> dt.date:
    return dt.date(int(ds[:4]), int(ds[4:6]), int(ds[6:]))


def to_ds(d: dt.date) -> str:
    return d.strftime("%Y%m%d")


def shift_ds(ds: str, days: int) -> str:
    return to_ds(to_date(ds) + dt.timedelta(days=days))


def today() -> str:
    return dt.date.today().strftime("%Y%m%d")


def holiday_runs(days: list[str]) -> np.ndarray:
    """3日以上続く土日祝(連休)の中の日か。DBの is_holiday は誤りなので jpholiday で作る。"""
    if not days:
        return np.zeros(0, bool)
    first, last = to_date(days[0]), to_date(days[-1])
    cal = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    off = [x.weekday() >= 5 or bool(jpholiday.is_holiday(x)) for x in cal]
    member = set()
    i = 0
    while i < len(cal):
        if not off[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(cal) and off[j + 1]:
            j += 1
        if j - i + 1 >= 3:
            member.update(to_ds(x) for x in cal[i : j + 1])
        i = j + 1
    return np.array([d in member for d in days])


# ---------------------------------------------------------------- 台日表
def load_table(hall: str, db_dir: Path | None = None) -> pd.DataFrame:
    """G=0 の行を残した台日表。配置は日付に対応する版を結合する(無いホールでは NaN)。"""
    db = (Path(db_dir) / f"{hall}.db") if db_dir else mr.hall_db_path(hall)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        raw = pd.read_sql_query(
            "SELECT date AS ds, machine_name, machine_number, games_normalized AS G, "
            "diff_coins_normalized AS diff, bb_count AS bb, rb_count AS rb FROM machine_detailed_results",
            con,
        )
        lay = pd.read_sql_query(
            "SELECT machine_number, valid_from, valid_to, section, rank_from_min, rank_from_max, rank_from_aisle "
            "FROM machine_layout_history",
            con,
        )
    finally:
        con.close()
    raw["ds"] = raw.ds.astype(str)
    raw["machine_number"] = pd.to_numeric(raw.machine_number, errors="coerce").astype(int)
    for col in ("G", "diff", "bb", "rb"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0.0)
    out = raw.reset_index(drop=True)
    for col in ("rank_from_min", "rank_from_max", "rank_from_aisle"):
        out[col] = np.nan
    out["section"] = None
    if len(lay):
        lay["valid_from"] = lay.valid_from.astype(str)
        lay["valid_to"] = lay.valid_to.fillna("99999999").astype(str)
        m = out[["ds", "machine_number"]].reset_index().merge(lay, on="machine_number", how="inner")
        m = m[(m.ds >= m.valid_from) & (m.ds <= m.valid_to)].drop_duplicates("index").set_index("index")
        for col in ("section", "rank_from_min", "rank_from_max", "rank_from_aisle"):
            out.loc[m.index, col] = m[col] if col == "section" else pd.to_numeric(m[col], errors="coerce")
    out["ld"] = out.machine_number % 10
    edge = out[["rank_from_min", "rank_from_max"]].min(axis=1)
    out["edge"] = edge.map(lambda v: None if pd.isna(v) else ("端1" if v == 1 else "端2" if v == 2 else "端3以上"))
    out["aisle"] = out.rank_from_aisle.map(
        lambda v: None if pd.isna(v) else ("通路角1" if v == 1 else "通路角2" if v == 2 else "通路角3以上")
    )
    return out


def rb_checks(df: pd.DataFrame, specs: dict) -> pd.DataFrame:
    """機種ごとに、RB確率・AT初当り率を使えるかを確かめる(SKILLの4項目)。

    カテゴリで固定しない。ただしAT・ARTはホール別の監査でAのものだけをAT位置に使う。
    """
    rows = []
    for name, part in df[df.G > 0].groupby("machine_name"):
        spec = bs.find_spec(name, specs)
        row = dict(
            machine_name=name,
            category=(spec or {}).get("category"),
            kind=None,
            r1=np.nan,
            r6=np.nan,
            column=None,
            reason="",
        )
        if spec is None:
            rows.append({**row, "reason": "マスターになし"})
            continue
        settings = spec.get("settings") or {}
        rates = {s: v.get("rb_probability") for s, v in settings.items() if v.get("rb_probability")}
        at = bool(spec.get("at_judgeable"))
        col = spec.get("at_column") if at else "rb"
        if not rates:
            rows.append({**row, "reason": "設定別の当り確率なし"})
            continue
        if not at and spec.get("category") in ("AT", "ART"):
            rows.append({**row, "reason": "ATで監査Aでない"})
            continue
        lo, hi = rates[min(rates)], rates[max(rates)]
        if hi <= lo:
            rows.append({**row, "reason": "設定差がない"})
            continue
        hits = part.bb if col == "bb" else part.bb + part.rb if col == "bb+rb" else part.rb
        if hits.sum() == 0:
            rows.append({**row, "reason": "当り列が空"})
            continue
        rate = hits.sum() / part.G.sum()
        if not (min(rates.values()) * 0.95 <= rate <= max(rates.values()) * 1.05):
            rows.append({**row, "reason": f"実測{rate:.5f}が設定の範囲外"})
            continue
        expected = (part.G * rate).clip(lower=1e-6)
        dispersion = float(((hits - expected) ** 2 / expected).mean())
        if dispersion > 5:
            rows.append({**row, "reason": f"分散比{dispersion:.1f}が5超"})
            continue
        rows.append({**row, "kind": "AT" if at else "RB", "r1": lo, "r6": hi, "column": col})
    return pd.DataFrame(rows)


def prepare(df: pd.DataFrame, specs: dict, hall: str) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """機種タイプ・新台の印・当り指標の列を足す。"""
    checks = rb_checks(df, specs)
    first, db_min = mr.load_first_seen(mr.hall_db_path(hall))
    out = df.copy()
    cat = {n: (bs.find_spec(n, specs) or {}).get("category") for n in out.machine_name.unique()}
    out["cat"] = out.machine_name.map(cat)
    out["type"] = [ut.machine_type(n, c) for n, c in zip(out.machine_name, out.cat)]
    out["first_seen"] = out.machine_name.map(first).fillna(db_min)
    out["is_new"] = [ax.is_new_machine(f, d, db_min) for f, d in zip(out.first_seen, out.ds)]
    info = checks.set_index("machine_name")
    out["hit_kind"] = out.machine_name.map(info.kind)
    out["r1"] = out.machine_name.map(info.r1)
    out["r6"] = out.machine_name.map(info.r6)
    column = out.machine_name.map(info.column)
    out["hit"] = np.where(column == "bb", out.bb, np.where(column == "bb+rb", out.bb + out.rb, out.rb))
    out["band"] = np.digitize(out.G, ax.BAND_EDGES)
    return out, checks, db_min


def metric_arrays(df: pd.DataFrame, metric: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(分子, 分母, 対象の行)。回転数・差枚は0Gを含め、率の指標は0Gを含めない。"""
    G, diff = df.G.to_numpy(float), df["diff"].to_numpy(float)
    if metric == "差枚":
        return diff, np.ones(len(df)), np.ones(len(df), bool)
    if metric == "回転数":
        return G, np.ones(len(df)), np.ones(len(df), bool)
    if metric == "機械割差":
        return 100.0 * diff, 3.0 * G, G > 0
    if metric in ("RB位置", "AT位置"):
        mask = (df.hit_kind == metric[:2]).to_numpy() & (G > 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            num = (df.hit.to_numpy(float) - G * df.r1.to_numpy(float)) / (df.r6.to_numpy(float) - df.r1.to_numpy(float))
        return np.nan_to_num(num), G, mask
    raise ValueError(metric)


def _recenter(part: pd.DataFrame, group: list[str]) -> pd.Series:
    """群の中で残差の和をゼロに戻す。

    自分を除いた平均との差は、回転数と率に正の相関があると(勝っている台ほど回される)
    群の和が (G1-G2)(r1-r2) のように正になり、どの単位の効果も底上げされる。
    分母に比例して配り直すので、差の大きさの尺度は変えない。
    """
    grouped = part.groupby(group, sort=False)
    with np.errstate(invalid="ignore", divide="ignore"):
        return part._r - part._d * (grouped._r.transform("sum") / grouped._d.transform("sum"))


def residual_rows(df: pd.DataFrame, metric: str, group: list[str]) -> pd.DataFrame:
    """同じ日・同じ群の、自分を除いた平均との差(行単位、群の和はゼロ)。群に1行しかない行は落とす。"""
    num, den, mask = metric_arrays(df, metric)
    part = df.loc[mask].assign(_n=num[mask], _d=den[mask])
    grouped = part.groupby(group, sort=False)
    tn, td, size = grouped._n.transform("sum"), grouped._d.transform("sum"), grouped._n.transform("size")
    keep = size >= 2
    part, tn, td = part[keep], tn[keep], td[keep]
    with np.errstate(invalid="ignore", divide="ignore"):
        ref = (tn - part._n) / (td - part._d)
    part = part.assign(_r=part._n - part._d * ref)
    part = part[np.isfinite(part._r) & (part._d > 0)]
    return part.assign(_r=_recenter(part, group))


def unit_level_residual(df: pd.DataFrame, metric: str, unit: str, group: list[str]) -> pd.DataFrame:
    """単位(機種)を1まとまりにして、同じ日の他の単位との差を取る。"""
    num, den, mask = metric_arrays(df, metric)
    part = df.loc[mask].assign(_n=num[mask], _d=den[mask])
    u = part.groupby(list(dict.fromkeys(["ds", unit, *group])), sort=False)[["_n", "_d"]].sum().reset_index()
    outer = u.groupby(list(dict.fromkeys(["ds", *group])), sort=False)
    tn, td, size = outer._n.transform("sum"), outer._d.transform("sum"), outer._n.transform("size")
    keep = size >= 2
    u, tn, td = u[keep], tn[keep], td[keep]
    with np.errstate(invalid="ignore", divide="ignore"):
        ref = (tn - u._n) / (td - u._d)
    u = u.assign(_r=u._n - u._d * ref)
    u = u[np.isfinite(u._r) & (u._d > 0)]
    return u.assign(_r=_recenter(u, list(dict.fromkeys(["ds", *group]))))


def block_weights(days: int, iters: int, rng: np.random.Generator, block: int = BLOCK) -> np.ndarray:
    """日のブロックブートストラップの重み(iters×days)。"""
    count = int(np.ceil(days / block))
    starts = rng.integers(0, days, (iters, count))
    offs = ((starts[:, :, None] + np.arange(block)) % days).reshape(iters, -1)[:, :days]
    weights = np.zeros((iters, days))
    np.add.at(weights, (np.repeat(np.arange(iters), days), offs.ravel()), 1.0)
    return weights


def boot_table(frame, unit, days, iters, rng, min_days=5):
    """単位ごとの効果・区間・p。frame は ds・unit・_r・_d を持つ。"""
    empty = pd.DataFrame(columns=["unit", "n_days", "effect", "ci_lo", "ci_hi", "p"])
    if frame is None or not len(frame) or not days:
        return empty
    units = sorted(frame[unit].astype(str).unique())
    di = {d: i for i, d in enumerate(days)}
    ui = {u: i for i, u in enumerate(units)}
    R, D = np.zeros((len(days), len(units))), np.zeros((len(days), len(units)))
    ix = (frame.ds.map(di).to_numpy(), frame[unit].astype(str).map(ui).to_numpy())
    np.add.at(R, ix, frame._r.to_numpy(float))
    np.add.at(D, ix, frame._d.to_numpy(float))
    n_days = (D > 0).sum(0)
    W = block_weights(len(days), iters, rng)
    with np.errstate(invalid="ignore", divide="ignore"):
        eff = R.sum(0) / D.sum(0)
        sims = (W @ R) / (W @ D)
    ok = np.isfinite(sims).any(0)
    lo, hi = np.full(len(units), np.nan), np.full(len(units), np.nan)
    if ok.any():
        lo[ok] = np.nanpercentile(sims[:, ok], 2.5, axis=0)
        hi[ok] = np.nanpercentile(sims[:, ok], 97.5, axis=0)
    p = np.maximum(np.minimum(1.0, 2 * np.minimum((sims <= 0).mean(0), (sims >= 0).mean(0))), 1.0 / iters)
    table = pd.DataFrame(dict(unit=units, n_days=n_days, effect=eff, ci_lo=lo, ci_hi=hi, p=p))
    # 同機種の全台が1つの島にあると、機種内の残差は島の中で打ち消し合って必ずゼロになる。比較が成り立たないので結果に入れない。
    return table[(table.n_days >= min_days) & np.isfinite(table.effect) & ((table.ci_hi - table.ci_lo) > 1e-9)]


# ---------------------------------------------------------------- 結果ファイルと台帳
def _frame(rows, columns) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    for col in columns:
        if col not in frame:
            frame[col] = None
    return frame[columns]


def _js(v):
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return str(v)


def _round(value, digits=4):
    return None if value is None or pd.isna(value) else round(float(value), digits)


def _ex(axis_id, kind, unit, level, metric, contrast, window, code):
    return dict(
        unit_kind=kind, unit=unit, level=level, metric=metric, contrast=contrast, window=window, reason_code=code
    )


class Ledger:
    """台帳と結果ファイル。完了の条件を書き出しの時点で確かめる。"""

    def __init__(self, hall: str, asof: str, root: Path = OUT_ROOT):
        self.hall, self.asof = hall, asof
        self.dir = Path(root) / f"{hall}__{asof}"
        self.results = self.dir / "results"
        self.results.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "LEDGER.csv"
        self.rows: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8-sig", newline="") as fh:
                self.rows = {r["axis_id"]: r for r in csv.DictReader(fh)}
        for axis_id, axis in CATALOG.items():
            self.rows.setdefault(axis_id, self._blank(axis_id, axis))

    @staticmethod
    def _blank(axis_id, axis):
        return {c: "" for c in LEDGER_COLUMNS} | {
            "axis_id": axis_id,
            "axis": axis,
            "status": "未実施",
            "reason": "未着手",
        }

    def not_run(self, axis_id, status, reason, scope=""):
        row = self.rows.setdefault(axis_id, self._blank(axis_id, CATALOG.get(axis_id, axis_id)))
        row.update(
            status=status,
            reason=reason,
            scope=scope,
            planned="0",
            done="0",
            excluded="0",
            result_file="",
            updated=today(),
        )
        for suffix in (".json", ".cells.csv", ".excluded.csv"):
            (self.results / f"{axis_id.replace(':', '_')}{suffix}").unlink(missing_ok=True)
        self.save()

    def record(self, axis_id, *, planned, cells, excluded, unit, metrics, window, scope, basis, runner, top=None,
               power="", caveats=None, extra=None, n_days=0, n_units=0, families=0):  # fmt: skip
        """全セルと除外を書き、planned = done + excluded のときだけ完了にする。"""
        cells = _frame(cells, CELL_COLUMNS)
        excluded = _frame(excluded, EXCLUDED_COLUMNS)
        cells["axis_id"], excluded["axis_id"] = axis_id, axis_id
        cells["basis"] = basis
        for col in ("p", "q"):  # 保存時の丸めと集計を一致させる
            cells[col] = pd.to_numeric(cells[col], errors="coerce").map(
                lambda v: float(f"{v:.5g}") if pd.notna(v) else v
            )
        cells.to_csv(self.results / f"{axis_id}.cells.csv", index=False, encoding="utf-8-sig", float_format="%.5g")
        excluded.to_csv(self.results / f"{axis_id}.excluded.csv", index=False, encoding="utf-8-sig")
        done, exc = len(cells), len(excluded)
        status = "完了" if planned == done + exc else "失敗"
        reason = "" if status == "完了" else f"一部のみ: planned={planned}, done={done}, excluded={exc}"
        pvals = pd.to_numeric(cells.p, errors="coerce")
        qvals = pd.to_numeric(cells.q, errors="coerce")
        summary = {
            "axis_id": axis_id, "hall": self.hall, "asof": self.asof, "window": window, "status": status,
            "basis": basis, "scope": scope, "planned": int(planned), "done": done, "excluded": exc,
            "cells_file": f"results/{axis_id}.cells.csv", "excluded_file": f"results/{axis_id}.excluded.csv",
            "n_days": int(n_days), "n_units": int(n_units), "families": int(families), "cells": done,
            "p05": int((pvals < 0.05).sum()), "p05_expected": round(0.05 * int(pvals.notna().sum()), 1),
            "bh_q02": int((qvals < 0.2).sum()), "top": top or [], "power": power, "caveats": caveats or [],
            "reason": reason,
        }  # fmt: skip
        if extra:
            summary["extra"] = extra
        (self.results / f"{axis_id}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=_js), "utf-8"
        )
        row = self.rows.setdefault(axis_id, self._blank(axis_id, CATALOG.get(axis_id, axis_id)))
        row.update(
            unit=unit, metrics=metrics, window=window, status=status, scope=scope, planned=str(planned), done=str(done),
            excluded=str(exc), basis=basis, runner=runner, result_file=f"results/{axis_id}.json", reason=reason,
            updated=today(),
        )  # fmt: skip
        self.save()
        return summary

    def record_composite(self, axis_id, parts, *, unit, metrics, window, scope, basis, runner, caveats=None):
        """別の軸のセルの和。同じ行を二重に持たず、結果は parts の各ファイルを指す。"""
        planned = done = exc = 0
        for part in parts:
            row = self.rows[part]
            planned, done, exc = planned + int(row["planned"]), done + int(row["done"]), exc + int(row["excluded"])
        for suffix in (".cells.csv", ".excluded.csv"):
            (self.results / f"{axis_id}{suffix}").unlink(missing_ok=True)
        summary = {
            "axis_id": axis_id, "hall": self.hall, "asof": self.asof, "window": window, "status": "完了", "basis": basis, "scope": scope,
            "planned": planned, "done": done, "excluded": exc, "composite_of": list(parts), "top": [], "power": "", "caveats": caveats or [], "reason": "",
        }  # fmt: skip
        (self.results / f"{axis_id}.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1, default=_js), "utf-8"
        )
        row = self.rows.setdefault(axis_id, self._blank(axis_id, CATALOG.get(axis_id, axis_id)))
        row.update(
            unit=unit, metrics=metrics, window=window, status="完了", scope=scope, planned=str(planned), done=str(done), excluded=str(exc),
            basis=basis, runner=runner, result_file=f"results/{axis_id}.json", reason="", updated=today(),
        )  # fmt: skip
        self.save()
        return summary

    def save(self):
        order = list(CATALOG)
        with open(self.path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, LEDGER_COLUMNS)
            writer.writeheader()
            writer.writerows(
                self.rows[k] for k in sorted(self.rows, key=lambda x: order.index(x) if x in order else len(order))
            )


def reconcile(ledger: Ledger) -> dict:
    """SKILLの照合のうち、機械で確かめられる項目(1〜5)の結果を返す。"""
    problems = [f"{a}: 台帳にない" for a in CATALOG if a not in ledger.rows]
    for axis_id, row in ledger.rows.items():
        if row["status"] not in ("未実施", "完了", "データ不足", "失敗"):
            problems.append(f"{axis_id}: 状態が不正 {row['status']}")
        if row["status"] != "完了":
            if not row["reason"]:
                problems.append(f"{axis_id}: 理由がない")
            continue
        files = {s: ledger.results / f"{axis_id}{s}" for s in (".json", ".cells.csv", ".excluded.csv")}
        if files[".json"].exists() and "composite_of" in (composite := json.loads(files[".json"].read_text("utf-8"))):
            parts = composite["composite_of"]
            total = [sum(int(ledger.rows[x][c]) for x in parts) for c in ("planned", "done", "excluded")]
            if total != [int(row["planned"]), int(row["done"]), int(row["excluded"])]:
                problems.append(f"{axis_id}: 合成元と件数が合わない {total}")
            continue
        if not all(f.exists() for f in files.values()):
            problems.append(f"{axis_id}: 結果ファイルが足りない")
            continue
        summary = json.loads(files[".json"].read_text("utf-8"))
        cells = pd.read_csv(files[".cells.csv"], encoding="utf-8-sig", low_memory=False)
        excluded = pd.read_csv(files[".excluded.csv"], encoding="utf-8-sig", low_memory=False)
        planned, done, exc = int(row["planned"]), int(row["done"]), int(row["excluded"])
        if planned != done + exc or done != len(cells) or exc != len(excluded):
            problems.append(f"{axis_id}: 件数が合わない {planned}/{done}/{exc}/{len(cells)}/{len(excluded)}")
        if summary["planned"] != planned or summary["done"] != done or summary["excluded"] != exc:
            problems.append(f"{axis_id}: JSONと台帳が合わない")
        if summary["p05"] != int((pd.to_numeric(cells.p, errors="coerce") < 0.05).sum()):
            problems.append(f"{axis_id}: p05 が数え直しと合わない")
        if summary["bh_q02"] != int((pd.to_numeric(cells.q, errors="coerce") < 0.2).sum()):
            problems.append(f"{axis_id}: bh_q02 が数え直しと合わない")
        known = set(cells.unit.astype(str)) | set(cells.level.astype(str))
        problems += [
            f"{axis_id}: top の候補がセルにない {t.get('label')}"
            for t in summary["top"]
            if str(t.get("label")) not in known
        ]
    for path in ledger.results.glob("*.json"):
        if path.stem not in ledger.rows:
            problems.append(f"{path.stem}: 台帳にない結果ファイル")
    counts = pd.Series([r["status"] for r in ledger.rows.values()]).value_counts().to_dict()
    report = {"problems": problems, "ok": not problems, "status_counts": counts}
    (ledger.dir / "RECONCILE.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
    return report


# ---------------------------------------------------------------- 開始時の確認
def build_header(raw: pd.DataFrame, checks, cfg: dict, asof: str) -> dict:
    days = sorted(raw.ds.unique())
    missing = sorted(set(pd.date_range(days[0], days[-1]).strftime("%Y%m%d")) - set(days))
    first = raw.groupby("machine_name").ds.min()
    last = raw.groupby("machine_name").ds.max()
    recent = shift_ds(asof, -120)
    jump = raw.groupby("ds").machine_number.nunique().diff().abs()
    hall = cfg["hall"]
    reg = {}
    for name in ("EVENT_DAYS", "EVENT_SERIES", "PAST_PROMISES"):
        rows = [json.loads(x) for x in (ax.REGISTRY / f"{name}.jsonl").read_text("utf-8").splitlines() if x.strip()]
        reg[name] = sum(r.get("hall") == hall for r in rows)
    audit = pd.read_csv(ax.REGISTRY / "AT_RB_AUDIT.csv", encoding="utf-8-sig")
    return {
        "hall": hall, "db_min": days[0], "asof": asof, "n_days": len(days), "missing_days": missing,
        "missing_note": "休業と欠測は区別できないので欠測として扱う",
        "windows": {"3m": [shift_ds(asof, -89), asof], "regime": [cfg.get("regime"), asof], "all": [days[0], asof]},
        "regime": cfg.get("regime"), "regime_note": cfg.get("regime_note"),
        "regime_candidates": {
            "machine_first_seen_recent": first[first >= recent].sort_values().to_dict(),
            "machine_last_seen_recent": last[(last >= recent) & (last < asof)].sort_values().to_dict(),
            "unit_count_jump_ge10": {k: int(v) for k, v in jump[jump >= 10].items() if k >= recent},
        },
        "layout_share": round(float(raw.section.notna().mean()), 4), "rows": len(raw), "rows_g0": int((raw.G == 0).sum()),
        "rows_new_machine_excluded": int(raw.is_new.sum()), "event_rows": reg,
        "audit_rows": int((audit.hall == hall).sum()),
        "rb_usable": checks[checks.kind == "RB"].machine_name.tolist(),
        "at_usable": checks[checks.kind == "AT"].machine_name.tolist(),
        "holiday_source": "jpholiday",
        "fixed_thresholds": {
            "V1_games": V1_GAMES, "V1_loss_coins": V1_LOSS_COINS, "V1_loss_pt": V1_LOSS_PT,
            "S1_good": f"G>={S1_GOOD_GAMES} かつ 機械割>={S1_GOOD_PAYOUT}%",
            "S1_wide": f"自機種の期間平均を上回る機種の割合>={S1_WIDE_SHARE}",
            "S1_concentrated": f"正の超過の上位2機種占有>={S1_CONC_TOP2}", "high_posterior": HIGH_POSTERIOR,
            "F1": "D・末尾は±1(円環)、曜日は±1、DDは±1、端番は±1、機種・島は同タイプで台数が近い2つ、台番号は±1",
        },
    }  # fmt: skip


# ---------------------------------------------------------------- 水準
def month_windows(asof: str, count: int = 4) -> dict[str, tuple[str, str]]:
    out = {}
    d = to_date(asof).replace(day=1)
    for _ in range(count):
        end = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        out[f"m{d:%Y%m}"] = (to_ds(d), min(to_ds(end), asof))
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return out


def level_windows(asof: str) -> dict[str, tuple[str, str]]:
    win = {
        "1m": (shift_ds(asof, -29), asof),
        "2m": (shift_ds(asof, -59), asof),
        "3m": (shift_ds(asof, -89), asof),
        "train": (shift_ds(asof, -119), shift_ds(asof, -30)),
        "verify": (shift_ds(asof, -29), asof),
    }
    win.update(month_windows(asof))
    return win


def pick_top(cells: pd.DataFrame, metrics, limit=5, window="3m") -> list[dict]:
    """正の効果で p が小さいものから、指標ごとに候補を選ぶ(5件まで)。"""
    if not len(cells):
        return []
    top = []
    part = cells[(cells.window == window) & cells.effect.notna() & (cells.effect > 0)]
    for metric in metrics:
        for r in part[part.metric == metric].sort_values(["p", "effect"], ascending=[True, False]).head(2).itertuples():
            top.append(
                dict(
                    label=str(r.unit), metric=metric, n_days=int(r.n_days), effect=round(float(r.effect), 3),
                    ci=[_round(r.ci_lo), _round(r.ci_hi)], q=_round(r.q), contrast=r.contrast, level=str(r.level),
                    falsification="未実施", next_month="未検証",
                )
            )  # fmt: skip
    # 回転数は設定の根拠にならないので、同じ q なら後ろへ(客の集中を拾うだけのことが多い)。
    top.sort(key=lambda x: (x["metric"] == "回転数", x["q"] if x["q"] is not None else 1.0))
    return top[:limit]


def next_month(primary: pd.DataFrame) -> dict:
    """train の窓だけで選んだ上位が、verify の窓で残るか。全単位の順位相関も出す。"""
    report, selected = [], {}
    for (kind, metric), part in primary.groupby(["unit_kind", "metric"]):
        train = part[part.window == "train"].set_index("unit")
        verify = part[part.window == "verify"].set_index("unit")
        both = train.index.intersection(verify.index)
        if len(both) < 3:
            continue
        rho = train.loc[both].effect.astype(float).corr(verify.loc[both].effect.astype(float), method="spearman")
        chosen = train.loc[both].sort_values("effect", ascending=False).head(max(2, len(both) // 10))
        report.append(
            dict(
                unit_kind=kind, metric=metric, n_units=len(both), spearman_train_verify=_round(rho, 3),
                top_units=list(chosen.index[:5]), train_mean=_round(chosen.effect.mean(), 3),
                verify_mean=_round(verify.loc[chosen.index].effect.mean(), 3),
                verify_all_mean=_round(verify.loc[both].effect.mean(), 3),
            )
        )  # fmt: skip
        for unit in chosen.index:
            selected[(str(unit), metric)] = _round(verify.loc[unit].effect, 3)
    return {"report": report, "selected": selected}


def _level_axis(
    ledger,
    axis_id,
    unit_defs,
    base,
    metrics,
    wins,
    iters,
    rng,
    contrasts_of,
    primary_contrast,
    scope_note,
    caveats,
    runner,
):
    cells, excluded, planned = [], [], 0
    for col, kind in unit_defs:
        earliest = min(v[0] for v in wins.values())  # どの窓にも出ない過去の機種・台は予定に入れない
        all_units = sorted(base[base[col].notna() & (base.ds >= earliest)][col].astype(str).unique())
        for metric in metrics:
            for window, (start, end) in wins.items():
                part = base[(base.ds >= start) & (base.ds <= end) & base[col].notna()]
                days = sorted(part.ds.unique())
                min_days = max(5, int(len(days) * 0.5))
                for contrast, group, whole_unit in contrasts_of(col):
                    planned += len(all_units)
                    if part.empty:
                        excluded += [_ex(axis_id, kind, u, "", metric, contrast, window, "NO_ROWS") for u in all_units]
                        continue
                    frame = (
                        unit_level_residual(part, metric, col, group)
                        if whole_unit
                        else residual_rows(part, metric, ["ds", *group])
                    )
                    table = boot_table(frame, col, days, iters, rng, min_days)
                    qs = ax.bh_adjust(table.p.to_numpy(float)) if len(table) else []
                    for r, q in zip(table.itertuples(), qs):
                        cells.append(
                            dict(
                                unit_kind=kind, unit=str(r.unit), level="", metric=metric, contrast=contrast, window=window,
                                n_days=int(r.n_days), n_units=1, effect=r.effect, ci_lo=r.ci_lo, ci_hi=r.ci_hi, p=r.p, q=q,
                                family=f"{axis_id}|{kind}|{metric}|{contrast}|{window}",
                            )
                        )  # fmt: skip
                    present = set(table.unit) if len(table) else set()
                    excluded += [
                        _ex(axis_id, kind, u, "", metric, contrast, window, "FEW_DAYS_OR_NO_CONTRAST")
                        for u in all_units
                        if u not in present
                    ]
    cell_df = pd.DataFrame(cells)
    extra, top, power = {}, [], ""
    if len(cell_df):
        primary = cell_df[cell_df.contrast == primary_contrast]
        top = pick_top(primary, [m for m in metrics if m != "差枚"])
        nm = next_month(primary)
        extra["next_month"] = nm["report"]
        for item in top:
            match = nm["selected"].get((item["label"], item["metric"]))
            if match is not None:
                item["next_month"] = "済"
                item["verify_effect"] = match
        w3 = cell_df[cell_df.window == "3m"]
        half = ((w3.ci_hi.astype(float) - w3.ci_lo.astype(float)) / 2).groupby(w3.metric).median()
        power = "; ".join(f"{m}: 3m の CI 半幅の中央値 ±{v:.3f}" for m, v in half.items())
    return ledger.record(
        axis_id, planned=planned, cells=cell_df, excluded=excluded, unit="/".join(k for _, k in unit_defs), metrics=",".join(metrics),
        window=",".join(wins), scope=scope_note, basis="ex_post", runner=runner, top=top, power=power, caveats=caveats, extra=extra,
        n_days=base[base.ds >= shift_ds(ledger.asof, -89)].ds.nunique(), n_units=base.machine_name.nunique(),
    )  # fmt: skip


def run_levels(ledger, df, metrics, iters, rng):
    base = df[~df.is_new]
    wins = level_windows(ledger.asof)
    has_layout = base.section.notna().any()

    def contrasts_of(col):
        if col == "machine_name":
            return [("vs_hall", [], True), ("vs_type", ["type"], True)]
        return [("vs_hall", [], False), ("within_machine", ["machine_name"], False)]

    defs = {"L1": [("machine_name", "機種")], "L4": [("machine_number", "台番号")], "L5": [("ld", "末尾")]}
    if has_layout:
        defs["L2"] = [("section", "島")]
        defs["L3"] = [("edge", "端番"), ("aisle", "通路角")]
    else:
        ledger.not_run("L2", "データ不足", "machine_layout_history が空で、島を定義できない")
        ledger.not_run("L3", "データ不足", "machine_layout_history が空で、角番を定義できない")
    note = (
        f"単位×指標{len(metrics)}×窓{len(wins)}×対比2(全組み合わせ、2軸)。train で選び verify で確かめる翌月検証を含む"
    )
    caveats = [
        "新台(導入後7日)は除外",
        "同じ日の他の台日との差で、当日の比較なので事後分析",
        "差枚と機械割差は1つの証拠として数える",
    ]
    for axis_id, unit_defs in defs.items():
        _level_axis(ledger, axis_id, unit_defs, base, metrics, wins, iters, rng, contrasts_of,
                    "vs_hall" if axis_id == "L1" else "within_machine", note, caveats, "theory_rescan.run_levels")  # fmt: skip
    # P5: 機種の台数区分。P6: 同じ島で隣が別機種の台。
    wins2 = {"3m": wins["3m"], "all": (base.ds.min(), ledger.asof)}
    count = base.groupby(["ds", "machine_name"]).machine_number.transform("nunique")
    sized = base.assign(
        size_bin=pd.cut(
            count, [0, 2, 5, 10, 20, 10000], labels=["1-2台", "3-5台", "6-10台", "11-20台", "21台以上"]
        ).astype(str)
    )
    _level_axis(ledger, "P5", [("size_bin", "機種の台数")], sized, metrics, wins2, iters, rng, lambda c: [("vs_hall", [], False)], "vs_hall",
                f"区分5×指標{len(metrics)}×窓2", ["機種の水準と分離しない。台数で揃えた機種比較ではない"], "theory_rescan.run_levels")  # fmt: skip
    if not has_layout:
        ledger.not_run("P6", "データ不足", "machine_layout_history が空で、隣接を定義できない")
        return
    lay = base[base.section.notna()][["ds", "machine_number", "machine_name", "section"]]
    left = lay.assign(machine_number=lay.machine_number + 1).rename(columns={"machine_name": "m_l", "section": "s_l"})
    right = lay.assign(machine_number=lay.machine_number - 1).rename(columns={"machine_name": "m_r", "section": "s_r"})
    merged = lay.merge(left, on=["ds", "machine_number"], how="left").merge(
        right, on=["ds", "machine_number"], how="left"
    )
    boundary = ((merged.s_l == merged.section) & (merged.m_l != merged.machine_name)) | (
        (merged.s_r == merged.section) & (merged.m_r != merged.machine_name)
    )
    key = merged[["ds", "machine_number"]].assign(bd=np.where(boundary, "機種の境界", "機種の内側"))
    enriched = base[base.section.notna()].merge(key, on=["ds", "machine_number"], how="inner")
    _level_axis(ledger, "P6", [("bd", "機種の境界")], enriched, metrics, wins2, iters, rng, lambda c: [("within_machine", ["machine_name"], False)],
                "within_machine", f"2区分×指標{len(metrics)}×窓2", ["隣は台番号の連番で近似"], "theory_rescan.run_levels")  # fmt: skip


# ---------------------------------------------------------------- 時間軸
def time_axis_levels(days: list[str], hall: str, regime: str | None) -> dict[str, dict[str, np.ndarray]]:
    ev = ut.event_dates(hall)
    all_ev = set().union(*ev.values()) if ev else set()
    labels = ut.time_labels(days, pd.Series(np.ones(len(days)), index=days), all_ev)
    out = {
        "T1": labels["曜日"],
        "T2": labels["D(下一桁)"],
        "T3": labels["DD(日付)"],
        "T4": labels["ゾロ目"],
        "T5": {**labels["月内の週"], **labels["給料日・月末"]},
        "T6": {**labels["祝日"], "連休(3日以上の土日祝)": holiday_runs(days)},
    }
    if all_ev:
        out["T7"] = labels["イベント日(台帳)"]
        out["T9"] = {k: np.array([d in v for d in days]) for k, v in ev.items()}
    series = ax.time_axes(days, hall).get("イベント・公約")
    if series:
        out["T8"] = {n: series[1][:, i] for i, n in enumerate(series[0])}
    if regime:
        out["T10"] = {f"{regime}以降": np.array([d >= regime for d in days])}
    return out


def time_matrices(df: pd.DataFrame, metric: str, days: list[str], units: list[str], col: str):
    """日×単位の分子・分母。基準は窓の中の機種平均(機種構成を除く。in_sample)。"""
    part = df
    if metric in ("RB無補正", "RB帯補正", "AT無補正", "AT帯補正"):
        part = part[(part.hit_kind == metric[:2]) & (part.G > 0)]
        keys = ["machine_name"] if metric.endswith("無補正") else ["machine_name", "band"]
        grouped = part.groupby(keys)
        rate = grouped.hit.transform("sum") / grouped.G.transform("sum")
        num, den = part.hit.to_numpy(float), (part.G * rate).to_numpy(float)
    elif metric == "機械割差":
        part = part[part.G > 0]
        grouped = part.groupby("machine_name")
        rate = grouped["diff"].transform("sum") / (3.0 * grouped.G.transform("sum"))
        num, den = 100.0 * (part["diff"] - 3.0 * part.G * rate).to_numpy(float), 3.0 * part.G.to_numpy(float)
    elif metric == "差枚":
        num, den = (
            (part["diff"] - part.groupby("machine_name")["diff"].transform("mean")).to_numpy(float),
            np.ones(len(part)),
        )
    elif metric == "回転数":
        num, den = (part.G - part.groupby("machine_name").G.transform("mean")).to_numpy(float), np.ones(len(part))
    else:
        raise ValueError(metric)
    di = {d: i for i, d in enumerate(days)}
    ui = {u: i for i, u in enumerate(units)}
    NUM, DEN = np.zeros((len(days), len(units))), np.zeros((len(days), len(units)))
    if len(part):
        unit_ix = part[col].map(ui)
        ok = unit_ix.notna().to_numpy()
        ix = (part.ds.map(di).to_numpy()[ok], unit_ix.to_numpy()[ok].astype(int))
        np.add.at(NUM, ix, num[ok])
        np.add.at(DEN, ix, den[ok])
    return NUM, DEN


def time_stats(L, NUM, DEN):
    L = L.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (L @ NUM) / (L @ DEN) - ((1 - L) @ NUM) / ((1 - L) @ DEN)


def run_time_axes(ledger, df, metrics, cfg, iters, rng):
    base = df[~df.is_new].assign(all_units="全台")
    wins = {"3m": shift_ds(ledger.asof, -89), "all": base.ds.min()}
    if cfg.get("regime"):
        wins["regime"] = cfg["regime"]
    time_metrics = [m for m in ("機械割差", "差枚", "回転数") if m in metrics]
    if "RB位置" in metrics:
        time_metrics += ["RB無補正", "RB帯補正"]
    if "AT位置" in metrics:
        time_metrics += ["AT無補正", "AT帯補正"]
    store, excluded, planned, day_count = {}, {}, {}, {}
    for window, start in wins.items():
        part = base[base.ds >= start]
        days = sorted(part.ds.unique())
        day_count[window] = len(days)
        axes = time_axis_levels(days, cfg["hall"], cfg.get("regime") if window == "all" else None)
        for kind, col in (("全台", "all_units"), ("タイプ", "type")):
            units = sorted(part[col].unique())
            for metric in time_metrics:
                NUM, DEN = time_matrices(part, metric, days, units, col)
                for axis_id, levels in axes.items():
                    pix = ut.perm_index(ut.strata_of("曜日" if axis_id == "T1" else "other", days), iters, rng)
                    results = []
                    for name, lab in levels.items():
                        lab = np.asarray(lab, bool)
                        planned[axis_id] = planned.get(axis_id, 0) + len(units)
                        if lab.sum() < 3 or (~lab).sum() < 3:
                            excluded.setdefault(axis_id, []).extend(
                                _ex(axis_id, kind, u, name, metric, "in_vs_out", window, "FEW_DAYS") for u in units
                            )
                            continue
                        obs = time_stats(lab[None], NUM, DEN)[0]
                        sims = time_stats(lab[pix], NUM, DEN)
                        sd = np.nanstd(sims, axis=0)
                        sd[sd == 0] = np.nan
                        results.append((name, lab, obs, sims / sd, sd))
                    if not results:
                        continue
                    zs = np.stack([r[3] for r in results])
                    zmax = np.nanmax(np.where(np.isfinite(zs), np.abs(zs), -1), axis=(0, 2))
                    for name, lab, obs, z_sim, sd in results:
                        for k, u in enumerate(units):
                            z = obs[k] / sd[k] if np.isfinite(sd[k]) else np.nan
                            if not np.isfinite(z):
                                excluded.setdefault(axis_id, []).append(
                                    _ex(axis_id, kind, u, name, metric, "in_vs_out", window, "NO_METRIC")
                                )
                                continue
                            store.setdefault(axis_id, []).append(
                                dict(
                                    unit_kind=kind, unit=u, level=name, metric=metric, contrast="in_vs_out", window=window,
                                    n_days=int(lab.sum()), n_units=1, effect=obs[k], ci_lo=obs[k] - 1.96 * sd[k],
                                    ci_hi=obs[k] + 1.96 * sd[k], p=(1 + np.sum(np.abs(z_sim[:, k]) >= abs(z))) / (1 + iters),
                                    family=f"{axis_id}|{kind}|{metric}|{window}",
                                    note=f"p_family={(1 + np.sum(zmax >= abs(z))) / (1 + iters):.4f}",
                                )
                            )  # fmt: skip
    for axis_id in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10"):
        if axis_id not in planned:
            reason = (
                "レジーム境界が未確定"
                if axis_id == "T10"
                else "イベント台帳にこのホールの行がない、または3日以上の系列がない"
            )
            ledger.not_run(axis_id, "データ不足", reason)
            continue
        cell_df = pd.DataFrame(store.get(axis_id, []))
        if len(cell_df):
            cell_df["q"] = np.nan
            for _, idx in cell_df.groupby("family").groups.items():
                cell_df.loc[idx, "q"] = ax.bh_adjust(cell_df.loc[idx, "p"].to_numpy(float))
        win = "all" if axis_id == "T10" else "3m"
        power = ""
        if len(cell_df) and (cell_df.window == win).any():
            w = cell_df[cell_df.window == win]
            size = ((w.ci_hi - w.effect) / 1.96).groupby(w.metric).median() * 2.8
            power = "; ".join(f"{m}: 80%検出の目安 ±{v:.3f}" for m, v in size.items())
        ledger.record(
            axis_id, planned=planned[axis_id], cells=cell_df, excluded=excluded.get(axis_id, []), unit="全台/タイプ", metrics=",".join(time_metrics),
            window=",".join(wins), scope=f"窓{len(wins)}×単位(全台+タイプ)×指標{len(time_metrics)}×水準。全組み合わせ(2軸)。3日未満の水準は除外",
            basis="in_sample", runner="theory_rescan.run_time_axes(unit_time_scan の水準と入れ替えを再利用)",
            top=pick_top(cell_df, [m for m in time_metrics if m != "差枚"], window=win), power=power,
            caveats=["基準は窓全体の機種平均なので in_sample。開店前の評価には使わない", "RBは帯補正あり・なしを並べる。符号が割れたら判定しない"],
            n_days=day_count.get("3m", 0), n_units=base.machine_name.nunique(), families=cell_df.family.nunique() if len(cell_df) else 0,
        )  # fmt: skip


# ---------------------------------------------------------------- 履歴軸
def history_panel(df, metric, col, calendar):
    """暦日×単位の分子・分母・観測あり・機種コード(台番号単位のときだけ意味を持つ)。"""
    num, den, mask = metric_arrays(df, metric)
    part = df.loc[mask].assign(_n=num[mask], _d=den[mask])
    part = part[part[col].notna()]
    units = sorted(part[col].astype(str).unique())
    di = {d: i for i, d in enumerate(calendar)}
    ui = {u: i for i, u in enumerate(units)}
    N, D, O = (np.zeros((len(calendar), len(units))) for _ in range(3))
    M = np.full((len(calendar), len(units)), -1, int)
    if len(part):
        ix = (part.ds.map(di).to_numpy(), part[col].astype(str).map(ui).to_numpy())
        np.add.at(N, ix, part._n.to_numpy(float))
        np.add.at(D, ix, part._d.to_numpy(float))
        np.add.at(O, ix, 1.0)
        if col == "machine_number":
            M[ix] = part.machine_name.astype("category").cat.codes.to_numpy()
    return units, N, D, O, M


def history_feature(N, D, O, M, d, lag_from, lag_to, *, per_unit_min, frac=0.7, same_machine=False):
    """対象日 d(暦日の位置)の特徴量。窓は [d-lag_to, d-lag_from] で、d を含まない。"""
    a, b = d - lag_to, d - lag_from + 1
    if a < 0:
        return np.full(N.shape[1], np.nan)
    keep = (M[a:b] == M[d]) if same_machine else np.ones((b - a, N.shape[1]), bool)
    n, den = (N[a:b] * keep).sum(0), (D[a:b] * keep).sum(0)
    obs = ((O[a:b] > 0) & keep).sum(0)
    length = lag_to - lag_from + 1
    need = 1 if length == 1 else (max(per_unit_min, 10) if same_machine else max(per_unit_min, int(length * frac)))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = n / den
    out[(obs < need) | (den <= 0)] = np.nan
    return out


def _within_groups(values, groups):
    """日の断面を、群ごとに平均を引く。群が2未満の値は NaN。"""
    out = np.full(values.shape, np.nan)
    ok = np.isfinite(values)
    for g in np.unique(groups[ok]):
        ix = ok & (groups == g)
        if ix.sum() >= 2:
            out[ix] = values[ix] - values[ix].mean()
    return out


def _rank_z(values):
    out = np.full(values.shape, np.nan)
    ok = np.isfinite(values)
    if ok.sum() < 3:
        return out
    ranks = pd.Series(values[ok]).rank().to_numpy()
    sd = ranks.std()
    if sd > 0:
        out[ok] = (ranks - ranks.mean()) / sd
    return out


def history_cell(panel, cal_ix, weekday, lags, col, demean, iters, rng):
    """1セルの結果: 日ごとの順位相関の平均、入れ替えp、上位25%−下位25%の差。"""
    _, N, D, O, M = panel
    same = col == "machine_number"
    T, U = len(cal_ix), N.shape[1]
    F, Y, QD = np.full((T, U), np.nan), np.full((T, U), np.nan), []
    for t, d in enumerate(cal_ix):
        feat = history_feature(N, D, O, M, d, *lags, per_unit_min=10, same_machine=same)
        with np.errstate(invalid="ignore", divide="ignore"):
            now = np.where((O[d] > 0) & (D[d] > 0), N[d] / D[d], np.nan)
        if demean:
            long_run = history_feature(N, D, O, M, d, 1, LONG_RUN_DAYS, per_unit_min=10, frac=0.3, same_machine=same)
            feat, now = feat - long_run, now - long_run
        groups = M[d] if same else np.zeros(U, int)
        feat = _within_groups(np.where(np.isfinite(now), feat, np.nan), groups)
        now = _within_groups(np.where(np.isfinite(feat), now, np.nan), groups)
        ok = np.isfinite(feat) & np.isfinite(now)
        if ok.sum() >= 8:
            top, bot = ok & (feat >= np.quantile(feat[ok], 0.75)), ok & (feat <= np.quantile(feat[ok], 0.25))
            if top.any() and bot.any():
                QD.append(now[top].mean() - now[bot].mean())
        F[t], Y[t] = _rank_z(feat), _rank_z(now)
    mf, my = np.isfinite(F), np.isfinite(Y)
    valid = (mf & my).sum(1) >= 5
    if valid.sum() < 10:
        return None
    S = np.nan_to_num(F) @ np.nan_to_num(Y).T
    C = mf.astype(float) @ my.astype(float).T
    with np.errstate(invalid="ignore", divide="ignore"):
        R = S / C
    use = np.where(valid)[0]
    daily = np.diag(R)[use]
    daily = np.where(np.isfinite(daily), daily, 0.0)
    obs = float(daily.mean())
    # 主検定は日ごとの順位相関のブロックブートストラップ(ゼロとの差)。曜日の中の入れ替えは、窓の特徴量が
    # 近い日どうしで似るだけで小さくなり、大きさのない差を有意にするので note の参考値に留める。
    sims = block_weights(len(daily), iters, rng) @ daily / len(daily)
    p = float(max(min(1.0, 2 * min((sims <= 0).mean(), (sims >= 0).mean())), 1.0 / iters))
    pix = ut.perm_index(np.asarray(weekday)[use], min(iters, 500), rng)
    perm = np.nanmean(R[use[pix], use[None, :]], axis=1)
    p_perm = (1 + np.sum(np.abs(perm - np.nanmean(perm)) >= abs(obs - np.nanmean(perm)))) / (1 + len(perm))
    return dict(
        n_days=int(valid.sum()), rho=obs, p=p, ci=(float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))),
        p_perm=float(p_perm), qdiff=float(np.mean(QD)) if QD else np.nan,
    )  # fmt: skip


def run_history(ledger, df, metrics, iters, rng):
    base = df[~df.is_new]
    asof = ledger.asof
    calendar = pd.date_range(base.ds.min(), asof).strftime("%Y%m%d").tolist()
    pos = {d: i for i, d in enumerate(calendar)}
    windows = {"3m": (shift_ds(asof, -89), asof), "prev3m": (shift_ds(asof, -179), shift_ds(asof, -90))}
    units = [("machine_name", "機種"), ("machine_number", "台番号"), ("ld", "末尾")]
    if base.section.notna().any():
        units += [("section", "島"), ("edge", "端番")]
    panels = {(col, m): history_panel(base, m, col, calendar) for col, _ in units for m in metrics}
    for hid, lags in HISTORY_WINDOWS.items():
        cells, excluded, planned = [], [], 0
        for col, kind in units:
            for metric in metrics:
                panel = panels[(col, metric)]
                for window, (start, end) in windows.items():
                    cal_ix = [pos[d] for d in calendar if start <= d <= end]
                    weekday = [to_date(calendar[i]).weekday() for i in cal_ix]
                    for variant, demean in (("raw", False), ("own_level_removed", True)):
                        planned += 1
                        label = f"{kind}|{metric}|{variant}"
                        if len(panel[0]) < 5:
                            excluded.append(_ex(hid, kind, label, "", metric, variant, window, "FEW_UNITS"))
                            continue
                        res = history_cell(panel, cal_ix, weekday, lags, col, demean, iters, rng)
                        if res is None:
                            excluded.append(_ex(hid, kind, label, "", metric, variant, window, "FEW_DAYS"))
                            continue
                        cells.append(
                            dict(
                                unit_kind=kind, unit=label, level="", metric=metric, contrast=variant, window=window,
                                n_days=res["n_days"], n_units=len(panel[0]), effect=res["rho"], ci_lo=res["ci"][0], ci_hi=res["ci"][1], p=res["p"],
                                family=f"{hid}|{window}", note=f"上位25%-下位25%={res['qdiff']:.3f},p_入れ替え={res['p_perm']:.4f}",
                            )
                        )  # fmt: skip
        cell_df = pd.DataFrame(cells)
        power = ""
        if len(cell_df):
            cell_df["q"] = np.nan
            for _, idx in cell_df.groupby("family").groups.items():
                cell_df.loc[idx, "q"] = ax.bh_adjust(cell_df.loc[idx, "p"].to_numpy(float))
            power = f"順位相関の CI 半幅の中央値 ±{((cell_df.ci_hi - cell_df.ci_lo) / 2).median():.3f}"
        ledger.record(
            hid, planned=planned, cells=cell_df, excluded=excluded, unit="/".join(k for _, k in units), metrics=",".join(metrics), window="3m,prev3m",
            scope=f"単位{len(units)}×指標{len(metrics)}×窓2×(素の値/自分の長期水準を引く)。全期間は計算量で対象外(前の3か月を再現確認に置く)",
            basis="as_of", runner="theory_rescan.run_history", top=pick_top(cell_df[cell_df.contrast == "own_level_removed"], metrics) if len(cell_df) else [], power=power,
            caveats=["top は自分の長期水準を引いた版から選ぶ。素の値は日を問わない強さ(水準)を再検出するだけなので候補にしない", "特徴量は対象日より前だけ。結果(当日の値)は同日の断面で引いたもの", "台番号は同じ機種の期間だけで窓を作る"],
            n_days=len([d for d in calendar if d >= windows["3m"][0]]), n_units=base.machine_number.nunique(),
            families=cell_df.family.nunique() if len(cell_df) else 0,
        )  # fmt: skip


# ---------------------------------------------------------------- S1・V1・N1・絶対数
def s1_classify(day: pd.DataFrame) -> dict:
    """1日の分類。day は機種ごとの active, good, expected を持つ(台数の下限を満たす機種だけ)。"""
    excess = day.good - day.expected
    above = float((excess > 0).mean())
    pos = excess.clip(lower=0)
    total = pos.sum()
    share = (pos / total) if total > 0 else pos * 0
    top = day.assign(s=share).sort_values("s", ascending=False)
    top2 = float(top.s.head(2).sum())
    label = "全体型" if above >= S1_WIDE_SHARE else "集中型" if top2 >= S1_CONC_TOP2 and total > 0 else "どちらでもない"
    return dict(
        label=label,
        above_share=above,
        top2_share=top2,
        hhi=float((share**2).sum()),
        top="/".join(top.machine_name.head(2)),
    )


def run_s1(ledger, df, cfg):
    base = df[~df.is_new & (df.G > 0)]
    wins = {"3m": shift_ds(ledger.asof, -89)}
    if cfg.get("regime"):
        wins["regime"] = cfg["regime"]
    wins["all"] = base.ds.min()
    ev = ut.event_dates(cfg["hall"])
    event_days = set().union(*ev.values()) if ev else set()
    cells, excluded, planned, extra = [], [], 0, {}
    for window, start in wins.items():
        part = base[base.ds >= start].copy()
        payout = 100 + 100 * part["diff"] / (3 * part.G)
        part["good"] = ((part.G >= S1_GOOD_GAMES) & (payout >= S1_GOOD_PAYOUT)).astype(float)
        by_m = part.groupby(["ds", "machine_name"]).agg(active=("good", "size"), good=("good", "sum")).reset_index()
        by_m["expected"] = by_m.active * by_m.machine_name.map(part.groupby("machine_name").good.mean())
        by_m = by_m[by_m.active >= S1_MIN_ACTIVE]
        rate = part.groupby("machine_name")["diff"].sum() / (3 * part.groupby("machine_name").G.sum())
        expect = (3 * part.G * part.machine_name.map(rate)).groupby(part.ds).sum()
        hall_day = part.groupby("ds").agg(diff=("diff", "sum"), games=("G", "sum"))
        resid = 100 * (hall_day["diff"] - expect) / (3 * hall_day.games)
        labels = []
        for d in sorted(part.ds.unique()):
            planned += 1
            day = by_m[by_m.ds == d]
            if len(day) < 3:
                excluded.append(_ex("S1", "日", d, "", "好調台", "機種の期間平均", window, "FEW_MACHINES"))
                continue
            info = s1_classify(day)
            labels.append((d, info["label"], info["top"]))
            cells.append(
                dict(
                    unit_kind="日", unit=d, level=info["label"], metric="好調台", contrast="機種の期間平均", window=window, n_days=1,
                    n_units=len(day), effect=info["above_share"], family=f"S1|{window}",
                    note=f"top2={info['top2_share']:.3f},hhi={info['hhi']:.3f},中心={info['top']},全体機械割差={resid.get(d, np.nan):.2f}",
                )
            )  # fmt: skip
        tab = pd.DataFrame(labels, columns=["ds", "label", "top"])
        if len(tab):
            tab["event"] = tab.ds.isin(event_days)
            tab["resid"] = tab.ds.map(resid)
            centers = tab[tab.label == "集中型"].top.str.split("/").explode()
            extra[window] = {
                "n_days": len(tab), "counts": tab.label.value_counts().to_dict(),
                "event_counts": tab[tab.event].label.value_counts().to_dict(), "event_days": int(tab.event.sum()),
                "hall_resid_pt_by_label": {k: _round(v, 2) for k, v in tab.groupby("label").resid.mean().items()},
                "center_machines": centers.value_counts().head(5).to_dict() if len(centers) else {},
            }  # fmt: skip
    ledger.record(
        "S1", planned=planned, cells=cells, excluded=excluded, unit="日", metrics="好調台(G>=3000かつ機械割>=105%)", window=",".join(wins),
        scope="日×窓。分類は開始時に固定した規則", basis="in_sample", runner="theory_rescan.run_s1",
        caveats=["基準は窓全体の機種の好調率。検定なしの分類で、件数を見るためのもの", f"台数{S1_MIN_ACTIVE}台未満の機種は除く"],
        extra=extra, n_days=extra.get("3m", {}).get("n_days", 0), n_units=base.machine_name.nunique(),
    )  # fmt: skip


def run_v1(ledger, df, cfg, iters, rng):
    asof = ledger.asof
    start = shift_ds(asof, -89)
    base = df[~df.is_new & (df.ds >= start) & (df.G > 0)].copy()
    days = sorted(base.ds.unique())
    ev = ut.event_dates(cfg["hall"])
    event_days = set().union(*ev.values()) if ev else set()
    is_event = np.array([d in event_days for d in days])
    pix = ut.perm_index(np.array([to_date(d).weekday() for d in days]), iters, rng)
    base["pt"] = 100 * base["diff"] / (3 * base.G)
    history = df[(~df.is_new) & (df.ds < start) & (df.ds >= shift_ds(start, -90)) & (df.G > 0)]
    base["above_own_p75"] = base.G > base.machine_name.map(history.groupby("machine_name").G.quantile(0.75)).fillna(
        np.inf
    )
    ref = base[base.hit_kind.notna()].groupby(["machine_name", "band"]).agg(h=("hit", "sum"), g=("G", "sum"))
    base = base.join((ref.h / ref.g).rename("band_rate"), on=["machine_name", "band"])
    groups = (
        [("機種", m) for m in sorted(base.machine_name.unique())]
        + [("タイプ", t) for t in sorted(base.type.unique())]
        + [("全台", "全台")]
    )
    masks = {
        g: (base.machine_name == g[1])
        if g[0] == "機種"
        else (base.type == g[1])
        if g[0] == "タイプ"
        else pd.Series(True, index=base.index)
        for g in groups
    }
    cells, excluded, planned, repeats = [], [], 0, []
    for gmin in V1_GAMES:
        for lossdef, lossmask in (
            (f"差枚<={V1_LOSS_COINS}", base["diff"] <= V1_LOSS_COINS),
            (f"機械割差<={V1_LOSS_PT}pt", base.pt <= V1_LOSS_PT),
        ):
            flag = (base.G >= gmin) & lossmask
            rep = base[flag].groupby(["machine_number", "machine_name"]).ds.nunique()
            repeats += [
                dict(gmin=gmin, loss=lossdef, machine_number=int(k[0]), machine_name=k[1], times=int(v))
                for k, v in rep[rep >= 2].items()
            ]
            for group in groups:
                kind, name = group
                planned += 1
                label = f"{name}|{gmin}G|{lossdef}"
                part = base[masks[group]]
                flagged = part[flag.reindex(part.index)]
                total = part.groupby("ds").size().reindex(days).fillna(0).to_numpy()
                hits = flagged.groupby("ds").size().reindex(days).fillna(0).to_numpy()
                ok = total > 0
                if not event_days or (is_event & ok).sum() < 3 or (~is_event & ok).sum() < 3:
                    excluded.append(_ex("V1", kind, label, "", "発生率", "イベント日vs他", "3m", "FEW_EVENT_DAYS"))
                    continue
                rate = np.divide(hits, total, out=np.full(len(days), np.nan), where=ok)
                arr = np.nan_to_num(rate)
                w = ok.astype(float)
                L = is_event[pix].astype(float)
                with np.errstate(invalid="ignore", divide="ignore"):
                    sims = (L @ arr) / (L @ w) - ((1 - L) @ arr) / ((1 - L) @ w)
                obs = np.nanmean(rate[is_event]) - np.nanmean(rate[~is_event])
                sd = np.nanstd(sims)
                p = (1 + np.nansum(np.abs(sims) >= abs(obs))) / (1 + iters) if sd > 0 else 1.0
                hit_rows = flagged[flagged.hit_kind.notna()]
                oe = hit_rows.hit.sum() / (hit_rows.G * hit_rows.band_rate).sum() if len(hit_rows) else np.nan
                above = float(flagged.above_own_p75.mean()) if len(flagged) else np.nan
                cells.append(
                    dict(
                        unit_kind=kind, unit=label, level=name, metric="発生率", contrast="イベント日vs他", window="3m", n_days=int(ok.sum()),
                        n_units=int(part.machine_number.nunique()), effect=obs, ci_lo=obs - 1.96 * sd, ci_hi=obs + 1.96 * sd, p=p,
                        family=f"V1|{gmin}|{lossdef}",
                        note=f"該当{len(flagged)}台日,通常率={np.nanmean(rate[~is_event]):.4f},同帯当りO/E={oe:.3f},自機種p75超={above:.2f}",
                    )
                )  # fmt: skip
    cell_df = pd.DataFrame(cells)
    if len(cell_df):
        cell_df["q"] = np.nan
        for _, idx in cell_df.groupby("family").groups.items():
            cell_df.loc[idx, "q"] = ax.bh_adjust(cell_df.loc[idx, "p"].to_numpy(float))
    rep_df = pd.DataFrame(repeats)
    rep_df.to_csv(ledger.dir / "V1_repeat.csv", index=False, encoding="utf-8-sig")
    top_rep = (
        rep_df[rep_df.gmin == 5000].sort_values("times", ascending=False).head(10).to_dict("records")
        if len(rep_df)
        else []
    )
    ledger.record(
        "V1", planned=planned, cells=cell_df, excluded=excluded, unit="機種/タイプ/全台", metrics="発生率,同帯当りO/E", window=f"{start}-{asof}",
        scope="群×3G閾値×2負け定義。比較はイベント日と他の日(曜日の中で入れ替え)。日を1観測にする", basis="ex_post", runner="theory_rescan.run_v1",
        top=pick_top(cell_df, ["発生率"]),
        caveats=[
            "大負け×高回転だけでは要確認候補。確認済みのRB・AT当り率の裏付けがあるものだけ不発候補",
            "日次の合計なので、負けてから回されたのか先に好調で後から負けたのかは判別できない",
            "新台は除外。機種人気は「自機種の前の90日のp75超」の割合で併記",
        ],
        extra={"repeat_top_5000G": top_rep, "repeat_file": "V1_repeat.csv"}, n_days=len(days), n_units=base.machine_number.nunique(),
    )  # fmt: skip


def run_n1(ledger, df, metrics, db_min, iters, rng):
    first = df.groupby("machine_name").first_seen.first()
    debuted = first[first > db_min]
    cells, excluded, planned, paired = [], [], 0, []
    recent_from = shift_ds(ledger.asof, -179)
    for name, f in debuted.items():
        part = df[df.machine_name == name].copy()
        part["el"] = (pd.to_datetime(part.ds) - pd.to_datetime(f)).dt.days
        for metric in metrics:
            num, den, mask = metric_arrays(part, metric)
            tb = part.loc[mask].assign(_n=num[mask], _d=den[mask])
            if not len(tb):
                continue  # この機種に当てはまらない指標は予定に入れない
            post = tb[(tb.el >= 8) & (tb.el <= 35)]
            ref = post._n.sum() / post._d.sum() if post._d.sum() > 0 else np.nan
            for el in range(7):
                planned += 1
                sub = tb[tb.el == el]
                if not len(sub) or sub._d.sum() <= 0:
                    excluded.append(_ex("N1", "機種", name, f"d{el}", metric, "vs自分のd8-35", f, "NO_ROWS"))
                elif not np.isfinite(ref):
                    excluded.append(_ex("N1", "機種", name, f"d{el}", metric, "vs自分のd8-35", f, "NO_POST_PERIOD"))
                else:
                    cells.append(
                        dict(
                            unit_kind="機種", unit=name, level=f"d{el}", metric=metric, contrast="vs自分のd8-35", window=f, n_days=1,
                            n_units=int(sub.machine_number.nunique()), effect=sub._n.sum() / sub._d.sum() - ref, family=f"N1|{metric}",
                        )
                    )  # fmt: skip
            early = tb[tb.el <= 6]
            if early._d.sum() > 0 and np.isfinite(ref):
                paired.append(
                    dict(
                        machine=name, recent=f >= recent_from, metric=metric, diff=early._n.sum() / early._d.sum() - ref
                    )
                )
    pairs = pd.DataFrame(paired)
    pooled = {}
    if len(pairs):
        for metric in metrics:
            for scope, part in (
                ("全機種", pairs[pairs.metric == metric]),
                ("直近180日導入", pairs[(pairs.metric == metric) & pairs.recent]),
            ):
                if len(part) < 5:
                    pooled[f"{scope}|{metric}"] = {"n_machines": len(part), "note": "機種が5未満で区間を出さない"}
                    continue
                means = rng.choice(part["diff"].to_numpy(), (iters, len(part))).mean(1)
                pooled[f"{scope}|{metric}"] = {
                    "n_machines": len(part), "mean_diff": _round(part["diff"].mean(), 3),
                    "ci": [_round(np.percentile(means, 2.5), 3), _round(np.percentile(means, 97.5), 3)],
                }  # fmt: skip
    ledger.record(
        "N1", planned=planned, cells=cells, excluded=excluded, unit="機種×経過日0-6", metrics=",".join(metrics), window="導入日〜35日",
        scope="初出がDBの最初の日より後の機種×指標×経過日7", basis="ex_post", runner="theory_rescan.run_n1",
        caveats=["回転数の高さは根拠にしない", "DBの最初の日にある機種は導入日が不明なので対象外", "単日セルに検定はなく、機種をまたいだ平均だけ区間を出す"],
        extra={"pooled": pooled}, n_days=7, n_units=len(debuted),
    )  # fmt: skip


def run_density(ledger, df, specs):
    """高設定推定の絶対数(チェックリストのパス2)。一様な事前の値で、比較の目安。"""
    asof = ledger.asof
    wins = {"3m": (shift_ds(asof, -89), asof), **month_windows(asof, 4)}
    rows = df[
        (~df.is_new) & df.hit_kind.notna() & (df.G >= HIGH_MIN_GAMES) & (df.ds >= min(v[0] for v in wins.values()))
    ]
    post = []
    for r in rows.itertuples():
        spec = bs.find_spec(r.machine_name, specs)
        if r.hit_kind == "RB":
            p = bs.posterior(spec, r.G, r.bb, r.rb)
        else:
            p = bs.posterior(
                {
                    "settings": {
                        k: {"rb_probability": v.get("rb_probability"), "use_bb": False}
                        for k, v in spec["settings"].items()
                    }
                },
                r.G,
                0,
                r.hit,
            )
        post.append(sum(v for k, v in p.items() if k >= 5) if p else np.nan)
    rows = rows.assign(p_high=post)
    types = sorted(rows.type.unique())
    cells, excluded, planned = [], [], 0
    for window, (start, end) in wins.items():
        part = rows[(rows.ds >= start) & (rows.ds <= end)]
        days = part.ds.nunique()
        for t in types:
            planned += 1
            sub = part[part.type == t]
            if not len(sub):
                excluded.append(_ex("CHK2", "タイプ", t, "", "高設定推定", "一様な事前", window, "NO_ROWS"))
                continue
            high = sub.p_high >= HIGH_POSTERIOR
            cells.append(
                dict(
                    unit_kind="タイプ", unit=t, level="", metric="高設定推定", contrast="一様な事前", window=window, n_days=days,
                    n_units=int(sub.machine_number.nunique()), effect=high.sum() / days, family=f"CHK2|{window}",
                    note=f"判定台日={len(sub)},該当={int(high.sum())},割合={high.mean():.3f}",
                )
            )  # fmt: skip
    ledger.record(
        "CHK2", planned=planned, cells=cells, excluded=excluded, unit="タイプ", metrics="1日あたりの高設定推定台数", window="3m,月別4",
        scope=f"G>={HIGH_MIN_GAMES}の確認済み機種。事後確率(設定5以上)>={HIGH_POSTERIOR}", basis="ex_post", runner="theory_rescan.run_density",
        caveats=["一様な事前の値。絶対数は膨らむので、確率ではなく比較の目安として読む"], n_days=rows.ds.nunique(), n_units=rows.machine_number.nunique(),
    )  # fmt: skip


# ---------------------------------------------------------------- 既存モジュールのラップ
def _grid_anti(grid: pd.DataFrame, cells: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if not len(grid):
        return grid
    return grid.merge(cells[keys].drop_duplicates(), on=keys, how="left", indicator=True).query(
        "_merge == 'left_only'"
    )[keys]


def _wrapped_top(cells):
    if not len(cells):
        return []
    rows = cells[cells.effect.astype(float) > 0].sort_values("p").head(5)
    return [
        dict(label=r.unit, metric=r.metric, n_days=int(r.n_days), effect=_round(r.effect), ci=[None, None], q=_round(r.q), falsification="未実施", next_month="未検証")
        for r in rows.itertuples()
    ]  # fmt: skip


def run_wrapped(ledger, cfg, iters):
    hall, asof = cfg["hall"], ledger.asof
    start = shift_ds(asof, -89)
    specs = bs.load_specs(hall=hall)
    table = ax.build_day_table(hall, start, asof, specs=specs, require_layout=False)
    has_layout = table.section.notna().any()
    caveats = [
        "axis_scan は G=0 を読み込まない",
        "区分 seg は排他(RB側は機械割差なし、OTHER側はRBなし)",
        "基準は期間全体で in_sample",
        "新台は除外",
    ]
    if has_layout:
        positioned = table[table.section.notna()]
        F, C = ax.run_scan(positioned, iters=iters, hall=hall)
        days = sorted(positioned.ds.unique())
        grid_rows = []
        for axis_name, (names, _m, _s) in ax.time_axes(days, hall).items():
            for seg, outcome in (
                ("RB", "当りO/E"),
                ("RB", "回転数/期待"),
                ("OTHER", "機械割(差枚/3G)"),
                ("OTHER", "回転数/期待"),
            ):
                if (positioned.seg == seg).any():
                    for pos, levels in (("末尾", [f"末尾{k}" for k in range(10)]), ("角番", ["角1", "角2", "角3以上"])):
                        grid_rows += [
                            dict(axis=axis_name, pos=pos, seg=seg, outcome=outcome, time=n, level=x)
                            for n in names
                            for x in levels
                        ]
            for seg in ("RB", "OTHER"):
                if (positioned.seg == seg).any():
                    grid_rows += [
                        dict(axis=axis_name, pos="並び", seg=seg, outcome="隣接ペア残差積", time=n, level="隣接ペア")
                        for n in names
                    ]
        grid = pd.DataFrame(grid_rows)
        missing = _grid_anti(grid, C, ["axis", "pos", "seg", "outcome", "time", "level"])
        for axis_id, pos in (("P1", "末尾"), ("P2", "角番"), ("P3", "並び")):
            sel = C[C.pos == pos]
            miss = missing[missing.pos == pos]
            cells = sel.assign(
                unit_kind=sel.pos + "×" + sel.axis, unit=sel.time + "×" + sel.level, metric=sel.seg + ":" + sel.outcome, contrast="差の差",
                window="3m", n_days=sel.days, n_units=1, effect=sel.obs, family=sel.axis + "|" + sel.pos + "|" + sel.seg + "|" + sel.outcome,
                note="z=" + sel.z.round(2).astype(str),
            )  # fmt: skip
            exc = miss.assign(
                unit_kind=miss.pos + "×" + miss.axis, unit=miss.time + "×" + miss.level, metric=miss.seg + ":" + miss.outcome, contrast="差の差",
                window="3m", reason_code="NONFINITE",
            )  # fmt: skip
            ledger.record(
                axis_id, planned=int((grid.pos == pos).sum()), cells=cells, excluded=exc, unit=pos,
                metrics="当りO/E,機械割(差枚/3G),回転数/期待", window=f"{start}-{asof}", scope="位置×時間(曜日・D・DD・ゾロ目・イベント系列)。全組み合わせ(2軸)。3m のみ",
                basis="in_sample", runner="axis_scan.run_scan", top=_wrapped_top(cells), caveats=caveats, n_days=len(days),
                n_units=positioned.machine_number.nunique(), families=int((F.pos == pos).sum()),
            )  # fmt: skip
        ledger.record_composite(
            "X1",
            ["P1", "P2", "P3"],
            unit="末尾・角番・並び",
            metrics="当りO/E,機械割(差枚/3G),回転数/期待",
            window=f"{start}-{asof}",
            scope="P1・P2・P3 の和。BHは全セル共通",
            basis="in_sample",
            runner="axis_scan.run_scan",
            caveats=caveats,
        )
    else:
        for axis_id in ("P1", "P2", "P3", "X1"):
            ledger.not_run(
                axis_id,
                "データ不足",
                "machine_layout_history が空で、axis_scan の位置軸を回せない(水準の末尾は L5 で別に見る)",
            )
        ledger.not_run("P4", "データ不足", "machine_layout_history が空で島を定義できない")
    days = sorted(table.ds.unique())
    table = table.assign(
        diff=table.diff_coins_normalized, mtype=[ut.machine_type(n, c) for n, c in zip(table.machine_name, table.cat)]
    )
    ev = ut.event_dates(hall)
    labels = ut.time_labels(days, table.groupby("ds").G.sum(), set().union(*ev.values()) if ev else set())
    labels.pop("前日の稼働", None)  # 暦日でも as_of でもない。履歴は H1 で見る
    unit_parts = []
    for axis_id, col in [("M1", "machine_name"), ("M2", "mtype")] + ([("P4", "section")] if has_layout else []):
        F, C = ut.scan_units(table, col, labels, days, B=iters, min_unit_days=30)
        units = sorted(table[col].dropna().astype(str).unique())
        grid = pd.DataFrame(
            [
                dict(axis=a, level=x, outcome=o, unit=u)
                for a, levels in labels.items()
                for x in levels
                for o in ut.OUTCOMES
                for u in units
            ]
        )
        if not len(C):
            C = pd.DataFrame(columns=["axis", "level", "outcome", "unit", "days", "obs", "z", "p", "q"])
        miss = _grid_anti(grid, C, ["axis", "level", "outcome", "unit"])
        cells = C.assign(
            unit_kind=col + "×" + C.axis, unit=C.unit + "×" + C.level, metric=C.outcome, contrast="水準の中と外", window="3m", n_days=C.days,
            n_units=1, effect=C.obs, family=C.axis + "|" + C.level + "|" + C.outcome, note="z=" + C.z.astype(float).round(2).astype(str),
        )  # fmt: skip
        exc = miss.assign(
            unit_kind=col + "×" + miss.axis,
            unit=miss.unit + "×" + miss.level,
            metric=miss.outcome,
            contrast="水準の中と外",
            window="3m",
            reason_code="BELOW_MIN_DAYS",
        )
        ledger.record(
            axis_id, planned=len(grid), cells=cells, excluded=exc, unit=col, metrics=",".join(ut.OUTCOMES), window=f"{start}-{asof}",
            scope="単位×時間。「前日の稼働」は暦日でないので外した。3m のみ", basis="in_sample", runner="unit_time_scan.scan_units", top=_wrapped_top(cells),
            caveats=["seg は排他で、差枚は出さない", "基準は期間全体で in_sample", "新台は除外"], n_days=len(days), n_units=len(units), families=len(F),
        )  # fmt: skip
        unit_parts.append(axis_id)
    ledger.record_composite(
        "X2",
        unit_parts,
        unit="機種・タイプ・島",
        metrics=",".join(ut.OUTCOMES),
        window=f"{start}-{asof}",
        scope="M1・M2・P4 の和",
        basis="in_sample",
        runner="unit_time_scan.scan_units",
        caveats=["M1・M2・P4 の結果の和。BHは単位ごとに別"],
    )


# ---------------------------------------------------------------- 反証確認
def neighbors_for(axis_id: str, label: str, lookup: dict | None = None) -> list[str]:
    """事前に決めた比較条件。結果を見てから足さない。"""
    if axis_id == "L5":
        digit = int(label)
        return [str((digit - 1) % 10), str((digit + 1) % 10)]
    if axis_id == "T2":
        digit = int(label[0])
        return [f"{(digit - 1) % 10}のつく日", f"{(digit + 1) % 10}のつく日"]
    if axis_id == "T1":
        names = [c + "曜" for c in "月火水木金土日"]
        i = names.index(label)
        return [names[(i - 1) % 7], names[(i + 1) % 7]]
    if axis_id == "T3":
        day = int(label[:-1])
        return [f"{day - 1 if day > 1 else 31}日", f"{day + 1 if day < 31 else 1}日"]
    if axis_id == "L3":
        order = {
            "端1": ["端2"],
            "端2": ["端1", "端3以上"],
            "端3以上": ["端2"],
            "通路角1": ["通路角2"],
            "通路角2": ["通路角1", "通路角3以上"],
            "通路角3以上": ["通路角2"],
        }
        return order.get(label, [])
    if axis_id == "L4":
        return [str(int(label) - 1), str(int(label) + 1)]
    return (lookup or {}).get(label, [])


def peer_lookup(df, col):
    """同タイプで台数が近い2つ(機種・島の比較条件)。"""
    known = df[df[col].notna()]
    sizes = known.groupby(col).machine_number.nunique()
    kinds = known.groupby(col).type.agg(lambda s: s.mode().iat[0])
    out = {}
    for unit, size in sizes.items():
        same = sizes[(kinds == kinds[unit]) & (sizes.index != unit)]
        out[str(unit)] = [str(x) for x in (same - size).abs().sort_values().head(2).index]
    return out


def _daily(frame, days):
    di = {d: i for i, d in enumerate(days)}
    R, D = np.zeros(len(days)), np.zeros(len(days))
    if len(frame):
        ix = frame.ds.map(di).to_numpy()
        np.add.at(R, ix, frame._r.to_numpy(float))
        np.add.at(D, ix, frame._d.to_numpy(float))
    return R, D


def run_falsification(ledger, df, iters, rng, axes=("L1", "L2", "L3", "L4", "L5", "T1", "T2", "T3")):
    start = shift_ds(ledger.asof, -89)
    base = df[(~df.is_new) & (df.ds >= start)].assign(all_units="全台")
    days = sorted(base.ds.unique())
    cols = {"L1": "machine_name", "L2": "section", "L4": "machine_number", "L5": "ld"}
    lookups = {"L1": peer_lookup(base, "machine_name")}
    if base.section.notna().any():
        lookups["L2"] = peer_lookup(base, "section")
    t_levels = time_axis_levels(days, ledger.hall, None)
    cands = []
    for axis_id in axes:
        path = ledger.results / f"{axis_id}.json"
        if path.exists():
            cands += [(axis_id, item) for item in json.loads(path.read_text("utf-8"))["top"]]
    cells, excluded, status = [], [], {}
    for axis_id, item in cands:
        metric = item["metric"]
        label = item["label"] if axis_id[0] == "L" else item["level"]
        key = (axis_id, item["label"], metric, item.get("level"))
        neighbors = neighbors_for(axis_id, label, lookups.get(axis_id))
        if not neighbors:
            excluded.append(_ex("F1", axis_id, label, "", metric, "隣接", "3m", "NO_RULE"))
            status[key] = "該当なし"
            continue
        if axis_id[0] == "L":
            col = cols.get(axis_id) or ("aisle" if str(label).startswith("通路") else "edge")
            part = base[base[col].notna()]
            frame = (
                unit_level_residual(part, metric, col, [])
                if axis_id == "L1"
                else residual_rows(part, metric, ["ds", "machine_name"])
            )
            frame = frame.assign(_u=frame[col].astype(str))
            cand_r, cand_d = _daily(frame[frame._u == str(label)], days)
            near_r, near_d = _daily(frame[frame._u.isin(neighbors)], days)
            valid = (cand_d > 0) & (near_d > 0)
            if valid.sum() < 5:
                excluded.append(_ex("F1", axis_id, label, "", metric, "隣接", "3m", "FEW_DAYS"))
                status[key] = "未実施"
                continue
            R, D = np.stack([cand_r[valid], near_r[valid]], 1), np.stack([cand_d[valid], near_d[valid]], 1)
            W = block_weights(int(valid.sum()), iters, rng)
            with np.errstate(invalid="ignore", divide="ignore"):
                sims = (W @ R) / (W @ D)
            est = R.sum(0) / D.sum(0)
        else:
            col = "all_units" if item["label"] == "全台" else "type"
            units = sorted(base[col].unique())
            levels = t_levels[axis_id]
            if label not in levels or item["label"] not in units or not any(n in levels for n in neighbors):
                excluded.append(_ex("F1", axis_id, label, "", metric, "隣接", "3m", "NO_NEIGHBOR_DAYS"))
                status[key] = "未実施"
                continue
            NUM, DEN = time_matrices(base, metric, days, units, col)
            k = units.index(item["label"])
            cand = np.asarray(levels[label], bool)
            near = np.any([np.asarray(levels[n], bool) for n in neighbors if n in levels], axis=0)
            if cand.sum() < 2 or near.sum() < 2:
                excluded.append(_ex("F1", axis_id, label, "", metric, "隣接", "3m", "FEW_DAYS"))
                status[key] = "未実施"
                continue
            ci, ni = (
                rng.integers(0, cand.sum(), (iters, int(cand.sum()))),
                rng.integers(0, near.sum(), (iters, int(near.sum()))),
            )
            with np.errstate(invalid="ignore", divide="ignore"):
                sims = np.stack(
                    [
                        NUM[cand, k][ci].sum(1) / DEN[cand, k][ci].sum(1),
                        NUM[near, k][ni].sum(1) / DEN[near, k][ni].sum(1),
                    ],
                    1,
                )
            est = np.array([NUM[cand, k].sum() / DEN[cand, k].sum(), NUM[near, k].sum() / DEN[near, k].sum()])
        delta = sims[:, 0] - sims[:, 1]
        p = float(max(min(1.0, 2 * min(np.nanmean(delta <= 0), np.nanmean(delta >= 0))), 1 / iters))
        cells.append(
            dict(
                unit_kind=axis_id, unit=f"{item['label']}|{item.get('level', '')}", level="/".join(neighbors), metric=metric, contrast="候補−隣接",
                window="3m", n_days=item["n_days"], n_units=1, effect=est[0] - est[1], ci_lo=np.nanpercentile(delta, 2.5),
                ci_hi=np.nanpercentile(delta, 97.5), p=p, family="F1", note=f"候補={est[0]:.4f},隣接={est[1]:.4f}",
            )
        )  # fmt: skip
        status[key] = "済"
    cell_df = pd.DataFrame(cells)
    if len(cell_df):
        cell_df["q"] = ax.bh_adjust(cell_df.p.to_numpy(float))
    ledger.record(
        "F1", planned=len(cands), cells=cell_df, excluded=excluded, unit="各軸の上位候補", metrics="候補と同じ指標", window=f"{start}-{ledger.asof}",
        scope="比較条件は開始時に固定した規則のみ。追加なし", basis="in_sample", runner="theory_rescan.run_falsification",
        caveats=["同程度の結果が隣でも出るなら、候補固有ではなく軸全体の水準の可能性がある"], n_days=len(days), n_units=len(cands), families=1,
    )  # fmt: skip
    for axis_id in axes:
        path = ledger.results / f"{axis_id}.json"
        if path.exists():
            summary = json.loads(path.read_text("utf-8"))
            for item in summary["top"]:
                item["falsification"] = status.get(
                    (axis_id, item["label"], item["metric"], item.get("level")), item["falsification"]
                )
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=_js), "utf-8")


# ---------------------------------------------------------------- 文書の説
CLAIM_UNITS = {
    "payout": ("pp", 100.0),
    "rb_rate": ("回/1000G", 1000.0),
    "bonus_rate": ("回/1000G", 1000.0),
    "games": ("G", 1.0),
    "diff": ("枚", 1.0),
}
MIN_RECENT_TARGET = 3
MIN_FIRM_RECENT = (
    6  # 直近がこれ未満の日数なら、区間の向きを問わず判定しない(日のブートストラップは小標本で区間が狭く出る)
)


def verdict_from(status: str, recent_ci, recent: float, base: float) -> str:
    """deathwatch の判定を、文書の区分へ写す。非有意を「消えた」にしない。"""
    excl = recent_ci[0] * recent_ci[1] > 0
    if status in ("DEAD", "REVERSED"):
        return "消えた"
    if status == "NO_BASELINE":
        if not excl:
            return "判別不能(過去も検出なし)"
        return "直近のみ検出(正)" if recent > 0 else "直近のみ検出(負)"
    if excl and np.sign(recent) == np.sign(base):
        return "残っている"
    return "判別不能"


def claim_frame(hall: str) -> pd.DataFrame:
    df = load_frame(hall)
    df["diff"] = df["diff_coins_normalized"]
    df["games"] = df["games_normalized"]
    df["dd"] = df["date"].str[6:8].astype(int)
    df["ddd"] = df["dd"] % 10
    df["strong_zorome"] = (df["date"].str[4:6].astype(int) == df["dd"]).astype(int)
    df["weekday"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.weekday
    df["ld"] = df["machine_number"].astype(int) % 10
    df["edge"] = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    df["unit_no"] = df["machine_number"].astype(int)
    df["unit_zorome"] = (df["unit_no"] % 100 % 11 == 0).astype(int)
    return df


def _day_mask(df, days):
    mask = pd.Series(True, index=df.index)
    for field, values in (days or {}).items():
        mask &= df[field].isin(values if isinstance(values, list) else [values])
    return mask


def _claim_row(row, base, recent, b_boot, r_boot, scale, n_base, n_recent):
    b_ci, r_ci, d_ci = dw._ci(b_boot), dw._ci(r_boot), dw._ci(r_boot - b_boot)
    status = dw.classify(base, b_ci, recent, r_ci, d_ci)
    verdict = verdict_from(status, r_ci, recent, base)
    if n_recent < MIN_FIRM_RECENT:
        verdict = "判別不能(小標本)"
    return {
        **row, "status": status, "verdict": verdict, "n_baseline": n_base, "n_recent": n_recent,
        "baseline": round(base * scale, 3), "baseline_ci_lo": round(b_ci[0] * scale, 3), "baseline_ci_hi": round(b_ci[1] * scale, 3),
        "recent": round(recent * scale, 3), "recent_ci_lo": round(r_ci[0] * scale, 3), "recent_ci_hi": round(r_ci[1] * scale, 3),
        "delta": round((recent - base) * scale, 3), "delta_ci_lo": round(d_ci[0] * scale, 3), "delta_ci_hi": round(d_ci[1] * scale, 3),
    }  # fmt: skip


def _weighted_level(part: pd.DataFrame) -> pd.Series:
    """日ごとの機械割差(回転数で加重、機種の期間平均との差)。非加重は少回転の台日の外れ値に振られる。"""
    live = part[part["games"] > 0]
    games = live.groupby("machine_name")["games"].transform("sum")
    rate = live.groupby("machine_name")["diff"].transform("sum") / (3.0 * games)
    resid = live["diff"] - 3.0 * live["games"] * rate
    return resid.groupby(live["date"]).sum() / (3.0 * live["games"]).groupby(live["date"]).sum()


def _weighted_rate(part: pd.DataFrame) -> pd.Series:
    live = part[part["games"] > 0]
    return live.groupby("date")["diff"].sum() / (3.0 * live["games"]).groupby(live["date"]).sum()


def _in_universe(df, claim):
    part = df
    if claim.get("machine_like"):
        part = part[part["machine_name"].str.contains("|".join(claim["machine_like"]), regex=True)]
    if claim.get("universe"):
        part = apply_eligibility(part, claim["universe"])
    return part


def evaluate_claim(df: pd.DataFrame, claim: dict, recent_days: int, iters: int) -> list[dict]:
    """1つの説を、指標ごとに baseline と直近で比べる。比較の統計量は deathwatch と同じ。"""
    src = df[df["date"] >= claim["date_min"]] if claim.get("date_min") else df
    part = _in_universe(src, claim)
    contrast = claim["contrast"]
    asof = df["date"].max()
    cut = claim.get("recent_from") or shift_ds(asof, -recent_days + 1)  # recent_from はレジーム境界で区切る説のため
    base_min = claim.get("baseline_from")
    rows = []
    for metric in claim["metrics"]:
        unit, scale = CLAIM_UNITS[metric]
        row = dict(claim_id=claim["claim_id"], metric=metric, unit=unit, recent_from=cut, recent_to=asof)
        if part.empty:
            rows.append({**row, "status": "NO_ROWS", "verdict": "未検証(行なし)", "n_baseline": 0, "n_recent": 0})
            continue
        if contrast == "cross_day":
            lv = _weighted_level(part) if metric == "payout" else dw.daily_level(part, metric)
            mask = (
                _day_mask(part.drop_duplicates("date").set_index("date"), claim["days"])
                .reindex(lv.index)
                .fillna(False)
                .astype(bool)
            )
            old, new = lv.index < cut, lv.index >= cut
            if base_min:
                old = old & (lv.index >= base_min)
            b_t, b_o, r_t, r_o = lv[old & mask], lv[old & ~mask], lv[new & mask], lv[new & ~mask]
            if len(r_t) < MIN_RECENT_TARGET or len(b_t) < MIN_RECENT_TARGET or len(r_o) < 10 or len(b_o) < 10:
                rows.append(
                    {
                        **row,
                        "status": "INSUFFICIENT",
                        "verdict": "判別不能(日数不足)",
                        "n_baseline": len(b_t),
                        "n_recent": len(r_t),
                    }
                )
                continue

            def boot(t, o, seed):
                return block_bootstrap_means(t.to_numpy(), n_boot=iters, seed=seed, block=1) - block_bootstrap_means(
                    o.to_numpy(), n_boot=iters, seed=seed + 1, block=BLOCK
                )

            rows.append(
                _claim_row(
                    row,
                    float(b_t.mean() - b_o.mean()),
                    float(r_t.mean() - r_o.mean()),
                    boot(b_t, b_o, 20261106),
                    boot(r_t, r_o, 20261108),
                    scale,
                    len(b_t),
                    len(r_t),
                )
            )
            continue
        if contrast == "same_day":
            sub = part[_day_mask(part, claim.get("days"))].dropna(subset=dw.target_columns(claim["target"]))
            s = dw.daily_effect(sub, metric, dw.target_mask(sub, claim["target"]))
        elif contrast == "hall_level":
            all_days = src[_day_mask(src, claim.get("days"))]
            inside = _in_universe(all_days, claim)
            if claim.get("target"):
                inside = inside[dw.target_mask(inside, claim["target"])]
            others = all_days.drop(index=inside.index)
            if metric == "payout":
                s = (_weighted_rate(inside) - _weighted_rate(others)).dropna().sort_index()
            else:
                s = (
                    (inside.groupby("date")[metric].mean() - others.groupby("date")[metric].mean())
                    .dropna()
                    .sort_index()
                )
        else:
            raise ValueError(contrast)
        base_s, rec_s = s[s.index < cut], s[s.index >= cut]
        if base_min:
            base_s = base_s[base_s.index >= base_min]
        restricted = bool(claim.get("days"))
        if len(base_s) < (10 if restricted else 30) or len(rec_s) < (5 if restricted else 30):
            rows.append(
                {
                    **row,
                    "status": "INSUFFICIENT",
                    "verdict": "判別不能(日数不足)",
                    "n_baseline": len(base_s),
                    "n_recent": len(rec_s),
                }
            )
            continue
        block = 1 if restricted else BLOCK
        b_boot = block_bootstrap_means(base_s.to_numpy(), n_boot=iters, seed=20261106, block=block)
        r_boot = block_bootstrap_means(rec_s.to_numpy(), n_boot=iters, seed=20261107, block=block)
        rows.append(
            _claim_row(row, float(base_s.mean()), float(rec_s.mean()), b_boot, r_boot, scale, len(base_s), len(rec_s))
        )
    return rows


def load_claims(key: str) -> dict:
    path = CLAIMS_DIR / f"{key}.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {"claims": [], "untested": []}


def run_claims(ledger, key, iters):
    book = load_claims(key)
    claims = book["claims"]
    if not claims:
        ledger.not_run("CLAIM", "未実施", f"backtest/theory_claims/{key}.json に説が未登録")
        return
    df = claim_frame(ledger.hall)
    rows = []
    for claim in claims:
        for r in evaluate_claim(df, claim, 90, iters):
            detail = {
                k: r.get(k)
                for k in ("baseline", "baseline_ci_lo", "baseline_ci_hi", "delta", "delta_ci_lo", "delta_ci_hi", "unit")
            }
            rows.append(
                dict(
                    unit_kind=claim["contrast"], unit=claim["claim_id"], level=claim["text"], metric=r["metric"],
                    contrast=f"{r.get('status')}|{r.get('verdict')}", window=f"{r['recent_from']}-{r['recent_to']}", n_days=r["n_recent"],
                    n_units=r["n_baseline"], effect=r.get("recent"), ci_lo=r.get("recent_ci_lo"), ci_hi=r.get("recent_ci_hi"),
                    family=claim.get("source", ""), note=json.dumps(detail, ensure_ascii=False),
                )
            )  # fmt: skip
    ledger.record(
        "CLAIM", planned=sum(len(c["metrics"]) for c in claims), cells=rows, excluded=[], unit="文書の説", metrics="payout,rb_rate,bonus_rate,games,diff",
        window="直近90日とそれ以前", scope=f"説{len(claims)}件×指標。説の定義は backtest/theory_claims/{key}.json。n_days=直近の日数、n_units=比較期間の日数", basis="in_sample",
        runner="theory_rescan.run_claims(deathwatch の統計量)", caveats=[
            "判定は差の有意性に基づく。CIがゼロを跨ぐだけでは「消えた」にしない", f"直近が{MIN_FIRM_RECENT}日未満は判定しない",
            "payout は same_day が非加重(deathwatch と同じ)、cross_day と hall_level が回転数加重。旧本文の非加重の数値とは直接比べない",
        ],
        extra={"untested": book.get("untested", [])}, n_days=90, n_units=len(claims),
    )  # fmt: skip


# ---------------------------------------------------------------- 文書への書き出し
DOC_START = "<!-- RESCAN:START -->"
DOC_END = "<!-- RESCAN:END -->"
OLD_BODY_HEADING = "## 旧本文(未再検証)"
VERDICT_ORDER = (
    "残っている", "直近のみ検出(正)", "直近のみ検出(負)", "消えた", "判別不能", "判別不能(小標本)", "判別不能(過去も検出なし)", "判別不能(日数不足)", "未検証(行なし)",
)  # fmt: skip


def _claim_table(cells: pd.DataFrame) -> list[str]:
    """説ごとに、先頭の指標の判定で区分して表にする。残りの指標も同じ行に載せる。"""
    groups: dict[str, list[str]] = {}
    for claim_id, part in cells.groupby("unit", sort=False):
        verdict = str(part.iloc[0].contrast).split("|", 1)[1]
        parts = []
        for r in part.itertuples():
            detail = json.loads(r.note)
            status, judged = str(r.contrast).split("|", 1)
            if pd.isna(r.effect):
                parts.append(f"{r.metric}: {judged}(直近{r.n_days}日・比較{r.n_units}日)")
            else:
                parts.append(
                    f"{r.metric}: {detail['baseline']:+.3f} → **{r.effect:+.3f}** [{r.ci_lo:+.3f}, {r.ci_hi:+.3f}] {detail['unit']}"
                    f"(直近{r.n_days}日・比較{r.n_units}日、{judged}/{status})"
                )
        groups.setdefault(verdict, []).append(f"| `{claim_id}` {part.iloc[0].level} | {'<br>'.join(parts)} |")
    lines = []
    for verdict in VERDICT_ORDER:
        if verdict in groups:
            lines += [f"**{verdict}**", "", "| 説 | 比較期間 → 直近 [95%CI] |", "|---|---|", *groups[verdict], ""]
    return lines


def _top_lines(ledger: Ledger, axis_ids) -> list[str]:
    """q<0.2 で回転数以外の候補だけ載せる。回転数は客の集中を拾うので根拠に数えない。"""
    lines = [
        "| 軸 | 候補 | 指標 | 効果 | 95%CI | q | 日数 | 反証(隣接) | 翌月 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    count = 0
    for axis_id in axis_ids:
        path = ledger.results / f"{axis_id}.json"
        if not path.exists():
            continue
        for t in json.loads(path.read_text("utf-8"))["top"]:
            if t["metric"] in ("回転数", "RB:回転数/期待", "OTHER:回転数/期待") or t.get("q") is None or t["q"] >= 0.2:
                continue
            ci = t.get("ci") or [None, None]
            ci_text = f"[{ci[0]:+.3f}, {ci[1]:+.3f}]" if ci[0] is not None else "—"
            level = t.get("level") or ""
            label = f"{t['label']}×{level}" if level and level != t["label"] else t["label"]
            label = f"{label}({t['contrast']})" if t.get("contrast") else label
            month = t["next_month"] if "verify_effect" not in t else f"{t['next_month']}({t['verify_effect']:+.3f})"
            lines.append(
                f"| {axis_id} | {label} | {t['metric']} | {t['effect']:+.3f} | {ci_text} | {t['q']:.3f} | {t['n_days']} | {t['falsification']} | {month} |"
            )
            count += 1
    return lines if count else ["q<0.2 の候補(回転数を除く)はなかった。"]


def _axis_overview(ledger: Ledger) -> list[str]:
    lines = ["| 軸 | セル | p<0.05(偶然の期待) | BH q<0.2 | 検出力 |", "|---|---|---|---|---|"]
    for axis_id, row in ledger.rows.items():
        path = ledger.results / f"{axis_id}.json"
        if row["status"] != "完了" or not path.exists() or axis_id in ("CLAIM", "S1", "N1", "CHK2"):
            continue
        s = json.loads(path.read_text("utf-8"))
        if "composite_of" in s:
            continue
        lines.append(
            f"| {axis_id} {row['axis']} | {s['cells']} | {s['p05']}({s['p05_expected']}) | {s['bh_q02']} | {(s.get('power') or '—').replace('|', '/')} |"
        )
    return lines


def render_section(key: str, ledger: Ledger, *, reviewed: str) -> str:
    """結論の節。数値はすべて結果ファイルから引く。文章は theory_claims の conclusions を載せる。"""
    book = load_claims(key)
    header = json.loads((ledger.dir / "HEADER.json").read_text("utf-8"))
    rel = f"output/axis_scan/{ledger.hall}__{ledger.asof}/"
    w3 = header["windows"]["3m"]
    out = [
        DOC_START,
        f"## 直近3か月の結論({reviewed} 再検証、データは {ledger.asof} まで)",
        "",
        f"**期間**: 直近3か月 {w3[0]}〜{w3[1]}。比較は「それ以前」。台帳と結果: `{rel}`(`LEDGER.csv`・`results/`)。",
        f"**基準の注意**: 差は事後の比較で、`basis` が as_of の軸(H1〜H6)だけが開店前に使える形。レジーム境界は {header.get('regime') or '未確定'}({header.get('regime_note')})。",
        "",
    ]
    if book.get("conclusions"):
        out += ["### 結論", "", *[f"- {c}" for c in book["conclusions"]], ""]
    path = ledger.results / "CLAIM.cells.csv"
    if path.exists():
        cells = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
        out += [
            "### 文書の説の再判定",
            "",
            "「消えた」は直近が過去から有意に変わり、かつ直近の区間がゼロを跨ぐか逆符号のときだけ。区間がゼロを跨ぐだけのものは判別不能(watching)で、効果なしとは書かない。",
            "",
            *_claim_table(cells),
        ]
    if book.get("untested"):
        out += [
            "**未検証(今回は測っていない)**",
            "",
            "| 説 | 理由 |",
            "|---|---|",
            *[f"| {u['text']} | {u['reason']} |" for u in book["untested"]],
            "",
        ]
    out += [
        "### 軸スキャンの上位候補(事後の探索。候補であって確定ではない)", "",
        "水準(L)は同じ日の中の差で事後分析、時間軸(T)は in_sample、履歴(H)は as_of。翌月は train(直近30日より前の90日)で選んだ単位の verify(直近30日)の値。同機種の全台が1つの島にある島は、機種と島を分けられないので機種内比較から除く。", "",
        *_top_lines(ledger, ("L1", "L2", "L3", "L4", "L5", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "H1", "H2", "H3", "H4", "H5", "H6", "P1", "P2", "P3", "M1", "M2", "P4", "V1")), "",
        "### 軸ごとの件数と検出力", "", *_axis_overview(ledger), "",
    ]  # fmt: skip
    extras = []
    for axis_id, title in (("S1", "全体型/集中型"), ("N1", "新台")):
        file = ledger.results / f"{axis_id}.json"
        if file.exists():
            extras.append(
                f"- {title}: `{json.dumps(json.loads(file.read_text('utf-8')).get('extra', {}).get('3m') if axis_id == 'S1' else json.loads(file.read_text('utf-8')).get('extra', {}).get('pooled'), ensure_ascii=False)}`"
            )
    file = ledger.results / "CHK2.cells.csv"
    if file.exists():
        chk = pd.read_csv(file, encoding="utf-8-sig")
        chk = chk[chk.window == "3m"]
        extras.append(
            "- 高設定推定の台数/日(一様な事前の値、比較の目安): "
            + "、".join(f"{r.unit} {r.effect:.2f}台({r.note})" for r in chk.itertuples())
        )
    if extras:
        out += ["### 全体型・新台・絶対数", "", *extras, ""]
    if book.get("candidates"):
        out += [
            "### 前向き検証への登録候補(この再検証では登録していない)",
            "",
            *[f"- {c}" for c in book["candidates"]],
            "",
        ]
    rows = ledger.rows
    counts = pd.Series([r["status"] for r in rows.values()]).value_counts().to_dict()
    out += [
        "### 台帳の状態",
        "",
        f"状態の件数: {counts}。照合: {'合格' if reconcile(ledger)['ok'] else '未了'}。",
        "",
        "| 軸 | 状態 | 理由 |",
        "|---|---|---|",
    ]
    out += [f"| {k} {r['axis']} | {r['status']} | {r['reason']} |" for k, r in rows.items() if r["status"] != "完了"]
    out += ["", DOC_END, ""]
    return "\n".join(out)


def update_doc(text: str, section: str, note: str) -> str:
    """結論の節を差し替える。古い本文は消さず、旧本文の見出しの下に残す。"""
    title, _, rest = text.partition("\n")
    if DOC_START in rest:
        head, _, tail = rest.partition(DOC_START)
        _, _, tail = tail.partition(DOC_END)
        return f"{title}\n\n{note}\n\n{section}\n{tail.lstrip()}"
    body = rest.lstrip("\n")
    lines = body.splitlines()
    while lines and (
        lines[0].startswith("> **2026-11-06 棚卸し")
        or lines[0].startswith("> 角番")
        or lines[0].startswith("> - `")
        or lines[0].startswith("> `")
        or lines[0].startswith("> 死亡")
        or lines[0].startswith("> 9月以降")
        or lines[0].strip() == ""
    ):
        lines.pop(0)
    old = "\n".join(lines)
    return f"{title}\n\n{note}\n\n{section}\n---\n\n{OLD_BODY_HEADING}\n\n以下は再検証の前の記述で、期間・数値は当時のもの。根拠にする前に上の節と台帳で確かめる。\n\n{old}\n"


def write_doc(key: str, doc_path: Path, *, reviewed: str = "2026-11-06") -> None:
    cfg = HALLS[key]
    table_asof = sorted(p.name.split("__")[1] for p in OUT_ROOT.glob(f"{cfg['hall']}__*"))[-1]
    ledger = Ledger(cfg["hall"], table_asof)
    note = (
        f"> **{reviewed} 再検証済み**: 先頭の節が直近3か月の結論(データは {table_asof} まで、`backtest.theory_rescan`)。"
        f"後ろの「旧本文」は未再検証で、前の時点の記録として残している。"
    )
    text = Path(doc_path).read_text("utf-8")
    Path(doc_path).write_text(update_doc(text, render_section(key, ledger, reviewed=reviewed), note), "utf-8")


# ---------------------------------------------------------------- 実行
def fixed_not_run(ledger):
    ledger.not_run("T11", "データ不足", "ホール固有の日付の登録がない。文書にある特定DDは T3 と説の再判定で見る")
    ledger.not_run("T12", "未実施", "近隣ホールのイベント・天気のデータがこのDBにない(手段なし)")
    ledger.not_run("P4:座標", "未実施", "壁側・通路側の定義がDB列から確定できない(手段なし)。島は P4 で見る")
    ledger.not_run(
        "X3", "未実施", "末尾×D は P1 に含む。末尾×機種・角番×機種は1セルが数台で、総当たりは検出力が足りない"
    )
    ledger.not_run("X4", "未実施", "事前仮説のない3軸以上は対象外(検出力)。文書にある交互作用は CLAIM で見る")


def run(key: str, iters: int = 2000, only: set[str] | None = None, seed: int = 20261106) -> dict:
    cfg = HALLS[key]
    hall = cfg["hall"]
    rng = np.random.default_rng(seed)
    specs = bs.load_specs(hall=hall)
    df, checks, db_min = prepare(load_table(hall), specs, hall)
    ledger = Ledger(hall, df.ds.max())
    header = build_header(df, checks, cfg, ledger.asof)
    (ledger.dir / "HEADER.json").write_text(json.dumps(header, ensure_ascii=False, indent=1, default=_js), "utf-8")
    checks.to_csv(ledger.dir / "metric_checks.csv", index=False, encoding="utf-8-sig")
    metrics = (
        ["機械割差", "差枚", "回転数"]
        + (["RB位置"] if header["rb_usable"] else [])
        + (["AT位置"] if header["at_usable"] else [])
    )

    def want(name):
        return only is None or name in only

    fixed_not_run(ledger)
    if want("L"):
        run_levels(ledger, df, metrics, iters // 2, rng)
    if want("S"):
        run_s1(ledger, df, cfg)
    if want("V"):
        run_v1(ledger, df, cfg, min(iters, 500), rng)
    if want("N"):
        run_n1(ledger, df, metrics, db_min, iters // 2, rng)
    if want("D"):
        run_density(ledger, df, specs)
    if want("T"):
        run_time_axes(ledger, df, metrics, cfg, iters, rng)
    if want("H"):
        run_history(ledger, df, metrics, iters, rng)
    if want("X"):
        run_wrapped(ledger, cfg, iters // 2)
    if want("F"):
        run_falsification(ledger, df, iters // 2, rng)
    if want("CLAIM"):
        run_claims(ledger, key, iters)
    return {"dir": str(ledger.dir), "reconcile": reconcile(ledger)}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="全軸スキャンと文書の説の再判定")
    parser.add_argument("--key", required=True, choices=sorted(HALLS))
    parser.add_argument("--iters", type=int, default=2000)
    parser.add_argument("--only", help="L,S,V,N,D,T,H,X,F,CLAIM のカンマ区切り")
    parser.add_argument("--write-doc", help="結論の節を書き込む theory 文書のパス。スキャンはせず、既存の結果から書く")
    args = parser.parse_args(argv)
    if args.write_doc:
        write_doc(args.key, Path(args.write_doc))
        return 0
    result = run(args.key, args.iters, set(args.only.split(",")) if args.only else None)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["reconcile"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
