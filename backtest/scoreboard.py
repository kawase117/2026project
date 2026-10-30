"""前向き検証の総合採点表: 凍結した予測が「無作為に座る」より良かったかを1枚にまとめる。

なぜ要るか:
    forward.py は事前登録ルールごとに選択を凍結し、翌朝 score で答え合わせする。
    juggler_carryover ledger も上位候補の当日成績を台帳に積む。しかし両方とも
    「1件ずつの結果」しか残さず、ルールを横断して
        - どれが無作為より有意に上か
        - どれが有害か
        - どれがまだ判定できず、あと何日要るか
    を一覧する場所が無かった。分析を増やしても意思決定の質が上がらないのはこのため
    (2026-10-16 ユーザーとの議論で最優先に置いた)。

何を比べるか:
    forward plan の result.mean_edge_per_pick は「選んだ台の当日差枚 − 同じ母集団の
    当日平均差枚」。母集団から無作為に選んだときの期待値は 0 なので、これがそのまま
    無作為選択に対する上積みになる。
    台×日を1単位にすると、同じ日の台どうしの相関(ホールの日の強弱)で標本数を
    水増しすることになるので、**ルール×日を1単位**にする。

区間と検定:
    - 95%CI は対象日を時系列に並べた 7日ブロック bootstrap(曜日の周期と
      週内の自己相関を壊さないため。いくつかの事前登録基準がこの方式を指定している)。
    - p 値は片側 t 検定(平均 > 0)。ルール横断で Benjamini-Hochberg 補正した q を出す。
      ルールが30本近くあるので、補正なしの p<0.05 は1〜2本が偶然で出る。
    - 判定は4区分。「差を検出できず」は効果ゼロの意味ではない
      (feedback: 非有意・小標本で効果なしと断定しない)。代わりに、観測したばらつきで
      +100枚/台の差を検出力80%で捉えるのに要る日数を出す。

差枚だけで判定しない:
    台単位の差枚は運の分散が大きく、設定の有無とは別物。RB で選ぶルールについては
    result.rb_perspective の baseline_ratio(当日の同条件台平均に対する RB 確率の比)を
    日平均して並べる。1.0 を有意に上回れば、差枚が出ていなくても設定は当たっている。

使い方:
    venv\\Scripts\\python.exe -m backtest.scoreboard            # 表示して backtest/forward/SCOREBOARD.{md,json} を更新
    venv\\Scripts\\python.exe -m backtest.scoreboard --no-write # 表示だけ
    venv\\Scripts\\python.exe -m backtest.scoreboard --since 20261001
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from scipy import stats

JST = ZoneInfo("Asia/Tokyo")
FORWARD_DIR = Path(__file__).resolve().parent / "forward"
JUGGLER_LEDGER_NAME = "juggler_carryover_ledger.jsonl"
PLAN_NAME = re.compile(r"^(?P<rule>.+)__(?P<date>\d{8})\.json$")

BLOCK_DAYS = 7
N_BOOT = 5000
SEED = 20261016
MIN_DAYS = 10  # これ未満は判定しない
Q_THRESHOLD = 0.10
RECENT_DAYS = 28  # 短期の法則にも価値がある(feedback)。直近だけの平均も並べる
Z_ALPHA = 1.6449  # 片側5%
Z_POWER = 0.8416  # 検出力80%
# 系列ごとの「検出したい差」。あと何日要るかの計算に使う。
MDE_TARGET = {
    "forward_edge": 100.0,
    "forward_rb": 0.10,
    "juggler_ph": 0.05,
    "pred_models": 100.0,
    "pred_avoid": 100.0,
    "pred_avoid_late": 100.0,
    "pred_vs_base": 100.0,
    "pred_units": 100.0,
    "pred_jug_units": 100.0,
    "rb_models": 0.05,
    "rb_avoid_models": 0.05,
    "rb_avoid_models_late": 0.05,
    "rb_units": 0.05,
    "rb_jug_units": 0.05,
    "rb1_units": 0.10,
    "rb1_jug_units": 0.10,
    "rbm_top": 0.03,
    "rbm_bottom": 0.03,
    "rbauto_units": 0.02,
    "rbdip_units": 0.02,
    "rbdip_ctrl_units": 0.02,
    "rbdip_diff": 0.02,
    "announce_named": 100.0,
    # 結果ツイートとの照合(%ポイント): 名指しが結果に入った割合 − 基準の割合
    "rc_units": 10.0,
    "rc_jug_units": 10.0,
    "rc_models": 10.0,
    "rc_avoid_models": 10.0,
}
PRED_DIR = Path(__file__).resolve().parent / "predictions"
ANNOUNCE_DIR = Path(__file__).resolve().parent / "announce"
# 予測台帳の result のキー → 採点表の系列
PRED_FAMILIES = {
    "models": "pred_models",
    "avoid_models": "pred_avoid",
    "units": "pred_units",
    "jug_units": "pred_jug_units",
}
RB_PRED_FAMILIES = {key: f"rb_{key}" for key in ("models", "avoid_models", "units", "jug_units")}
RB1_PRED_FAMILIES = {key: f"rb1_{key}" for key in ("units", "jug_units")}
# 「避ける」は開店前に凍結したものだけが事前の判断。当日・事後に書いたものは結果を見てから書けるので別系列にする。
LATE_SUFFIX = "_late"
# 手書きの推しと比べる機械的な基準(直近60日の機種平均上位3)。forward の rule_id の末尾。
BASE_RULE_SUFFIX = "_model_term60_top3"
# 結果ツイートとの照合の記録(scripts/result_check.py)。差枚とは別の、台単位の正解。
RESULT_CHECKS = Path(__file__).resolve().parents[1] / "document" / "registry" / "RESULT_CHECKS.jsonl"
# 照合の採点ラベル → 系列の名前。改訂版(revN)は人の初版と重なるので数えない。
RC_SOURCES = {"人の予測": "人", "RB自動候補": "RB自動", "凹み戻り": "凹み戻り", "凹み戻りの対照": "凹み戻りの対照"}
# 11月の検証計画の「4ホール合計」に入れるホール(2026-10 月次振り返り 5節)。
CORE_HALLS = ("楽園蒲田店", "みとや大森町店", "マルハンメガシティ2000-蒲田7", "マルハンメガシティ2000-蒲田1")
CORE_LABEL = "4ホール合計"
TIMING_ORDER = ("pre_open", "same_day", "after")


@dataclass
class Stat:
    n_days: int
    mean: float | None
    ci_lo: float | None
    ci_hi: float | None
    p_one_sided: float | None
    share_positive: float | None
    sd: float | None
    q: float | None = None


@dataclass
class Row:
    family: str  # "forward_edge" / "forward_rb" / "juggler_ph"
    key: str
    hall: str
    label: str
    first_date: str
    last_date: str
    stat: Stat
    recent_mean: float | None
    recent_n: int
    verdict: str = ""
    days_needed: int | None = None
    criterion: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 統計


def block_bootstrap_ci(values: list[float], block: int = BLOCK_DAYS, n_boot: int = N_BOOT, seed: int = SEED):
    """時系列順の値について、長さ block の連続ブロックを復元抽出して平均の95%CIを返す。"""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2:
        return None, None
    # ブロックが標本に対して長すぎると取り方が数通りしかなく、CI が平均に潰れる
    # (n=3 で block=3 なら1通り)。ブロックが3つ以上取れるまで短くする。
    b = max(1, min(block, n // 3))
    starts = np.arange(n - b + 1)
    n_blocks = math.ceil(n / b)
    rng = np.random.default_rng(seed)
    picks = rng.choice(starts, size=(n_boot, n_blocks))
    idx = (picks[:, :, None] + np.arange(b)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def summarize(values: list[float]) -> Stat:
    x = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    n = len(x)
    if n == 0:
        return Stat(0, None, None, None, None, None, None)
    arr = np.asarray(x)
    sd = float(arr.std(ddof=1)) if n >= 2 else None
    lo, hi = block_bootstrap_ci(x)
    p = None
    if n >= 3 and sd and sd > 0:
        p = float(stats.ttest_1samp(arr, 0.0, alternative="greater").pvalue)
    return Stat(n, float(arr.mean()), lo, hi, p, float((arr > 0).mean()), sd)


def benjamini_hochberg(pvalues: list[float | None]) -> list[float | None]:
    idx = [i for i, p in enumerate(pvalues) if p is not None]
    out: list[float | None] = [None] * len(pvalues)
    m = len(idx)
    order = sorted(idx, key=lambda i: pvalues[i])
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvalues[i] * m / rank)
        out[i] = running
    return out


def days_needed(sd: float | None, target: float) -> int | None:
    if not sd:
        return None
    return int(math.ceil(((Z_ALPHA + Z_POWER) * sd / target) ** 2))


def verdict(stat: Stat) -> str:
    if stat.n_days < MIN_DAYS:
        return "標本不足"
    if stat.q is not None and stat.q < Q_THRESHOLD and stat.ci_lo is not None and stat.ci_lo > 0:
        return "有効"
    if stat.ci_hi is not None and stat.ci_hi < 0:
        return "有害"
    return "差を検出できず"


# ---------------------------------------------------------------- 読み込み


CRITERION_EDGE = re.compile(r"\+\s*(\d+)\s*枚")


def load_plans(forward_dir: Path, since: str | None = None) -> list[dict]:
    """採点済みの本番 plan だけを返す。invalidated/ 配下(glob が潜らない)・dry run・未採点は除く。"""
    plans = []
    for path in sorted(forward_dir.glob("*__*.json")):
        m = PLAN_NAME.match(path.name)
        if not m:
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if obj.get("is_dry_run") or not obj.get("result"):
            continue
        target = obj.get("target_date") or m.group("date")
        if since and target < since:
            continue
        obj.setdefault("rule_id", m.group("rule"))
        obj["target_date"] = target
        plans.append(obj)
    return plans


def load_juggler_ledger(forward_dir: Path, since: str | None = None) -> list[dict]:
    path = forward_dir / JUGGLER_LEDGER_NAME
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if since and r["date"] < since:
            continue
        if r.get("top_ph") is None or r.get("rest_ph") is None:
            continue
        rows.append(r)
    return rows


# ---------------------------------------------------------------- 集計


def _recent(series: list[tuple[str, float]]) -> tuple[float | None, int]:
    if not series:
        return None, 0
    last = datetime.strptime(series[-1][0], "%Y%m%d")
    cutoff = (last - timedelta(days=RECENT_DAYS - 1)).strftime("%Y%m%d")
    vals = [v for d, v in series if d >= cutoff]
    return float(np.mean(vals)), len(vals)


def _rb_ratio_of_day(result: dict) -> float | None:
    """選んだ台の当日RB確率 ÷ 同条件台平均 の日平均から 1 を引いた値(無作為なら 0)。"""
    rbp = result.get("rb_perspective") or {}
    ratios = [p["baseline_ratio"] for p in rbp.get("picks_rb", []) if p.get("baseline_ratio") is not None]
    return float(np.mean(ratios)) - 1.0 if ratios else None


def _row(family, key, hall, label, series, **kw) -> Row:
    stat = summarize([v for _, v in series])
    recent, recent_n = _recent(series)
    return Row(family, key, hall, label, series[0][0], series[-1][0], stat, recent, recent_n, **kw)


def build_forward_rows(plans: list[dict]) -> list[Row]:
    by_rule: dict[str, list[dict]] = {}
    for p in plans:
        by_rule.setdefault(p["rule_id"], []).append(p)

    rows: list[Row] = []
    for rule, items in sorted(by_rule.items()):
        items.sort(key=lambda p: p["target_date"])
        hall = items[-1].get("hall", "")
        edge_series = [
            (p["target_date"], p["result"]["mean_edge_per_pick"])
            for p in items
            if p["result"].get("mean_edge_per_pick") is not None
        ]
        rb_series = [(p["target_date"], v) for p in items if (v := _rb_ratio_of_day(p["result"])) is not None]
        criterion = items[-1].get("success_criterion")
        m = CRITERION_EDGE.search(criterion) if criterion else None
        win = [r["diff"] > 0 for p in items for r in p["result"].get("picks_realized", []) if r.get("diff") is not None]
        extra = {
            "n_plans": len(items),
            "n_stale_data_days": sum(1 for p in items if (p.get("data_lag_days") or 0) >= 2),
            "pick_win_rate": round(float(np.mean(win)), 3) if win else None,
            "n_machine_days": len(win),
            "criterion_edge": int(m.group(1)) if m else None,
        }
        if edge_series:
            rows.append(_row("forward_edge", rule, hall, rule, edge_series, criterion=criterion, extra=extra))
        if rb_series:
            rows.append(_row("forward_rb", rule, hall, rule, rb_series))
    return rows


def build_juggler_rows(ledger: list[dict]) -> list[Row]:
    groups: dict[tuple[str, str], dict[str, list[float]]] = {}
    for r in ledger:
        groups.setdefault((r["hall"], r["model"]), {}).setdefault(r["date"], []).append(r["top_ph"] - r["rest_ph"])
    rows = []
    for (hall, model), by_date in sorted(groups.items()):
        series = [(d, float(np.mean(v))) for d, v in sorted(by_date.items())]
        rows.append(_row("juggler_ph", f"{hall}/{model}", hall, model, series))
    return rows


def load_predictions(pred_dir: Path, since: str | None = None) -> list[dict]:
    """予測文書の台帳(backtest.prediction_ledger)のうち採点済みのもの。"""
    out = []
    for path in sorted(pred_dir.glob("*__*.json")) if pred_dir.exists() else []:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if obj.get("result") and not (since and obj["target_date"] < since):
            out.append(obj)
    return out


def build_prediction_rows(preds: list[dict]) -> list[Row]:
    """ホール×名指しの種類ごとに、1日1値(edge)の系列を作る。"""
    groups: dict[tuple[str, str], list[tuple[str, float, str]]] = {}
    for p in preds:
        if p.get("source") == "rb_auto":
            machine = p["result"].get("rb_machine") or {}
            for key, family, sign in (("top", "rbm_top", 1), ("bottom", "rbm_bottom", -1)):
                part = machine.get(key) or {}
                if part.get("edge") is not None:
                    groups.setdefault((family, p["hall"]), []).append(
                        (p["target_date"], sign * part["edge"], p["timing"])
                    )
            units = (p["result"].get("rb_s1") or {}).get("units") or {}
            if units.get("rb_s1_edge") is not None:
                groups.setdefault(("rbauto_units", p["hall"]), []).append(
                    (p["target_date"], units["rb_s1_edge"], p["timing"])
                )
            continue
        if p.get("source") in ("rb_dip", "rb_dip_ctrl"):
            # 凹み戻り(自動)は人の判断・rb_auto の系列に混ぜない。値は台の設定1比の差(同日・同機種の非選択台との差)。
            family = "rbdip_units" if p["source"] == "rb_dip" else "rbdip_ctrl_units"
            units = (p["result"].get("rb_s1") or {}).get("units") or {}
            if units.get("rb_s1_edge") is not None:
                groups.setdefault((family, p["hall"]), []).append((p["target_date"], units["rb_s1_edge"], p["timing"]))
            continue
        late = LATE_SUFFIX if p.get("timing") != "pre_open" else ""
        for key, family in PRED_FAMILIES.items():
            part = p["result"].get(key)
            if part and part.get("edge") is not None:
                if key == "avoid_models":
                    family += late
                if "revision_of" in p:
                    family = f"{family}[{p['revision']}]"
                groups.setdefault((family, p["hall"]), []).append((p["target_date"], part["edge"], p["timing"]))
        rb = p["result"].get("rb") or {}
        for key, family in RB_PRED_FAMILIES.items():
            part = rb.get(key)
            if part and part.get("rb_edge") is not None:
                if key == "avoid_models":
                    family += late
                if "revision_of" in p:
                    family = f"{family}[{p['revision']}]"
                edge = part["rb_edge"] * (-1 if key == "avoid_models" else 1)
                groups.setdefault((family, p["hall"]), []).append((p["target_date"], edge, p["timing"]))
        rb_s1 = p["result"].get("rb_s1") or {}
        for key, family in RB1_PRED_FAMILIES.items():
            part = rb_s1.get(key)
            if part and part.get("rb_s1_edge") is not None:
                if "revision_of" in p:
                    family = f"{family}[{p['revision']}]"
                groups.setdefault((family, p["hall"]), []).append((p["target_date"], part["rb_s1_edge"], p["timing"]))
    # 凹み戻りの増分: 同じ (ホール, 対象日) に凹み(A)と対照(B)の両方の値がある日だけ A − B を1値にする。
    ctrl = {
        (hall, date): value
        for (family, hall), items in groups.items()
        if family == "rbdip_ctrl_units"
        for date, value, _ in items
    }
    for (family, hall), items in list(groups.items()):
        if family != "rbdip_units":
            continue
        for date, value, timing_ in items:
            if (hall, date) in ctrl:
                groups.setdefault(("rbdip_diff", hall), []).append((date, value - ctrl[(hall, date)], timing_))
    rows = []
    for (family, hall), items in sorted(groups.items()):
        items.sort()
        timing = {t: sum(1 for *_, x in items if x == t) for t in ("pre_open", "same_day", "after")}
        rows.append(
            _row(family, f"{family}/{hall}", hall, hall, [(d, v) for d, v, _ in items], extra={"timing": timing})
        )
    return rows


def build_vs_base_rows(preds: list[dict], plans: list[dict]) -> list[Row]:
    """手書きで推した機種の edge − 同じホール・同じ日の基準(model_term60_top3)の edge。

    両方の edge は「名指しした台の平均差枚 − ホールの当日全台平均」で同じ定義なので、差がそのまま
    手書きの上積みになる。人の予測文書の初版だけを使う(自動凍結・改訂版は除く)。
    ホール別の行に加え、CORE_HALLS の日平均を「4ホール合計」の1行にする(同じ日のホールは独立でないため)。
    """
    base = {
        (p["hall"], p["target_date"]): p["result"]["mean_edge_per_pick"]
        for p in plans
        if p["rule_id"].endswith(BASE_RULE_SUFFIX) and p["result"].get("mean_edge_per_pick") is not None
    }
    groups: dict[str, list[tuple[str, float, float, float, str]]] = {}
    for p in preds:
        if p.get("source") or "revision_of" in p:
            continue
        part = p["result"].get("models") or {}
        b = base.get((p["hall"], p["target_date"]))
        if part.get("edge") is None or b is None:
            continue
        groups.setdefault(p["hall"], []).append((p["target_date"], part["edge"] - b, part["edge"], b, p["timing"]))
    core: dict[str, list[tuple[float, float, float, str]]] = {}
    for hall in CORE_HALLS:
        for d, diff, own, b, t in groups.get(hall, []):
            core.setdefault(d, []).append((diff, own, b, t))
    if core:
        groups[CORE_LABEL] = [
            # 事前性は、その日のホールのうち最も遅いものにそろえる
            (d, *(float(np.mean([x[i] for x in v])) for i in range(3)), max((x[3] for x in v), key=TIMING_ORDER.index))
            for d, v in core.items()
        ]
    rows = []
    for hall, items in sorted(groups.items()):
        items.sort()
        timing = {t: sum(1 for *_, x in items if x == t) for t in ("pre_open", "same_day", "after")}
        extra = {
            "timing": timing,
            "own_mean": round(float(np.mean([x[2] for x in items])), 1),
            "base_mean": round(float(np.mean([x[3] for x in items])), 1),
        }
        rows.append(
            _row("pred_vs_base", f"pred_vs_base/{hall}", hall, hall, [(d, v) for d, v, *_ in items], extra=extra)
        )
    return rows


def _announce_superseded(path: Path) -> bool:
    stem = path.name[: -len(".json")]
    return (path.parent / f"{stem}.withdrawn.json").exists() or (path.parent / f"{stem}__v2.json").exists()


def load_announcements(announce_dir: Path, since: str | None = None) -> list[dict]:
    """採点済みの予告。撤回・差し替え・遡及登録の版は除く(scripts/run_morning.py と同じ基準)。"""
    out = []
    for path in sorted(announce_dir.glob("*__*.json")) if announce_dir.exists() else []:
        if path.name.endswith(".withdrawn.json") or _announce_superseded(path):
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if not obj.get("result") or obj.get("retroactive") or (since and obj.get("target_date", "") < since):
            continue
        out.append(obj)
    return out


def build_announce_rows(announcements: list[dict]) -> list[Row]:
    """予告アカウント×ホールごとに、名指し機種の台平均 − ホールの台平均 を1予告1値で並べる。

    機種平均を機種間で単純平均せず、台数で重みづけする(forward の model_perspective と同じ理由)。
    あわせて閾値超え(hit)の実数と、機種の年齢別ベースレートから見た期待数を残す。
    """
    groups: dict[tuple[str, str], list[tuple[str, float]]] = {}
    hits: dict[tuple[str, str], list[float]] = {}
    for a in announcements:
        res = a["result"]
        base = res.get("hall_baseline_mean_diff")
        named = [
            c
            for c in res.get("claims", [])
            if c.get("type") == "model_named" and c.get("mean_diff") is not None and c.get("n_machines")
        ]
        if base is None or not named:
            continue
        n = sum(c["n_machines"] for c in named)
        edge = sum(c["mean_diff"] * c["n_machines"] for c in named) / n - base
        key = ((a.get("source") or {}).get("account") or "?", a["hall"])
        groups.setdefault(key, []).append((a["target_date"], edge))
        h = hits.setdefault(key, [0, 0.0, 0])
        for c in named:
            if c.get("hit") is not None and c.get("base_rate") is not None:
                h[0] += int(c["hit"])
                h[1] += float(c["base_rate"])
                h[2] += 1
    rows = []
    for (account, hall), items in sorted(groups.items()):
        # 同じアカウントが同じ日に複数投稿した場合は日平均にする(1単位=アカウント×ホール×日)
        by_date: dict[str, list[float]] = {}
        for d, v in items:
            by_date.setdefault(d, []).append(v)
        series = [(d, float(np.mean(v))) for d, v in sorted(by_date.items())]
        h = hits[(account, hall)]
        extra = {"hits": h[0], "expected_hits": round(h[1], 1), "n_named_scored": h[2]}
        rows.append(_row("announce_named", f"{account}/{hall}", hall, account, series, extra=extra))
    return rows


def load_result_checks(path: Path = RESULT_CHECKS, since: str | None = None) -> list[dict]:
    """照合の記録。同じ (ホール, 営業日) は最後の記録だけを使う(結果が後から増えると追記されるため)。"""
    if not path.exists():
        return []
    latest: dict[tuple[str, str], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("status") != "linked" or (since and rec["business_date"] < since):
            continue
        latest[(rec["hall"], rec["business_date"])] = rec
    return [latest[k] for k in sorted(latest)]


def build_result_check_rows(checks: list[dict]) -> list[Row]:
    """名指しが結果ツイートに入った割合 − 基準の割合(%ポイント)。避ける機種は符号を反転(入らないほど正)。

    基準は、台なら名指しした台と同じ機種の台のうち結果に入った割合、機種なら当日の全機種のうち結果のある割合。
    結果ツイートはジャグラーなど一部の機種に偏るので、その偏りを差し引く。基準の無い記録(旧形式)は使わない。
    """
    groups: dict[tuple[str, str, str], list[tuple[str, float]]] = {}
    for rec in checks:
        for label, scores in (rec.get("scores") or {}).items():
            src = RC_SOURCES.get(label)
            if not src:
                continue
            for kind, part in (scores or {}).items():
                if part.get("base") is None or not part.get("named"):
                    continue
                share = len(part["hit"]) / part["named"]
                value = (part["base"] - share) if kind == "avoid_models" else (share - part["base"])
                groups.setdefault((f"rc_{kind}", src, rec["hall"]), []).append((rec["business_date"], 100 * value))
    rows = []
    for (family, src, hall), series in sorted(groups.items()):
        series.sort()
        rows.append(_row(family, f"{family}/{src}/{hall}", hall, src, series))
    return rows


def finalize(rows: list[Row]) -> list[Row]:
    """系列(family)ごとに BH 補正し、判定と「あと何日」を埋める。"""
    for family in sorted({r.family for r in rows}):
        members = [r for r in rows if r.family == family]
        qs = benjamini_hochberg([r.stat.p_one_sided for r in members])
        for r, q in zip(members, qs, strict=True):
            r.stat.q = q
            r.verdict = verdict(r.stat)
            if r.verdict in ("差を検出できず", "標本不足"):
                need = days_needed(r.stat.sd, MDE_TARGET[family.split("[", 1)[0]])
                r.days_needed = None if need is None else max(need - r.stat.n_days, 0)
    return rows


def build(
    forward_dir: Path = FORWARD_DIR,
    since: str | None = None,
    pred_dir: Path = PRED_DIR,
    announce_dir: Path = ANNOUNCE_DIR,
    result_checks: Path = RESULT_CHECKS,
) -> list[Row]:
    plans = load_plans(forward_dir, since)
    preds = load_predictions(pred_dir, since)
    rows = build_forward_rows(plans)
    rows += build_juggler_rows(load_juggler_ledger(forward_dir, since))
    rows += build_prediction_rows(preds)
    rows += build_vs_base_rows(preds, plans)
    rows += build_announce_rows(load_announcements(announce_dir, since))
    rows += build_result_check_rows(load_result_checks(result_checks, since))
    return finalize(rows)


# ---------------------------------------------------------------- 出力

VERDICT_ORDER = {"有効": 0, "有害": 1, "差を検出できず": 2, "標本不足": 3}


def _f(v, fmt):
    return "—" if v is None else format(v, fmt)


def _forward_cols(r: Row) -> str:
    ce = r.extra.get("criterion_edge")
    return f" {_f(r.extra.get('pick_win_rate'), '.0%')} | {'+%d枚' % ce if ce else '—'} |"


def _timing_cols(r: Row) -> str:
    t = r.extra.get("timing", {})
    return f" {t.get('pre_open', 0)}/{t.get('same_day', 0)}/{t.get('after', 0)} |"


def _announce_cols(r: Row) -> str:
    e = r.extra
    return f" {e.get('hits', 0)} / {_f(e.get('expected_hits'), '.1f')} ({e.get('n_named_scored', 0)}件) |"


def _vs_base_cols(r: Row) -> str:
    e = r.extra
    return f" {_f(e.get('own_mean'), '+.0f')} | {_f(e.get('base_mean'), '+.0f')} |" + _timing_cols(r)


# 2026-10 月次振り返り(document/reviews/2026-10-monthly-retrospective.md)5節の11月検証計画 → 判定に使う表
PLAN_MAP = (
    (
        "手書きの推し − 基準",
        f"4a の「{CORE_LABEL}」が正、かつ楽園・みとやの行が正",
        "4a。RB判別機の推しは「予測文書RB: 推した機種」も併読",
    ),
    (
        "開店前の「避ける」",
        "平均edgeが正",
        "5(開店前の凍結のみ)と「予測文書RB: 避ける機種・開店前の凍結」。5b は数えない",
    ),
    (
        "ジャグラー候補(みとや)",
        "差枚edgeの95%CI下限 > 0 を維持",
        "7 のみとやの行。RB比は「予測文書RB(設定1比): ジャグラー候補表の台」",
    ),
    ("ジャグラー候補(楽園)", "差を検出、または平均 > +100", "7 の楽園の行と、RB(設定1比)のジャグラー候補表の楽園の行"),
    (
        "凍結前点検の警告件数",
        "月の後半で前半より減る",
        "この採点表の外。学びの台帳(document/registry/LESSONS.jsonl)の月次集計で見る",
    ),
)


def _plan_map() -> list[str]:
    out = [
        "## 11月の検証計画と判定に使う表",
        "",
        "| 項目 | 合格の基準 | 判定に使う表 |",
        "|---|---|---|",
    ]
    out += [f"| {a} | {b} | {c} |" for a, b, c in PLAN_MAP]
    return out + [""]


def _section(out, rows, family, title, unit, fmt, note, extra_head=None, extra_cols=None, key_head="ルール"):
    members = sorted(
        (r for r in rows if r.family == family),
        key=lambda r: (VERDICT_ORDER.get(r.verdict, 9), -(r.stat.mean if r.stat.mean is not None else -1e9)),
    )
    if not members:
        return
    counts: dict[str, int] = {}
    for r in members:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    out += [
        f"## {title}",
        "",
        note,
        "",
        "内訳: " + " / ".join(f"{k} {counts[k]}" for k in VERDICT_ORDER if k in counts),
        "",
    ]
    head = f"| 判定 | {key_head} | ホール | 日数 | 平均{unit} | 95%CI | 正の日 | q | 直近{RECENT_DAYS}日(日数) | あと何日 |"
    sep = "|---|---|---|---:|---:|---|---:|---:|---:|---:|"
    if extra_head:
        head += "".join(f" {h} |" for h in extra_head)
        sep += "---:|" * len(extra_head)
    out += [head, sep]
    for r in members:
        s = r.stat
        line = (
            f"| {r.verdict} | {r.label} | {r.hall} | {s.n_days} | {_f(s.mean, fmt)} | "
            f"{_f(s.ci_lo, fmt)} 〜 {_f(s.ci_hi, fmt)} | {_f(s.share_positive, '.0%')} | {_f(s.q, '.3f')} | "
            f"{_f(r.recent_mean, fmt)} ({r.recent_n}) | {_f(r.days_needed, 'd')} |"
        )
        if extra_cols:
            line += extra_cols(r)
        out.append(line)
    out.append("")


def render_markdown(rows: list[Row], generated_at: str, since: str | None) -> str:
    out = [
        "# 前向き検証 総合採点表",
        "",
        f"生成 {generated_at}(`python -m backtest.scoreboard`、毎朝 run_morning が更新)"
        + (f" / 集計開始 {since}" if since else ""),
        "",
        "**読み方**: 1単位=ルール×日。平均は「選んだ台 − 同じ母集団の当日平均」で、無作為に座った場合が 0。"
        f"95%CIは{BLOCK_DAYS}日ブロックbootstrap、qは系列ごとのルール横断BH補正。"
        f"判定: **有効**=q<{Q_THRESHOLD:.2f}かつCI下限>0 / **有害**=CI上限<0 / "
        f"**差を検出できず**=どちらでもない(効果ゼロの意味ではない) / **標本不足**={MIN_DAYS}日未満。"
        "「あと何日」は観測したばらつきで目標差を検出力80%・片側5%で捉えるのに要る追加日数。",
        "",
        "**RB判別機(ジャグラー・ハナハナ・ディスクアップなど)は、月次はRB比の表で判定し、差枚の表は3か月単位で見る。**"
        "差枚は運の分散が大きく、1か月では差を検出できないことが多い。RB比は設定の有無に直結し、1か月で判定に届く。",
        "",
        "**「避ける」は開店前に凍結したものだけを判断の成績として読む。** 当日・事後に書いた「避ける」は結果を見てから"
        "書けるので、別の表(当日・事後)に分けた。",
        "",
    ]
    out += _plan_map()
    _section(
        out,
        rows,
        "forward_edge",
        "1. 事前登録ルール: 差枚エッジ(枚/台)",
        "(枚)",
        "+.0f",
        f"目標差 +{MDE_TARGET['forward_edge']:.0f}枚/台。台の勝率は差枚>0の台の割合"
        "(母集団の勝率と比べていない記述統計)。事前基準は success_criterion から拾った最初の「+N枚」で、"
        "照合は本文で行うこと。",
        extra_head=["台の勝率", "事前基準"],
        extra_cols=_forward_cols,
    )
    _section(
        out,
        rows,
        "forward_rb",
        "2. 事前登録ルール: 当日RB確率の比(設定シグナル、RB選出ルールのみ)",
        "(比−1)",
        "+.2f",
        "選んだ台の当日RB確率 ÷ 同条件台の当日平均 − 1。差枚が出ていなくてもここが正なら設定は当たっている。"
        f"目標差 +{MDE_TARGET['forward_rb']:.2f}。",
    )
    _section(
        out,
        rows,
        "juggler_ph",
        "3. ジャグラー持ち越し候補: 上位10台の当日ph − 同機種の残り",
        "(ph差)",
        "+.3f",
        f"phは当日の高設定確率の推定。目標差 +{MDE_TARGET['juggler_ph']:.2f}。",
    )
    pred_note = (
        "予測文書(document/reviews/*-prediction.md)から backtest.prediction_ledger が機械的に抜き出した名指し。"
        "edge は名指しした台(機種なら全台)の平均差枚 − そのホールの当日全台平均。"
        "事前性は 開店前/当日中/事後 の件数(事後=git の初出コミットが翌日以降で、事前に書いたことを証明できないもの)。"
    )
    _section(
        out,
        rows,
        "pred_vs_base",
        "4a. 予測文書: 手書きの推し − 基準(model_term60_top3)",
        "(枚)",
        "+.0f",
        "同じホール・同じ日の「手書きで推した機種のedge − 基準(直近60日の機種平均上位3)のedge」。"
        "正なら手書きが基準に上積みしている。人の予測文書の初版だけを使い、改訂版・自動凍結は除く。"
        f"「{CORE_LABEL}」は{'・'.join(CORE_HALLS)}の日平均を1日1値にしたもの。"
        "手書き・基準の列は、比べた日だけの平均。",
        extra_head=["手書き", "基準", "事前性 開店前/当日/事後"],
        extra_cols=_vs_base_cols,
        key_head="対象",
    )
    for family, title in (
        ("pred_models", "4. 予測文書: 推した機種(枚/台)"),
        ("pred_avoid", "5. 予測文書: 避けると書いた機種・開店前の凍結(全台平均 − 機種平均。正なら避けて正解)"),
        ("pred_avoid_late", "5b. 予測文書: 避けると書いた機種・当日/事後に書いたもの(判断の成績には数えない)"),
        ("pred_units", "6. 予測文書: 判断で名指しした台"),
        ("pred_jug_units", "7. 予測文書: ジャグラー候補表の台"),
    ):
        _section(
            out,
            rows,
            family,
            title,
            "(枚)",
            "+.0f",
            pred_note,
            extra_head=["事前性 開店前/当日/事後"],
            extra_cols=_timing_cols,
            key_head="対象",
        )
    for family, title in (
        ("rb_models", "予測文書RB: 推した機種"),
        ("rb_avoid_models", "予測文書RB: 避ける機種・開店前の凍結"),
        ("rb_avoid_models_late", "予測文書RB: 避ける機種・当日/事後に書いたもの"),
        ("rb_units", "予測文書RB: 判断で名指しした台"),
        ("rb_jug_units", "予測文書RB: ジャグラー候補表の台"),
    ):
        _section(
            out,
            rows,
            family,
            title,
            "(RB比の差)",
            "+.3f",
            "機種の過去60日RB率に対する当日RB比から、当日の判別機種全体のRB比を引く。"
            "避ける機種は符号を反転。目標差 +0.05（5ポイント）。",
            extra_head=["事前性 開店前/当日/事後"],
            extra_cols=_timing_cols,
            key_head="対象",
        )
    for family, title in (
        ("rb1_units", "予測文書RB(設定1比): 判断で名指しした台"),
        ("rb1_jug_units", "予測文書RB(設定1比): ジャグラー候補表の台"),
    ):
        _section(
            out,
            rows,
            family,
            title,
            "(設定1比の差)",
            "+.3f",
            f"同日・同ホール・同機種の非選択台との差。期待RB回数で機種を重みづけ。目標差 +{MDE_TARGET[family]:.2f}。",
            extra_head=["事前性 開店前/当日/事後"],
            extra_cols=_timing_cols,
            key_head="対象",
        )
    for family, title in (
        ("rbm_top", "RB機種候補(自動): 上位機種"),
        ("rbm_bottom", "RB機種候補(自動): 下位機種"),
        ("rbauto_units", "RB機種候補(自動): 台の補助"),
        ("rbdip_units", "凹み戻り(自動): 凹んだ台"),
        ("rbdip_ctrl_units", "凹み戻り(自動): 対照(好調な台)"),
        ("rbdip_diff", "凹み戻り(自動): 凹み − 対照"),
    ):
        _section(
            out,
            rows,
            family,
            title,
            "(RB差)",
            "+.3f",
            f"開店前に自動凍結した候補。目標差 +{MDE_TARGET[family]:.2f}。",
            extra_head=["事前性 開店前/当日/事後"],
            extra_cols=_timing_cols,
        )
    _section(
        out,
        rows,
        "announce_named",
        "8. 予告の名指し機種(アカウント×ホール)",
        "(枚)",
        "+.0f",
        "予告で名指しされた機種(model_named)の台平均差枚 − ホールの当日台平均。台数で重みづけ。"
        "撤回・差し替え・遡及登録の版は除く。判定は差枚の上積み(日の強さを差し引いた値)で行う。"
        "閾値超えの「期待」は機種の年齢別ベースレートの合計で、**日を条件づけていない**。予告が出る日はホール全体が強いので"
        "実数が期待を大きく上回って見えるが、それは名指しの力ではなく日の力を含む(feedback: named-model-conditional-baserate)。"
        "自動下ごしらえで本文から拾った claim を含むので、名指しの読み違いも混ざる。",
        extra_head=["閾値超え 実/期待"],
        extra_cols=_announce_cols,
        key_head="アカウント",
    )
    for family, title in (
        ("rc_units", "9. 結果ツイートとの照合: 判断で名指しした台"),
        ("rc_jug_units", "9. 結果ツイートとの照合: ジャグラー候補表の台"),
        ("rc_models", "9. 結果ツイートとの照合: 推した機種"),
        ("rc_avoid_models", "9. 結果ツイートとの照合: 避ける機種(入らないほど正)"),
    ):
        _section(
            out,
            rows,
            family,
            title,
            "(pt)",
            "+.1f",
            "発信者が結果として挙げた台(ホール公表とは限らない)に名指しが入った割合 − 基準の割合、%ポイント。"
            "台の基準は同じ機種の台のうち結果に入った割合、機種の基準は当日の全機種のうち結果のある割合。"
            "機種は結果の台が1台でもあれば的中と数える。結果ツイートが出た日だけの系列で、出ない日は数えない"
            f"(出る日は強い日に偏る)。目標差 +{MDE_TARGET[family]:.0f}pt。",
            key_head="予測",
        )
    out += [
        "## 注意",
        "",
        "- 同じホール・同じ日の複数ルールは独立ではない。本数を独立な証拠として数えないこと。",
        "- 予測文書の抽出は機械的。古い書式(「判断」の節が無い文書)はほとんど抜けない。"
        "照合できなかった語は backtest/predictions/*.json の unresolved に残る。",
        "- data_lag_days≥2(古いデータで凍結した日)も含む。件数は SCOREBOARD.json の extra.n_stale_data_days。",
        "",
    ]
    return "\n".join(out)


def to_json(rows: list[Row], generated_at: str, since: str | None) -> dict:
    return {
        "generated_at": generated_at,
        "since": since,
        "params": {
            "block_days": BLOCK_DAYS,
            "n_boot": N_BOOT,
            "seed": SEED,
            "min_days": MIN_DAYS,
            "q_threshold": Q_THRESHOLD,
            "recent_days": RECENT_DAYS,
            "mde_target": MDE_TARGET,
        },
        "rows": [asdict(r) for r in rows],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="この日以降の対象日だけで集計する (YYYYMMDD)")
    parser.add_argument("--no-write", action="store_true", help="SCOREBOARD.md / .json を書き出さない")
    parser.add_argument("--forward-dir", default=str(FORWARD_DIR))
    args = parser.parse_args(argv)

    forward_dir = Path(args.forward_dir)
    rows = build(forward_dir, args.since, PRED_DIR, ANNOUNCE_DIR)
    generated_at = datetime.now(JST).isoformat(timespec="seconds")
    md = render_markdown(rows, generated_at, args.since)
    print(md)
    if not args.no_write:
        (forward_dir / "SCOREBOARD.md").write_text(md, encoding="utf-8")
        (forward_dir / "SCOREBOARD.json").write_text(
            json.dumps(to_json(rows, generated_at, args.since), ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"\n→ {forward_dir / 'SCOREBOARD.md'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
