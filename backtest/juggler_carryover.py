"""ジャグラー設定の持ち越し分析(読み取り専用)。

前日(と過去数日)の結果から、翌日に高設定(設定5以上)である確率がどれだけ上がるかを台単位で測る。
翌日の高設定確率は、BB・RBの二項尤度とスペックから1日ごとに求めた設定5以上の事後確率(事前は機種別に独立EMで推定)。

使い方:
  python -m backtest.juggler_carryover groups   [--hall みとや大森町店] [--since 20260601]
  python -m backtest.juggler_carryover tomorrow [--hall みとや大森町店]   # 最新の収集スナップショットから翌日の候補
  python -m backtest.juggler_carryover check    --date 20261012           # 前日までの履歴で作った候補の答え合わせ
  python -m backtest.juggler_carryover splithalf [--cut 20260801]          # 前半・後半で台別の偏りと持ち越しが再現するか
  python -m backtest.juggler_carryover position  [--cut 20260801]          # 島の端が低いか、位置を除いても台固定が残るか
  python -m backtest.juggler_carryover oos       [--model マイジャグラーV]  # 候補に島の端を反映する案の比較(アウトオブサンプル)

考え方・検証結果・限界は document/JUGGLER_SETTING_PATTERNS.md を読むこと。
"""

import argparse
import csv
import glob
import json
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import bonus_specs
from backtest.bonus_specs import find_spec, load_specs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HALL = "みとや大森町店"
MIN_GAMES = 1500  # 事後確率を出す最低G数
MIN_N = 30  # 群の最低台日数


HALL_CONFIG = ROOT / "config" / "juggler_analysis.json"


def load_hall_config(hall, path=None):
    """ホール別の例外(除外日exclusions・変化点regime_boundaries)。無ければ空。イベント日・配置は別の台帳を参照する。"""
    p = Path(path) if path else HALL_CONFIG
    if not p.exists():
        return {"exclusions": [], "regime_boundaries": [], "event_days": None}
    cfg = json.loads(p.read_text(encoding="utf-8")).get("halls", {}).get(hall, {})
    return {
        "exclusions": cfg.get("exclusions", []),
        "regime_boundaries": cfg.get("regime_boundaries", []),
        "event_days": _normalize_event_days(cfg.get("event_days")),
    }


def _normalize_event_days(ev):
    """event_days を {"default": 名前, "definitions": {名前: 規則}} の形にそろえる。
    旧い平坦な形(規則がそのまま入っている)は、名前 "default" の1定義として扱う。無ければ None。"""
    if not ev:
        return None
    if "definitions" in ev:
        defs = ev["definitions"]
        return {"default": ev.get("default") or next(iter(defs)), "definitions": defs}
    return {"default": "default", "definitions": {"default": ev}}


def pick_event_rule(event_days, name=None):
    """名前で定義を選ぶ(省略時は default)。無い名前なら選べる名前を挙げて停止する。(名前, 規則) を返す。event_days が無ければ (None, None)。"""
    if not event_days:
        return None, None
    name = name or event_days["default"]
    if name not in event_days["definitions"]:
        raise SystemExit(f"イベント日の定義 '{name}' は無い。選べるのは: {', '.join(event_days['definitions'])}")
    return name, event_days["definitions"][name]


def is_event_day(ts, rule):
    """ホール設定のイベント日の定義(rule)に、その日(Timestamp)が当てはまるか。
    rule のキー: dd(日の集合)、dd_last_digit(日の末尾の集合)、zorome(11・22日)、strong_zorome(月=日)、month_end(月末)。"""
    day = ts.day
    if day in set(rule.get("dd", [])):
        return True
    if day % 10 in set(rule.get("dd_last_digit", [])):
        return True
    if rule.get("zorome") and day in (11, 22):
        return True
    if rule.get("strong_zorome") and ts.month == day:
        return True
    return bool(rule.get("month_end") and (ts + pd.Timedelta(days=1)).month != ts.month)


DAY_TYPES = ("all", "normal", "event")


def _by_day_type(frame, col, day_type):
    """day_type(all/normal/event)で行を絞る。col はイベント日フラグの列。定義が未登録のホールで normal/event を指定したら停止する。"""
    if day_type == "all":
        return frame
    if frame[col].isna().all():
        raise SystemExit("このホールはイベント日の定義が未登録(config/juggler_analysis.json の event_days に追加する)")
    return frame[frame[col].astype(bool) == (day_type == "event")]


def _db(hall, db_dir=None):
    return (Path(db_dir) if db_dir else ROOT / "db") / f"{hall}.db"


def _layout_history(hall, db_dir=None):
    """日付つきの配置。過去の分析には現行配置(machine_layout)でなくこちらを使う(配置替えをまたぐと島が誤る)。"""
    con = sqlite3.connect(_db(hall, db_dir))
    try:
        return pd.read_sql(
            "select machine_number u, section, rank_from_min rmin, rank_from_max rmax, rank_from_aisle raisle,"
            " valid_from, valid_to from machine_layout_history",
            con,
        )
    except pd.errors.DatabaseError:
        try:  # rank列の無いDB(合成テスト等)
            return pd.read_sql(
                "select machine_number u, section, valid_from, valid_to from machine_layout_history", con
            )
        except pd.errors.DatabaseError:
            return pd.DataFrame(columns=["u", "section", "valid_from", "valid_to"])


def attach_section(raw, hist):
    """各台日に、その日に有効な配置(valid_from <= date <= valid_to)の section と、島の端からの順位
    (rmin/rmax/raisle。あれば)を付ける。無ければNaN。dist = min(rmin, rmax) で 1 が島の端。"""
    raw = raw.reset_index(drop=True)
    cols = [c for c in ("section", "rmin", "rmax", "raisle") if c in hist.columns]
    if hist.empty:
        for c in ("section", "rmin", "rmax", "raisle"):
            raw[c] = np.nan
        raw["dist"] = np.nan
        return raw
    m = raw.assign(_i=raw.index).merge(hist, on="u", how="left")
    valid = (m.date >= m.valid_from) & (m.valid_to.isna() | (m.date <= m.valid_to))
    got = m[valid].drop_duplicates("_i").set_index("_i")
    for c in ("section", "rmin", "rmax", "raisle"):
        raw[c] = got[c].reindex(raw.index) if c in cols else np.nan
    raw["dist"] = raw[["rmin", "rmax"]].min(axis=1)
    return raw


def _master_settings(model):
    """machine_master.csv(公表値)の設定別BB・RB確率。見つからなければ空。"""
    out = {}
    with open(bonus_specs.MASTER_CSV, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("canonical_machine_name") != model and row.get("machine_name") != model:
                continue
            for s in range(1, 7):
                bb = re.match(r"1/([\d.]+)", row.get(f"bb_setting{s}") or "")
                rb = re.match(r"1/([\d.]+)", row.get(f"rb_setting{s}") or "")
                if bb and rb:
                    out[s] = {"bb_probability": 1 / float(bb.group(1)), "rb_probability": 1 / float(rb.group(1))}
            break
    return out


SPEC_TOLERANCE = 0.005  # find_specとマスターCSVの確率(分母)の相対差。2026-10-13のスペック誤りの再発防止


def audit_specs(models, specs):
    """機種ごとにスペックを照合する。(不一致のリスト, 対象外のリスト)を返す。
    不一致: find_specとマスターCSVの設定別BB・RBが許容差を超えて食い違う。対象外: スペックが無い/設定が4未満。"""
    mismatches, unsupported = [], []
    for m in models:
        spec = find_spec(m, specs)
        if not spec:
            unsupported.append((m, "スペックなし"))
            continue
        used = {s: v for s, v in spec["settings"].items() if v.get("bb_probability") and v.get("rb_probability")}
        if len(used) < 4:
            unsupported.append((m, f"設定別BB・RBが{len(used)}設定しか無い"))
            continue
        for s, mv in _master_settings(m).items():
            v = used.get(s)
            if not v:
                continue
            for key in ("bb_probability", "rb_probability"):
                if abs(v[key] / mv[key] - 1) > SPEC_TOLERANCE:
                    mismatches.append((m, s, key, 1 / v[key], 1 / mv[key]))
    return mismatches, unsupported


def _load_raw(hall, since, db_dir=None):
    con = sqlite3.connect(_db(hall, db_dir))
    df = pd.read_sql(
        "select date,machine_number u,machine_name m,games_normalized g,bb_count bb,rb_count rb,"
        "diff_coins_normalized diff from machine_detailed_results "
        "where date>=? and machine_name like '%ジャグラー%'",
        con,
        params=(since,),
    )
    df["d"] = pd.to_datetime(df["date"])
    return df[df.bb.notna() & df.rb.notna()].copy()


def _latest_snapshot(hall):
    files = sorted(glob.glob(str(ROOT / "scraper" / "realtime" / "output" / "snapshots" / f"{hall}_quick_*.jsonl")))
    if not files:
        raise SystemExit("収集スナップショットが無い")
    f = files[-1]
    rows = [json.loads(line) for line in open(f, encoding="utf-8")]
    out = pd.DataFrame(
        [
            {"u": r["unit"], "m": r["model"], "g": r["games"], "bb": r["bb"], "rb": r["rb"], "diff": r.get("diff")}
            for r in rows
            if r.get("model") and "ジャグラー" in r["model"] and r.get("games") and r.get("bb") is not None
        ]
    )
    stamp = Path(f).stem.split("_")[-2]
    out["date"] = stamp
    out["d"] = pd.to_datetime(stamp)
    out["diff"] = out["diff"].astype(float)
    return out, Path(f).name


def _posteriors(df, specs, excluded=None):
    """台×日の設定5以上の事後確率と、前日の型を判定する閾値。
    推定の対象外にした機種は excluded(dict: 機種 -> (台日数, 理由))に記録する。黙って飛ばさない。"""
    excluded = {} if excluded is None else excluded
    parts = []
    for m, sub in df.groupby("m"):
        spec = find_spec(m, specs)
        if not spec:
            excluded[m] = (len(sub), "スペックなし")
            continue
        ss = sorted(s for s, v in spec["settings"].items() if v.get("bb_probability") and v.get("rb_probability"))
        if len(ss) < 4:
            excluded[m] = (len(sub), f"設定別BB・RBが{len(ss)}設定しか無い")
            continue
        use = sub[sub.g >= MIN_GAMES]
        if use.u.nunique() < 3:
            excluded[m] = (len(sub), f"G{MIN_GAMES}以上の台が3台未満")
            continue
        g = use.g.values[:, None].astype(float)
        bb = use.bb.values[:, None]
        rb = use.rb.values[:, None]
        pb = np.array([spec["settings"][s]["bb_probability"] for s in ss])[None, :]
        pr = np.array([spec["settings"][s]["rb_probability"] for s in ss])[None, :]
        ll = bb * np.log(pb) + (g - bb) * np.log1p(-pb) + rb * np.log(pr) + (g - rb) * np.log1p(-pr)
        e = np.exp(ll - ll.max(axis=1, keepdims=True))
        prior = np.ones(len(ss)) / len(ss)
        for _ in range(60):
            w = e * prior
            w /= w.sum(axis=1, keepdims=True)
            prior = w.mean(axis=0)
        post = e * prior
        post /= post.sum(axis=1, keepdims=True)
        hi = np.array([s >= 5 for s in ss])
        s5 = [s for s in ss if s >= 5][0]
        s2 = [s for s in ss if s <= 2][-1]
        out = use.copy()
        out["ph"] = post[:, hi].sum(axis=1)
        out["rb5"] = spec["settings"][s5]["rb_probability"]
        out["bb2"] = spec["settings"][s2]["bb_probability"]
        out["rb2"] = spec["settings"][s2]["rb_probability"]
        parts.append(out)
    return pd.concat(parts)


def build(
    hall, since, snapshot=None, db_dir=None, specs=None, allow_spec_mismatch=False, config_path=None, event_def=None
):
    """台×日の表を作る。作成前に監査を行い、結果を d.attrs["audit"] に残す。
    スペックの不一致があれば停止する(allow_spec_mismatch=True で警告のみ)。
    ホール設定の除外日は集計から除き、変化点は監査行に出す(自動では分割しない)。"""
    raw = _load_raw(hall, since, db_dir)
    if snapshot is not None:
        raw = pd.concat([raw, snapshot], ignore_index=True)
    cfg = load_hall_config(hall, config_path)
    excluded_dates = {e["date"]: e["reason"] for e in cfg["exclusions"]}
    dropped = int(raw.date.isin(excluded_dates).sum())
    raw = raw[~raw.date.isin(excluded_dates)]
    hist = _layout_history(hall, db_dir)
    raw = attach_section(raw, hist)
    specs = load_specs(hall=hall) if specs is None else specs
    mismatches, _ = audit_specs(sorted(raw.m.unique()), specs)
    if mismatches and not allow_spec_mismatch:
        lines = [
            f"  {m} 設定{s} {k}: find_spec 1/{a:.1f} と マスターCSV 1/{b:.1f}" for m, s, k, a, b in mismatches[:12]
        ]
        raise SystemExit(
            "スペック不整合のため停止(find_spec と machine_master.csv が食い違う。公表値で直すこと):\n"
            + "\n".join(lines)
        )
    excluded = {}
    d = _posteriors(raw, specs, excluded)
    d.attrs["audit"] = {
        "hall": hall,
        "since": since,
        "last": f"{raw.d.max():%Y%m%d}",
        "models": sorted(raw.m.unique()),
        "spec_mismatches": mismatches,
        "excluded": excluded,
        "no_layout_rows": int(raw.section.isna().sum()),
        "layout_epochs": 0 if hist.empty else int(hist.valid_from.nunique()),
        "rows": len(raw),
        "excluded_dates": {k: v for k, v in excluded_dates.items() if (raw.date.max() >= k >= since) or dropped},
        "excluded_rows": dropped,
        "regime_in_period": [b for b in cfg["regime_boundaries"] if since <= b["date"] <= f"{raw.d.max():%Y%m%d}"],
    }
    audit = d.attrs["audit"]
    d["rbp"] = d.rb / d.g
    d["bbp"] = d.bb / d.g
    d["rb_good"] = d.rbp >= d.rb5  # RBが設定5水準以上
    d["bb_bad"] = d.bbp <= d.bb2  # BBが設定2以下
    d["fuhatsu"] = d.rb_good & ((d["diff"] <= 1000) | d.bb_bad)
    d["sec_diff"] = d.groupby(["date", "section"])["diff"].transform("mean")
    pv = raw.pivot_table(index="d", columns="u", values="diff", dropna=False)
    pv = pv.reindex(pd.date_range(pv.index.min(), pv.index.max()))
    r7 = pv.rolling(7, min_periods=4).mean().stack().rename("r7").reset_index()
    r7.columns = ["d", "u", "r7"]
    d = d.merge(r7, on=["d", "u"], how="left")
    d["r7band"] = (
        pd.cut(d.r7, [-1e9, -1500, -500, 500, 1e9], labels=["<=-1500", "-1500~-500", "-500~500", ">=500"])
        .astype(object)
        .fillna("NA")
    )
    rule_name, rule = pick_event_rule(cfg["event_days"], event_def)
    d["is_event"] = d.d.map(lambda ts: is_event_day(ts, rule)) if rule else np.nan
    audit["event_rule"] = bool(rule)
    audit["event_def"] = rule_name
    audit["event_status"] = (rule or {}).get("status", "")
    audit["event_defs_available"] = list((cfg["event_days"] or {}).get("definitions", {}))
    if rule:
        per_day = d.groupby("date").is_event.first()
        audit["event_days"], audit["normal_days"] = int(per_day.sum()), int((~per_day.astype(bool)).sum())
    d.attrs["audit"] = audit  # merge で attrs が失われるので付け直す
    return d


def format_audit(a):
    """出力の先頭に必ず出す監査行。期間・スペック・配置・対象外機種を明示する(結論の前提を隠さない)。"""
    lines = [
        f"[監査] {a['hall']} / 期間 {a['since']}〜{a['last']} / 台日 {a['rows']}"
        f" / 配置エポック {a['layout_epochs']} / 配置の無い台日 {a['no_layout_rows']}",
        f"[監査] スペック照合: 機種 {len(a['models'])}、不一致 {len(a['spec_mismatches'])}"
        + ("(許容して実行)" if a["spec_mismatches"] else "(すべて公表値と一致)"),
    ]
    if a["excluded"]:
        lines.append(
            "[監査] 推定の対象外: " + "、".join(f"{m}({n}台日: {why})" for m, (n, why) in sorted(a["excluded"].items()))
        )
    if a.get("event_rule"):
        lines.append(
            f"[監査] イベント日の定義 '{a['event_def']}' [{a['event_status']}]: 期間内 イベント日 {a['event_days']}日"
            f" / 通常日 {a['normal_days']}日 (選べる定義: {', '.join(a['event_defs_available'])})"
        )
    else:
        lines.append("[監査] イベント日の定義: 未登録(--day-type は all のみ)")
    if a["layout_epochs"] == 0:
        lines.append("[監査] 配置履歴が無いため島別の集計は出せない")
    if a.get("excluded_rows"):
        lines.append(
            f"[監査] 除外日(ホール設定): {a['excluded_rows']}台日を除外 / "
            + "、".join(f"{k}({v[:40]})" for k, v in a["excluded_dates"].items())
        )
    for b in a.get("regime_in_period", []):
        lines.append(f"[監査] 期間内の変化点 {b['date']}: {b['reason']}(結論は変化点の前後で分けて確認)")
    return "\n".join(lines)


def pairs(d):
    """前日の行に、翌日のph(ph_next)と、翌日がイベント日か(next_event。is_event 列があれば)を付ける。"""
    cols = ["u", "d", "ph"] + (["is_event"] if "is_event" in d.columns else [])
    nx = d[cols].copy()
    nx["d"] = nx["d"] - pd.Timedelta(days=1)
    nx = nx.rename(columns={"ph": "ph_next", "is_event": "next_event"})
    return d.merge(nx, on=["u", "d"])  # 前日の行は is_event(前日がイベント日か)を残し、翌日は next_event


class Boot:
    def __init__(self, z, n=300, seed=0):
        self.z = z
        self.agg = z.groupby("u").ph_next.agg(["sum", "count"])
        self.rng = np.random.default_rng(seed)
        self.n = n
        self.base = z.ph_next.mean()

    def ci(self, mask, ref=None):
        """群の平均 - 基準(既定は全体、refを渡すとその部分集合)の平均 を台単位ブートストラップで区間推定。"""
        idx_u = self.agg.index
        gs = self.z[mask].groupby("u").ph_next.agg(["sum", "count"]).reindex(idx_u).fillna(0).values
        if ref is None:
            b = self.agg.values
        else:
            b = self.z[ref].groupby("u").ph_next.agg(["sum", "count"]).reindex(idx_u).fillna(0).values
        vals = []
        for _ in range(self.n):
            i = self.rng.integers(0, len(idx_u), len(idx_u))
            if gs[i, 1].sum() == 0 or b[i, 1].sum() == 0:
                continue
            vals.append(gs[i, 0].sum() / gs[i, 1].sum() - b[i, 0].sum() / b[i, 1].sum())
        return np.percentile(vals, [5, 95])

    def line(self, label, mask, ref=None):
        """refを渡すと、その部分集合(機種・島)自身の平均との差を出す。"""
        n = int(mask.sum())
        if n < MIN_N:
            return f"{label:<40} n={n:4d} (少数)"
        mean = self.z.ph_next[mask].mean()
        base = self.base if ref is None else self.z.ph_next[ref].mean()
        lo, hi = self.ci(mask, ref)
        tag = "全体比" if ref is None else "自群比"
        return f"{label:<40} n={n:4d} 翌日5以上 {mean:.3f} ({tag} {mean - base:+.3f}, 90%CI {lo:+.3f}~{hi:+.3f})"


def cmd_groups(args):
    d = build(args.hall, args.since, allow_spec_mismatch=args.allow_spec_mismatch, event_def=args.event_def)
    print(format_audit(d.attrs["audit"]))
    z = _by_day_type(pairs(d), "next_event", args.day_type)  # 予測する翌日の種類で絞る(前日の特徴量は全日)
    if args.day_type != "all":
        print(
            f"[日の種類] 翌日が{ {'normal': '通常日', 'event': 'イベント日'}[args.day_type] }の組だけ (台日 {len(z)})"
        )
    b = Boot(z)
    print(f"{args.hall}: 連続2日の台日 {len(z)} / 台 {z.u.nunique()} / 翌日の平均 設定5以上確率(全体) {b.base:.3f}")
    print("\n[全体]  ※全体比は高設定の多い機種に条件の台日が集まる組成の効果を含む。判断は下の[機種別]の自群比で行う")
    for lab, mk in (
        ("前日RB良(設定5水準以上)", z.rb_good),
        ("  不発(RB良 & 差枚<=1000 or BB設定2以下)", z.fuhatsu),
        ("  RB良 & BBも悪くなく差枚>1000", z.rb_good & ~z.bb_bad & (z["diff"] > 1000)),
        ("前日RB悪(設定2以下) & 差枚<=-1000", (z.rbp <= z.rb2) & (z["diff"] <= -1000)),
        ("過去7日平均 -1500~-500", z.r7band == "-1500~-500"),
        ("過去7日平均 >=500", z.r7band == ">=500"),
    ):
        print(b.line(lab, mk))
    print("\n[条件の組み合わせ: 前日RB良 x 過去7日平均]")
    for rg in (True, False):
        for band in ("-1500~-500", "-500~500", ">=500"):
            print(b.line(f"RB良={'有' if rg else '無'} / 7日{band}", (z.rb_good == rg) & (z.r7band == band)))
    print("\n[機種別: 前日RB良の上乗せ]")
    for m, sub in z.groupby("m"):
        if len(sub) < 300:
            continue
        mk = z.m == m
        print(f"--- {m} ({sub.u.nunique()}台, 翌日平均 {z.ph_next[mk].mean():.3f})")
        print("  " + b.line("前日RB良", mk & z.rb_good, ref=mk))
        print("  " + b.line("過去7日 -1500~-500", mk & (z.r7band == "-1500~-500"), ref=mk))
    print("\n[島別: 前日RB良の上乗せ(島の台日300以上)]")
    for sec, sub in z.groupby("section"):
        if len(sub) < 300:
            continue
        mk = z.section == sec
        print(
            f"--- {sec} ({sub.u.nunique()}台, 翌日平均 {z.ph_next[mk].mean():.3f})  "
            + b.line("前日RB良", mk & z.rb_good, ref=mk).strip()
        )


def _edge_factors(d_upto, models):
    """機種ごとの端の係数。d_upto は候補日の前日までの台日だけ(未来を使わない)。"""
    return {m: edge_factor(d_upto, m) for m in models}


def _fixed_carry(d_upto, hist, day):
    """候補日の各台の 台固定×持ち越し の点数。
    台固定 = 台ごとの過去の平均ph(前日まで)を機種平均へ縮めた値(位置の効果も含む)。
    持ち越し = 群平均 ÷ 機種の翌日平均(持ち越しが無いホールでは約1で、台固定だけが効く)。
    台固定が無いホール(みとや)では係数が支配し、持ち越しが無いホール(蒲田7)では台固定が支配する。"""
    out = pd.Series(np.nan, index=day.index)
    for m, g in day.groupby("m"):
        upto = d_upto[d_upto.m == m]
        mm = upto.groupby("u").ph.agg(["mean", "count"])
        model_mean = upto.ph.mean()
        shrunk = (mm["mean"] * mm["count"] + model_mean * FIXED_SHRINK) / (mm["count"] + FIXED_SHRINK)
        hm = hist[hist.m == m]
        next_mean = hm.ph_next.mean() if len(hm) else np.nan
        carry = g.cell_mean / next_mean if next_mean and next_mean > 0 else 1.0
        out.loc[g.index] = g.u.map(shrunk).fillna(model_mean) * carry
    return out


def _attach_cells(hist, day, edge_f=None, d_upto=None):
    """履歴の群平均を、候補日の各台に付ける。
    score_edge = 群平均 × 端の係数(端の台のみ。edge_f が無ければ群平均そのまま)。
    score = 台固定×持ち越し(d_upto が渡されたとき。無ければ score_edge と同じ)。アウトオブサンプルの oos で、
    ホールの型(みとや=持ち越し、蒲田7=台固定)を問わず最も安定した(検証結果 17)。
    持ち越しは機種ごとに違う(マイジャグラーVのみ確認)ので、機種ごとに群平均を取る。台日が少ない群は機種×RB良に粗くする。
    島の端は高設定が入りにくい(検証結果 15)ので、score_edge は端の台の優先度を係数で下げる(外さない)。"""
    cell = (
        hist.groupby(["m", "rb_good", "r7band"])
        .ph_next.agg(["mean", "count"])
        .rename(columns={"mean": "cell_mean", "count": "cell_n"})
    )
    coarse = (
        hist.groupby(["m", "rb_good"]).ph_next.agg(["mean", "count"]).rename(columns={"mean": "c_mean", "count": "c_n"})
    )
    day = day.merge(cell, left_on=["m", "rb_good", "r7band"], right_index=True, how="left")
    day = day.merge(coarse, left_on=["m", "rb_good"], right_index=True, how="left")
    thin = day.cell_n.isna() | (day.cell_n < MIN_N)
    day.loc[thin, "cell_mean"] = day.loc[thin, "c_mean"]
    day.loc[thin, "cell_n"] = day.loc[thin, "c_n"]
    factor = day.m.map(edge_f or {}).fillna(1.0)
    day["score_edge"] = day.cell_mean * np.where(day.dist == 1, factor, 1.0)
    day["score"] = day.score_edge if d_upto is None else _fixed_carry(d_upto, hist, day)
    return day


def cmd_check(args):
    """前日までの履歴だけで作った候補が、実際の当日にどうだったかを検証する(答え合わせ)。"""
    d = build(args.hall, args.since, allow_spec_mismatch=args.allow_spec_mismatch, event_def=args.event_def)
    print(format_audit(d.attrs["audit"]))
    target = pd.Timestamp(args.date)
    prev = target - pd.Timedelta(days=1)
    if not (d.d == target).any():
        raise SystemExit(f"{args.date} のデータがDBに無い(DB最終日 {d.d.max():%Y%m%d})")
    hist = pairs(d[d.d < prev])  # 前日までの組だけ(当日の結果は使わない)
    day = _attach_cells(hist, d[d.d == prev].copy(), _edge_factors(d[d.d <= prev], d.m.unique()), d[d.d <= prev])
    act = d[d.d == target][["u", "ph", "g", "rb", "bb"]].rename(
        columns={"ph": "ph_act", "g": "g_act", "rb": "rb_act", "bb": "bb_act"}
    )
    z = day.merge(act, on="u")
    print(
        f"{args.hall} {args.date}: 前日の候補 {len(day)}台 / 当日の確定が揃った台 {len(z)} / 履歴は {prev:%Y%m%d} の前日まで"
    )
    for m, s in z.groupby("m"):
        if len(s) < 20 or s.score.nunique() < 2:
            continue
        rho = s.score.rank().corr(s.ph_act.rank())
        top = s.sort_values("score", ascending=False).head(10)
        rest = s.drop(top.index)
        print(
            f"--- {m} ({len(s)}台)  順位相関(群平均×当日ph) {rho:+.3f}  上位10の当日平均ph {top.ph_act.mean():.3f}  それ以外 {rest.ph_act.mean():.3f}  全体 {s.ph_act.mean():.3f}"
        )
    m0 = "マイジャグラーV"
    s = z[z.m == m0].sort_values("score", ascending=False)
    if len(s):
        print(f"\n[{m0}] 点数(台固定×持ち越し)の高い順(当日のphは確定データから)")
        s = s.assign(rb_rate=(s.g_act / s.rb_act.where(s.rb_act > 0)).round(0))
        print(
            s.head(args.top)[
                [
                    "u",
                    "dist",
                    "rb_good",
                    "r7band",
                    "cell_mean",
                    "score",
                    "cell_n",
                    "g_act",
                    "rb_act",
                    "bb_act",
                    "rb_rate",
                    "ph_act",
                ]
            ]
            .round(3)
            .to_string(index=False)
        )


def cmd_tomorrow(args):
    snap, name = _latest_snapshot(args.hall)
    d = build(
        args.hall, args.since, snapshot=snap, allow_spec_mismatch=args.allow_spec_mismatch, event_def=args.event_def
    )
    print(format_audit(d.attrs["audit"]))
    hist = pairs(d[d.d < snap.d.iloc[0]])
    stamp = snap.d.iloc[0]
    day = _attach_cells(hist, d[d.d == stamp].copy(), _edge_factors(d[d.d <= stamp], d.m.unique()), d[d.d <= stamp])
    print(f"スナップショット {name} / 履歴の翌日平均 {hist.ph_next.mean():.3f} / 今日の候補台日 {len(day)}")
    print("今日の差枚が無い収集では差枚由来の型(不発)は使わず、RB良と過去7日で見る。")
    print(
        "点数(score)=台固定×持ち越し(台ごとの過去の平均ph×群平均の相対係数)。score_edge=群平均×端の係数(参考)。dist==1が島の端。\n"
    )
    cols = ["u", "m", "dist", "g", "rb", "bb", "rb_good", "r7band", "cell_mean", "score_edge", "score", "cell_n", "ph"]
    day = day.sort_values(["score", "ph"], ascending=False)
    print(day.head(args.top)[cols].round(3).to_string(index=False))


def default_cut(d):
    """前半・後半の境界。台日の日付の中央(営業日の数で半分に分ける)。"""
    dates = sorted(d.date.unique())
    return dates[len(dates) // 2]


def split_half_rank(d, cut, min_days=20, n_perm=1000, seed=0):
    """機種ごとに、台別の平均ph(高設定になりやすさ)が前半と後半で再現するかを順位相関と並べ替え検定で見る。
    両期間とも min_days 日以上ある台だけを使い、5台未満の機種は相関を出さない。
    注意: phの事前分布は全期間から推定している(台別の値そのものは前半・後半で独立)。"""
    rng = np.random.default_rng(seed)
    rows = []
    for m, s in d.groupby("m"):
        a = s[s.date < cut].groupby("u").ph.agg(["mean", "count"])
        b = s[s.date >= cut].groupby("u").ph.agg(["mean", "count"])
        j = a.join(b, lsuffix="1", rsuffix="2", how="inner")
        j = j[(j.count1 >= min_days) & (j.count2 >= min_days)]
        row = {
            "m": m,
            "n": len(j),
            "base": s.ph.mean(),
            "rho": np.nan,
            "p": np.nan,
            "top3_next": np.nan,
            "all_next": np.nan,
        }
        if len(j) >= 5:
            r1, r2 = j.mean1.rank(), j.mean2.rank()
            rho = r1.corr(r2)
            perm = [r1.corr(pd.Series(rng.permutation(r2.values), index=r2.index)) for _ in range(n_perm)]
            row.update(
                rho=rho,
                p=(np.sum(np.array(perm) >= rho) + 1) / (n_perm + 1),
                top3_next=j.sort_values("mean1", ascending=False).head(3).mean2.mean(),
                all_next=j.mean2.mean(),
            )
        rows.append(row)
    return pd.DataFrame(rows)


def carry_by_half(z, cut):
    """前日RB良・過去7日低調の自群比を、前半(前日が cut より前)と後半に分けて出す。(機種, 区間, ラベル, 行) のリスト。"""
    out = []
    for name, part in (("前半", z[z.date < cut]), ("後半", z[z.date >= cut])):
        if part.empty:
            continue
        b = Boot(part)
        for m, sub in part.groupby("m"):
            if len(sub) < 300:
                continue
            mk = part.m == m
            out.append((m, name, "前日RB良", b.line("前日RB良", mk & part.rb_good, ref=mk)))
            out.append(
                (m, name, "過去7日低調", b.line("過去7日 -1500~-500", mk & (part.r7band == "-1500~-500"), ref=mk))
            )
    return out


def cmd_splithalf(args):
    d = build(args.hall, args.since, allow_spec_mismatch=args.allow_spec_mismatch, event_def=args.event_def)
    print(format_audit(d.attrs["audit"]))
    cut = args.cut or default_cut(d)
    print(f"\n[前半・後半の境界] {cut} (前半 {d.date.min()}〜{cut} 未満 / 後半 {cut}〜{d.date.max()})")
    dt = _by_day_type(d, "is_event", args.day_type)  # その台日の日の種類で絞る
    if args.day_type != "all":
        print(f"[日の種類] {dict(normal='通常日', event='イベント日')[args.day_type]}の台日だけ ({len(dt)}台日)")
    print(
        "\n[台別の平均ph(高設定になりやすさ)が前半と後半で再現するか]  ※順位相関が高くp<0.05なら台固定の兆候。再現しなければ採用しない"
    )
    t = split_half_rank(dt, cut, min_days=args.min_days)
    for r in t.itertuples():
        if np.isnan(r.rho):
            print(f"--- {r.m}: 両期間{args.min_days}日以上の台が{r.n}台で5台未満のため相関は出さない")
        else:
            print(
                f"--- {r.m}: {r.n}台 機種平均ph {r.base:.3f} / 順位相関 {r.rho:+.2f} (並べ替えp={r.p:.3f})"
                f" / 前半上位3台の後半ph {r.top3_next:.3f} (後半の全台 {r.all_next:.3f})"
            )
    z = _by_day_type(pairs(d), "next_event", args.day_type)
    print("\n[持ち越しの再現: 前日RB良・過去7日低調の自群比を前半・後半で比べる]  ※両期間で同じ向きなら再現")
    last = None
    for m, half, _, line in carry_by_half(z, cut):
        if m != last:
            print(f"--- {m}")
            last = m
        print(f"  {half} {line}")


DIST_BANDS = [0, 1, 2, 4, 8, 99]  # 島の端からの最短距離の帯(1=端, 2, 3-4, 5-8, 9+)


def edge_effect(d, cut, n_boot=300, seed=0):
    """機種ごとに、島の端(dist==1)と端以外の台日の平均ph(設定5以上の確率)を前半・後半別に比べる。
    位置は台日ごとの日付つき配置なので、配置替えをまたぐホールでも使える。差(端−端以外)の90%CIは台単位のブートストラップ。
    戻り値: DataFrame(m, half, n_edge, n_other, edge, other, diff, lo, hi)"""
    rng = np.random.default_rng(seed)
    rows = []
    d = d[d.dist.notna()]
    for m, s in d.groupby("m"):
        for half, part in (("前半", s[s.date < cut]), ("後半", s[s.date >= cut])):
            e = part[part.dist == 1]
            o = part[part.dist > 1]
            if len(e) < MIN_N or len(o) < MIN_N:
                rows.append({"m": m, "half": half, "n_edge": len(e), "n_other": len(o), "diff": np.nan})
                continue
            ge = e.groupby("u").ph.agg(["sum", "count"])
            go = o.groupby("u").ph.agg(["sum", "count"])
            vals = []
            for _ in range(n_boot):
                ie = rng.integers(0, len(ge), len(ge))
                io = rng.integers(0, len(go), len(go))
                a, b = ge.values[ie], go.values[io]
                vals.append(a[:, 0].sum() / a[:, 1].sum() - b[:, 0].sum() / b[:, 1].sum())
            lo, hi = np.percentile(vals, [5, 95])
            rows.append(
                {
                    "m": m,
                    "half": half,
                    "n_edge": len(e),
                    "n_other": len(o),
                    "edge": e.ph.mean(),
                    "other": o.ph.mean(),
                    "diff": e.ph.mean() - o.ph.mean(),
                    "lo": lo,
                    "hi": hi,
                }
            )
    return pd.DataFrame(rows)


def residual_fixed(d, cut, min_days=20, n_perm=2000, seed=0):
    """位置(島の端からの距離の帯)の平均を引いた後の、台別の平均phの前半・後半の相関(並べ替え検定)。
    位置が日付で変わる台を混ぜないよう、最新の配置エポック(その台の位置が一定の期間)の台日だけを使う。
    戻り値: DataFrame(m, n, rho_all, p_all, rho_resid, p_resid) 。rho_residが高ければ位置を除いても台固定が残る。"""
    rng = np.random.default_rng(seed)
    rows = []
    d = d[d.dist.notna()]
    for m, s in d.groupby("m"):
        a = s[s.date < cut].groupby("u").agg(m1=("ph", "mean"), c1=("ph", "count"), dist=("dist", "min"))
        b = s[s.date >= cut].groupby("u").agg(m2=("ph", "mean"), c2=("ph", "count"), dist2=("dist", "min"))
        j = a.join(b, how="inner")
        j = j[(j.c1 >= min_days) & (j.c2 >= min_days) & (j.dist == j.dist2)]  # 位置が前後半で変わらない台だけ
        if len(j) < 8:
            rows.append({"m": m, "n": len(j)})
            continue
        band = pd.cut(j.dist, DIST_BANDS)
        r1 = j.m1 - j.groupby(band, observed=True).m1.transform("mean")
        r2 = j.m2 - j.groupby(band, observed=True).m2.transform("mean")

        def pc(x, y):
            r = np.corrcoef(x, y)[0, 1]
            perm = [np.corrcoef(x, rng.permutation(y))[0, 1] for _ in range(n_perm)]
            return r, (np.sum(np.array(perm) >= r) + 1) / (n_perm + 1)

        rho_all, p_all = pc(j.m1.values, j.m2.values)
        rho_res, p_res = pc(r1.values, r2.values)
        rows.append({"m": m, "n": len(j), "rho_all": rho_all, "p_all": p_all, "rho_resid": rho_res, "p_resid": p_res})
    return pd.DataFrame(rows)


def cmd_position(args):
    d = build(args.hall, args.since, allow_spec_mismatch=args.allow_spec_mismatch, event_def=args.event_def)
    a = d.attrs["audit"]
    print(format_audit(a))
    if a["layout_epochs"] == 0 or d.dist.isna().all():
        print("\n配置履歴(島の端からの順位)が無いため位置の分析は出せない")
        return
    cut = args.cut or default_cut(d)
    print(f"\n[前半・後半の境界] {cut}")
    d = _by_day_type(d, "is_event", args.day_type)  # その台日の日の種類で絞る
    if args.day_type != "all":
        print(f"[日の種類] {dict(normal='通常日', event='イベント日')[args.day_type]}の台日だけ ({len(d)}台日)")
    print("\n[島の端(rank_from_min/max==1)は低いか: 端−端以外の平均ph。前半・後半で同じ向きなら再現]")
    t = edge_effect(d, cut)
    for r in t.itertuples():
        if np.isnan(r.diff):
            print(f"--- {r.m} {r.half}: 端{r.n_edge}台日/端以外{r.n_other}台日 (少数)")
        else:
            print(
                f"--- {r.m} {r.half}: 端 {r.edge:.3f} ({r.n_edge}台日) / 端以外 {r.other:.3f} ({r.n_other}台日)"
                f" / 差 {r.diff:+.3f} (90%CI {r.lo:+.3f}~{r.hi:+.3f})"
            )
    print("\n[位置を除いた台固定: 位置帯の平均を引いた残差の、台別平均phの前半・後半の相関(最新の配置エポックのみ)]")
    print("  ※rho_residが高くp<0.05なら、位置では説明できない台ごとの偏りが続いている。再現しなければ採用しない")
    for r in residual_fixed(d, cut, min_days=args.min_days).itertuples():
        if getattr(r, "rho_all", None) is None or np.isnan(r.rho_all):
            print(f"--- {r.m}: 位置が前後半で一定の台が{r.n}台で8台未満のため出さない")
        else:
            print(
                f"--- {r.m}: {r.n}台 / 位置を除く前の相関 {r.rho_all:+.2f}(p={r.p_all:.3f})"
                f" → 位置を除いた残差の相関 {r.rho_resid:+.2f}(p={r.p_resid:.3f})"
            )


VARIANTS = ("base", "edge_adj", "edge_excl", "fixed", "fixed_carry")
FIXED_SHRINK = 20  # 台ごとの平均phを機種平均へ縮める強さ(台日換算)。台日が少ない台の偶然の高さを抑える


def edge_factor(d_upto, model):
    """機種ごとの端の係数 = 端の台のph平均 ÷ 端以外のph平均(0.2〜1.0に収める。端を持ち上げない)。
    d_upto は評価日より前の台日だけを渡すこと(未来を使わない)。台日が足りなければ1.0。"""
    s = d_upto[(d_upto.m == model) & d_upto.dist.notna()]
    e, o = s[s.dist == 1].ph, s[s.dist > 1].ph
    if len(e) < MIN_N or len(o) < MIN_N or o.mean() <= 0:
        return 1.0
    return float(np.clip(e.mean() / o.mean(), 0.2, 1.0))


def score_variants(d, prev, model, top=10):
    """prev(前日)までの履歴だけから、3つの案で上位 top 台の台番号を決める。{案: [台番号, ...]} を返す。
    評価日(prevの翌日)以降の列は一切使わない。"""
    hist = pairs(d[(d.m == model) & (d.d < prev)])
    day = _attach_cells(hist, d[(d.m == model) & (d.d == prev)].copy())
    if day.empty or day.cell_mean.isna().all():
        return {v: [] for v in VARIANTS}
    upto = d[(d.m == model) & (d.d <= prev)]
    f = edge_factor(d[d.d <= prev], model)
    # 台固定: 台ごとの過去の平均ph(前日まで)を機種平均へ縮める。位置の効果も台ごとの平均に含まれる。
    mm = upto.groupby("u").ph.agg(["mean", "count"])
    model_mean = upto.ph.mean()
    shrunk = (mm["mean"] * mm["count"] + model_mean * FIXED_SHRINK) / (mm["count"] + FIXED_SHRINK)
    # 持ち越しの相対係数: 群平均 ÷ 機種の翌日平均(持ち越しが無いホールでは約1で、台固定だけが効く)
    next_mean = hist.ph_next.mean() if len(hist) else np.nan
    carry = day.cell_mean / next_mean if next_mean and next_mean > 0 else pd.Series(1.0, index=day.index)
    day = day.assign(
        s_base=day.cell_mean,
        s_adj=day.cell_mean * np.where(day.dist == 1, f, 1.0),
        s_fixed=day.u.map(shrunk).fillna(model_mean),
    )
    day["s_fixed_carry"] = day.s_fixed * carry.fillna(1.0)

    def pick(frame, col):
        return list(frame.sort_values([col, "ph"], ascending=False).head(top).u)

    return {
        "base": pick(day, "s_base"),
        "edge_adj": pick(day, "s_adj"),
        "edge_excl": pick(day[~(day.dist == 1)], "s_base"),
        "fixed": pick(day, "s_fixed"),
        "fixed_carry": pick(day, "s_fixed_carry"),
    }


def oos_eval(d, model, start, top=10, day_type="all"):
    """start 以降の各日(前日のデータがある日)について、案ごとの候補の当日平均phと、それ以外の平均phを出す。
    day_type(all/normal/event)は評価する当日の種類。候補を作る履歴は全日を使う。
    戻り値: DataFrame(date, variant, cand, rest, diff, n_cand)。"""
    dates = sorted(d.date.unique())
    event_by_date = d.groupby("date").is_event.first() if "is_event" in d.columns else None
    rows = []
    for i, t in enumerate(dates):
        if t < start or i == 0:
            continue
        if day_type != "all":
            if event_by_date is None or event_by_date.isna().all():
                raise SystemExit(
                    "このホールはイベント日の定義が未登録(config/juggler_analysis.json の event_days に追加する)"
                )
            if bool(event_by_date[t]) != (day_type == "event"):
                continue
        prev = pd.Timestamp(dates[i - 1])
        if (pd.Timestamp(t) - prev).days != 1:
            continue  # 連続日だけ
        act = d[(d.m == model) & (d.date == t)].set_index("u").ph
        if len(act) < top + 5:
            continue
        for var, units in score_variants(d, prev, model, top).items():
            c = act[act.index.isin(units)]
            r = act[~act.index.isin(units)]
            if len(c) == 0 or len(r) == 0:
                continue
            rows.append(
                {
                    "date": t,
                    "variant": var,
                    "cand": c.mean(),
                    "rest": r.mean(),
                    "diff": c.mean() - r.mean(),
                    "n_cand": len(c),
                }
            )
    return pd.DataFrame(rows)


def _day_ci(x, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    x = np.asarray(x, dtype=float)
    m = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return np.percentile(m, [5, 95])


def cmd_oos(args):
    d = build(args.hall, args.since, allow_spec_mismatch=args.allow_spec_mismatch, event_def=args.event_def)
    print(format_audit(d.attrs["audit"]))
    t = oos_eval(d, args.model, args.start, top=args.top, day_type=args.day_type)
    if args.day_type != "all":
        print(f"[日の種類] 評価する当日が{dict(normal='通常日', event='イベント日')[args.day_type]}の日だけ")
    if t.empty:
        raise SystemExit("評価できる日が無い(--start を見直す)")
    days = t.date.nunique()
    print(
        f"\n[アウトオブサンプル] {args.hall} / {args.model} / {t.date.min()}〜{t.date.max()} {days}日 / 候補は上位{args.top}台"
    )
    print("案 | 候補の当日平均ph | それ以外 | 差(候補−それ以外) 90%CI | 差が正の日")
    for var in VARIANTS:
        s = t[t.variant == var]
        lo, hi = _day_ci(s["diff"])
        print(
            f"{var:<9} | {s.cand.mean():.3f} | {s.rest.mean():.3f} | {s['diff'].mean():+.3f} ({lo:+.3f}~{hi:+.3f}) | {(s['diff'] > 0).mean():.0%}"
        )
    base = t[t.variant == "base"].set_index("date")["diff"]
    print("\n[案 − base の差(同じ日どうしの対応。正なら端を反映したほうが良い)]")
    for var in VARIANTS[1:]:
        s = t[t.variant == var].set_index("date")["diff"]
        dd = (s - base).dropna()
        lo, hi = _day_ci(dd)
        print(
            f"{var:<9} − base: {dd.mean():+.4f} (90%CI {lo:+.4f}~{hi:+.4f}) / 良くなった日 {(dd > 0).mean():.0%} / 悪化した日 {(dd < 0).mean():.0%}"
        )


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (
        ("groups", cmd_groups),
        ("tomorrow", cmd_tomorrow),
        ("check", cmd_check),
        ("splithalf", cmd_splithalf),
        ("position", cmd_position),
        ("oos", cmd_oos),
    ):
        sp = sub.add_parser(name)
        sp.add_argument("--hall", default=DEFAULT_HALL)
        sp.add_argument("--since", default="20260601")
        sp.add_argument(
            "--allow-spec-mismatch",
            action="store_true",
            help="find_specとマスターCSVが食い違っても止めない(警告のみ)。通常は使わず公表値で直す",
        )
        if name in ("tomorrow", "check"):
            sp.add_argument("--top", type=int, default=20)
        if name == "check":
            sp.add_argument("--date", required=True, help="答え合わせする当日(YYYYMMDD)")
        sp.add_argument(
            "--event-def",
            default=None,
            help="イベント日の定義の名前(config/juggler_analysis.json の event_days.definitions)。既定はdefault。選べる名前は[監査]行に出る",
        )
        if name in ("groups", "splithalf", "position", "oos"):
            sp.add_argument(
                "--day-type",
                choices=DAY_TYPES,
                default="all",
                help="予測する(評価する)日の種類。normal=通常日、event=イベント日(ホール設定のevent_days)。既定は全日",
            )
        if name == "oos":
            sp.add_argument("--model", default="マイジャグラーV", help="評価する機種(候補はこの機種の中から選ぶ)")
            sp.add_argument("--start", default="20260801", help="評価を始める日(YYYYMMDD)")
            sp.add_argument("--top", type=int, default=10, help="候補の台数")
        if name in ("splithalf", "position"):
            sp.add_argument("--cut", default=None, help="前半・後半の境界(YYYYMMDD)。既定は台日の日付の中央")
            sp.add_argument("--min-days", type=int, default=20, help="両期間で必要な最低日数")
        sp.set_defaults(fn=fn)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
