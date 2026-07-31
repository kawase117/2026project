"""死亡検知: 既知セオリーの効果量が過去水準から乖離していないか継続監視する。

なぜこれが要るか（`results/regime/FINDINGS.md` 追試6・追試7 の帰結）:
    みとやの角番1シグナルは16か月間 +0.327z で安定し、2026-04-27 に一度きり終わった。
    観測されたのは「2〜3ヶ月で入れ替わる循環レジーム」ではなく「長く効く法則が
    ある日死ぬ」という形だった。循環モデルなら常時レジーム推定が要るが（追試1のとおり
    推定は間に合わない）、この形なら **安定した法則を使い続け、死んだことを事後検知する
    監視だけ持てばよい**。検知が3か月遅れても、16か月効く法則に対してなら十分に価値がある。

    追試7 で「破断は外部イベント（店長交代・工事）に駆動される」ことも分かった。
    したがってこの監視は予測器ではなく **アラーム** である。鳴ったら原因を外部に探しに行く。

検定しているもの:
    「効果がゼロか」ではなく **「効果が過去水準から変わったか」**。
    この区別が本モジュールの核心である。効果がゼロでないことの検定は
    baseline 期間で既に済んでおり、ここで知りたいのは差分のほうだから、
    帰無仮説は「recent の効果 == baseline の効果」になる。

指標（差枚を使わない理由）:
    差枚 = 3 × G × (機械割 - 1) なので、回転数に効く変数を評価すると
    設定差でないものを設定差として計上する。蒲田7の角番1では差枚 -162枚 の
    ほぼ全部が「+624G 多く回されている」ことの帰結だった（追試8）。
    よって payout(機械割) と bonus_rate(BB+RB) / rb_rate を使う。

    BB と RB を両方見るのも意図的である。設定は両方を同じ向きに動かすので、
    片方だけ見ると符号が食い違って判断を誤る（追試9）。

効果量の定義:
    resid = 値 − 同日×同機種の平均   （機種構成の混入を除く）
    日次効果 = mean(resid | 対象) − mean(resid | 対象外)
    この日次系列を baseline 期間と recent 窓に分け、それぞれ7日ブロック
    ブートストラップして差の分布を作る。

判定（status）:
    NO_BASELINE   baseline でそもそも効果が有意でない。死亡検知の対象外
    DEAD          差が有意 かつ recent の CI がゼロを跨ぐ
    REVERSED      差が有意 かつ recent の符号が baseline と逆
    WEAKENED      差が有意 かつ 同符号で縮小
    STRENGTHENED  差が有意 かつ 同符号で拡大
    ALIVE         差が有意でなく、かつ「baseline の半減」なら検出できる分解能がある
    UNDERPOWERED  差が有意でないが、分解能が足りず「変わっていない」と言えない

    UNDERPOWERED を ALIVE と区別するのが重要である。追試1で確認したとおり
    日次分散が大きい系列では窓平均の標準誤差が大きく、null は情報を持たない。

使い方:
    venv\\Scripts\\python.exe -m backtest.deathwatch
    venv\\Scripts\\python.exe -m backtest.deathwatch --recent-days 120
    venv\\Scripts\\python.exe -m backtest.deathwatch --claim mitoya_jug_corner1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.run_backtest import apply_eligibility, block_bootstrap_means, load_frame

REGISTRY = Path(__file__).resolve().parent / "deathwatch" / "claims.json"
RESULT_DIR = Path(__file__).resolve().parent / "results" / "deathwatch"

# 指標ごとの表示単位。生値は小さすぎて読めないので倍率をかける。
UNITS = {
    "payout": ("pp", 100.0),
    "rb_rate": ("回/1000G", 1000.0),
    "bonus_rate": ("回/1000G", 1000.0),
}
BLOCK = 7  # 同じ台が連日入るので系列相関を保存する
MIN_DAYS = 30  # これ未満の窓は判定しない
MIN_TARGET_DAYS = 10  # 日付軸(cross_day)で、各期間に必要な対象日の本数
DEATH_RATIO = 0.5  # 「baseline の半減を検出できるか」を分解能の基準にする


def load_claims(path: Path = REGISTRY) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rakuen_clean_edge1(df: pd.DataFrame) -> pd.Series:
    """楽園の「clean 列の端(depth=1)」。§2.1c で確定した現行の端番定義。

    旧 `section_edge1`（`rank_from_min==1 | rank_from_max==1`）とは別物である。
    旧定義は2列背中合わせ島を1 section にまとめていた時代の名残で、島の片端しか
    拾えていなかった（FINDINGS 追試11）。さらに frame（外周）や interior_split は
    「端」の物理的意味が違い投入単位として機能していないため、clean 列に限る必要がある。

    エポックは日付から引く。楽園は 2026-07-06 に島配列の工事があり、section 名の
    集合そのものが変わる（`machine_layout_history` の2エポック）。
    """
    from eda.rakuen_section_classification import POST_EPOCH, PRE_EPOCH, classify

    epoch = np.where(df["date"] < POST_EPOCH, PRE_EPOCH, POST_EPOCH)
    group = pd.Series(
        [classify(s, e) if isinstance(s, str) else None for s, e in zip(df["section"], epoch)],
        index=df.index,
    )
    depth = df[["rank_from_min", "rank_from_max"]].min(axis=1)
    return (group == "clean") & (depth == 1)


# 派生 target。値は (判定に必要な実列, マスク関数)。ホール固有の定義はここに閉じ込める。
DERIVED_TARGETS = {
    # 素朴な端番。楽園では §2.1c により rakuen_clean_edge1 に置き換わっている。
    "section_edge1": (
        ["rank_from_min", "rank_from_max"],
        lambda df: (df["rank_from_min"] == 1) | (df["rank_from_max"] == 1),
    ),
    # 楽園専用。他ホールの section 命名では classify() が意味を持たない。
    "rakuen_clean_edge1": (
        ["section", "rank_from_min", "rank_from_max"],
        _rakuen_clean_edge1,
    ),
}


def target_columns(target: dict) -> list[str]:
    """target の判定に使う実列名。欠損行を落とすために必要。

    レイアウト未登録の台は `rank_from_*` が NULL になる。これを放置すると
    「対象ではない」と評価されて対照群に混ざり、コントラストが薄まる。
    位置が分からない台は対象群にも対照群にも入れてはいけない。
    """
    cols: list[str] = []
    for field in target:
        if field in DERIVED_TARGETS:
            cols += DERIVED_TARGETS[field][0]
        else:
            cols.append(field)
    return cols


def target_mask(df: pd.DataFrame, target: dict) -> pd.Series:
    """対象群のマスク。派生条件は DERIVED_TARGETS に登録したものだけ使える。"""
    mask = pd.Series(True, index=df.index)
    for field, cond in target.items():
        if field in DERIVED_TARGETS:
            hit = DERIVED_TARGETS[field][1](df)
            mask &= hit if cond else ~hit
        elif isinstance(cond, list):
            mask &= df[field].isin(cond)
        else:
            mask &= df[field] == cond
    return mask


def daily_effect(df: pd.DataFrame, metric: str, is_target: pd.Series) -> pd.Series:
    """日次の「対象 − 対象外」を、同日×同機種の残差ベースで返す。

    同日にその機種が1台しかない行は残差が定義上0になり効果を薄めるので落とす。
    """
    sub = df[df[metric].notna()].copy()
    sub["_t"] = is_target.reindex(sub.index)
    g = sub.groupby(["date", "machine_name"])[metric]
    sub["_resid"] = sub[metric] - g.transform("mean")
    sub = sub[g.transform("size") >= 2]

    wide = sub.groupby(["date", "_t"])["_resid"].mean().unstack()
    if wide.shape[1] < 2:
        return pd.Series(dtype=float)
    return (wide[True] - wide[False]).dropna().sort_index()


def daily_level(df: pd.DataFrame, metric: str) -> pd.Series:
    """日次の「機種構成を調整した平均水準」。日付軸の claim 用。

    位置軸(`same_day`)は同日の対象/対象外を引き算するので機種構成が自然に相殺されるが、
    日付軸ではその日の全台が対象側に入るため同日対比が作れない。代わりに日をまたいで
    水準を比較する必要があり、そのままだと機種の入替が効果に化ける。
    そこで各行から **その機種の全期間平均** を引いてから日次平均を取る。

    注意: 引く平均は全期間から取るので baseline と recent がわずかに混ざる。
    これは構成の統制であって効果そのものではないため許容するが、
    機種が総入替されるような期間をまたぐ比較では信用しないこと。
    """
    sub = df[df[metric].notna()].copy()
    sub["_r"] = sub[metric] - sub.groupby("machine_name")[metric].transform("mean")
    return sub.groupby("date")["_r"].mean().sort_index()


def _ci(arr: np.ndarray) -> tuple[float, float]:
    return (float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5)))


def classify(base: float, base_ci, recent: float, recent_ci, delta_ci) -> str:
    if not (base_ci[0] * base_ci[1] > 0):
        return "NO_BASELINE"
    changed = delta_ci[0] * delta_ci[1] > 0
    if changed:
        if not (recent_ci[0] * recent_ci[1] > 0):
            return "DEAD"
        if np.sign(recent) != np.sign(base):
            return "REVERSED"
        return "WEAKENED" if abs(recent) < abs(base) else "STRENGTHENED"
    half_width = (delta_ci[1] - delta_ci[0]) / 2
    return "ALIVE" if half_width < abs(base) * DEATH_RATIO else "UNDERPOWERED"


def evaluate(claim: dict, recent_days: int) -> list[dict]:
    df = load_frame(claim["hall"])
    if claim.get("date_min"):
        df = df[df["date"] >= claim["date_min"]]
    if claim.get("date_max"):
        df = df[df["date"] <= claim["date_max"]]
    df = apply_eligibility(df, claim["universe"])
    cross_day = claim.get("contrast") == "cross_day"
    if cross_day:
        # 日付軸。target は {"dd": [7,17,27]} の形で「日」を選ぶ。
        df = df.assign(dd=df["date"].str[6:8].astype(int))
        target_dd = set(claim["target"]["dd"])
    else:
        # 位置が分からない台は対象群にも対照群にも入れない（target_columns 参照）。
        df = df.dropna(subset=target_columns(claim["target"]))
        is_target = target_mask(df, claim["target"])

    rows = []
    for metric in claim["metrics"]:
        unit, scale = UNITS[metric]
        row = {"claim_id": claim["claim_id"], "hall": claim["hall"], "metric": metric, "unit": unit}

        if cross_day:
            lv = daily_level(df, metric)
            tgt = pd.Series(lv.index.str[6:8].astype(int).isin(target_dd), index=lv.index)
            if len(lv) < MIN_DAYS * 2:
                rows.append({**row, "status": "INSUFFICIENT_DATA", "n_baseline_days": 0, "n_recent_days": len(lv)})
                continue
            cut_str = (pd.to_datetime(lv.index.max(), format="%Y%m%d") - pd.Timedelta(days=recent_days)).strftime(
                "%Y%m%d"
            )
            parts = {}
            for name, sel in (("b", lv.index < cut_str), ("r", lv.index >= cut_str)):
                parts[name] = (lv[sel & tgt].to_numpy(), lv[sel & ~tgt].to_numpy())
            # 対象日は月に数日しかないので、この本数が判定の律速になる。
            if min(len(parts["b"][0]), len(parts["r"][0])) < MIN_TARGET_DAYS:
                rows.append(
                    {
                        **row,
                        "status": "INSUFFICIENT_DATA",
                        "n_baseline_days": len(parts["b"][0]),
                        "n_recent_days": len(parts["r"][0]),
                    }
                )
                continue

            # 対象日は互いに10日前後離れており系列相関がほぼ無いので block=1。
            # 対照日は連日なので通常どおり block=BLOCK。
            def diff_boot(pair, seed):
                t, o = pair
                return block_bootstrap_means(t, seed=seed, block=1) - block_bootstrap_means(
                    o, seed=seed + 1, block=BLOCK
                )

            b_boot = diff_boot(parts["b"], 20260731)
            r_boot = diff_boot(parts["r"], 20260733)
            d_boot = r_boot - b_boot
            base = float(parts["b"][0].mean() - parts["b"][1].mean())
            recent = float(parts["r"][0].mean() - parts["r"][1].mean())
            n_base, n_rec = len(parts["b"][0]), len(parts["r"][0])
        else:
            s = daily_effect(df, metric, is_target)
            if len(s) < MIN_DAYS * 2:
                rows.append({**row, "status": "INSUFFICIENT_DATA", "n_baseline_days": 0, "n_recent_days": len(s)})
                continue

            cut = s.index.max()
            cut_dt = pd.to_datetime(cut, format="%Y%m%d") - pd.Timedelta(days=recent_days)
            cut_str = cut_dt.strftime("%Y%m%d")
            base_s = s[s.index < cut_str].to_numpy()
            rec_s = s[s.index >= cut_str].to_numpy()

            if len(base_s) < MIN_DAYS or len(rec_s) < MIN_DAYS:
                rows.append(
                    {**row, "status": "INSUFFICIENT_DATA", "n_baseline_days": len(base_s), "n_recent_days": len(rec_s)}
                )
                continue

            # 期間ごとに独立にリサンプルし、差の分布を作る。seed をずらすのは
            # 同じ乱数列で両期間を引くと差の分散を過小評価するため。
            b_boot = block_bootstrap_means(base_s, seed=20260723, block=BLOCK)
            r_boot = block_bootstrap_means(rec_s, seed=20260724, block=BLOCK)
            d_boot = r_boot - b_boot
            base, recent = float(base_s.mean()), float(rec_s.mean())
            n_base, n_rec = len(base_s), len(rec_s)

        base_ci, rec_ci, d_ci = _ci(b_boot), _ci(r_boot), _ci(d_boot)
        status = classify(base, base_ci, recent, rec_ci, d_ci)

        rows.append(
            {
                **row,
                "n_baseline_days": n_base,
                "n_recent_days": n_rec,
                "recent_from": cut_str,
                "baseline": round(base * scale, 4),
                "baseline_ci_lo": round(base_ci[0] * scale, 4),
                "baseline_ci_hi": round(base_ci[1] * scale, 4),
                "recent": round(recent * scale, 4),
                "recent_ci_lo": round(rec_ci[0] * scale, 4),
                "recent_ci_hi": round(rec_ci[1] * scale, 4),
                "delta": round((recent - base) * scale, 4),
                "delta_ci_lo": round(d_ci[0] * scale, 4),
                "delta_ci_hi": round(d_ci[1] * scale, 4),
                # 検出限界: この幅より小さい変化は今の窓では見分けられない
                "detect_limit": round((d_ci[1] - d_ci[0]) / 2 * scale, 4),
                "status": status,
            }
        )
    return rows


ALERT = {"DEAD", "REVERSED", "WEAKENED"}


def render(out: pd.DataFrame, recent_days: int, claims: list[dict]) -> str:
    notes = {c["claim_id"]: c for c in claims}
    lines = [
        "# 死亡検知ステータス",
        "",
        f"recent 窓: 直近 {recent_days} 日 / baseline: それ以前の全期間 / CI: 7日ブロックブートストラップ",
        "",
        "検定しているのは「効果がゼロか」ではなく **「過去水準から変わったか」**。",
        "`UNDERPOWERED` は「変わっていない」ではなく **「変化を見分けられない」** の意味。",
        "差枚は使っていない（回転数の混入を避けるため。FINDINGS 追試8）。",
        "",
    ]
    alerts = out[out["status"].isin(ALERT)]
    lines.append(f"## アラート: {len(alerts)} 件" if len(alerts) else "## アラート: なし")
    lines.append("")
    if len(alerts):
        for _, r in alerts.iterrows():
            lines.append(
                f"- **{r['status']}** `{r['claim_id']}` / {r['metric']}: "
                f"{r['baseline']:+.3f} → {r['recent']:+.3f} {r['unit']} "
                f"(差 {r['delta']:+.3f}, CI [{r['delta_ci_lo']:+.3f}, {r['delta_ci_hi']:+.3f}])"
            )
        lines.append("")

    lines += [
        "## 全結果",
        "",
        "| claim | 指標 | baseline | recent | 差 | 差CI | 検出限界 | 判定 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, r in out.iterrows():
        if r["status"] == "INSUFFICIENT_DATA":
            lines.append(
                f"| `{r['claim_id']}` | {r['metric']} | — | — | — | — | — | "
                f"INSUFFICIENT_DATA (n={r['n_recent_days']}) |"
            )
            continue
        lines.append(
            f"| `{r['claim_id']}` | {r['metric']} ({r['unit']}) | "
            f"{r['baseline']:+.3f} [{r['baseline_ci_lo']:+.3f}, {r['baseline_ci_hi']:+.3f}] | "
            f"{r['recent']:+.3f} [{r['recent_ci_lo']:+.3f}, {r['recent_ci_hi']:+.3f}] | "
            f"{r['delta']:+.3f} | [{r['delta_ci_lo']:+.3f}, {r['delta_ci_hi']:+.3f}] | "
            f"±{r['detect_limit']:.3f} | **{r['status']}** |"
        )

    lines += ["", "## 監視対象の由来", ""]
    for cid in out["claim_id"].unique():
        c = notes[cid]
        lines.append(f"- `{cid}` — {c['source']}" + (f"　※{c['note']}" if c.get("note") else ""))
    return "\n".join(lines) + "\n"


def main() -> None:
    # Windows の既定 cp932 では日本語や em dash を出力できず落ちる。
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="既知セオリーの死亡検知")
    ap.add_argument("--recent-days", type=int, default=90, help="直近何日を recent 窓とするか（既定 90）")
    ap.add_argument("--claim", action="append", help="claim_id を指定して絞る（複数可）")
    args = ap.parse_args()

    claims = load_claims()
    if args.claim:
        claims = [c for c in claims if c["claim_id"] in set(args.claim)]
        if not claims:
            raise SystemExit("該当する claim_id がない")

    rows: list[dict] = []
    for c in claims:
        rows.extend(evaluate(c, args.recent_days))
    out = pd.DataFrame(rows)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(RESULT_DIR / "status.csv", index=False, encoding="utf-8-sig")
    text = render(out, args.recent_days, claims)
    (RESULT_DIR / "STATUS.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
