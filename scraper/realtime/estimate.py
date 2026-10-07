"""当日スナップショットのRB事後確率とAT参考スコア。"""

import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from backtest.bonus_specs import find_spec, load_specs, posterior
from .adapters.common import model_name
from .quick_filter import load_audit
from .schema import SnapshotRow

ROOT = Path(__file__).resolve().parents[2]
LOW_RB_RATIO = 1.25  # 高低間の最大RB確率比がこれ未満なら低判別力
NEW_MACHINE_DAYS = 7
EARLY_GAMES = 3000
SMALL_GAMES = 1000


def _entropy(probs):
    return -sum(p * math.log(p) for p in probs if p > 0)


def _prior(settings, hall, hall_prior):
    supplied = (
        hall_prior.get(hall)
        if isinstance(hall_prior, dict) and any(isinstance(k, str) for k in hall_prior)
        else hall_prior
    )
    weights = {s: float(supplied.get(s, 0)) if supplied else 1.0 for s in settings}
    total = sum(weights.values())
    if total <= 0 or any(v < 0 for v in weights.values()):
        raise ValueError("hall_prior must contain nonnegative weights with positive sum")
    return {s: v / total for s, v in weights.items()}


def _model(row):
    return row.model or model_name(row.model_raw)


def _none(reason):
    return {
        "p_high": None,
        "confidence": 0.0,
        "discriminability": "none",
        "kind": "none",
        "score": None,
        "setting_probabilities": None,
        "notes": [reason],
    }


def _select_evidence(row, name, spec):
    """尤度に使う証拠を機種ごとに選ぶ。使えなければNone。

    BB・RBの両方の設定別確率があればBBとRBを別々の証拠にする(合算はしない)。
    不二子BTはサイトセブンのBB欄が全ボーナスの合算なので、BB−RBをBBとして使う(それ以外の取得元では使わない)。
    BB/RB別のスペックが無く合算しかない機種は、BB+RBの合計を合算確率で見る。
    """
    st = spec["settings"]

    def usable(candidates):
        return len(candidates) >= 2 and any(s >= 5 for s in candidates) and any(s < 5 for s in candidates)

    both = {s: v for s, v in st.items() if v.get("rb_probability") is not None and v.get("bb_probability") is not None}
    only_rb = {s: v for s, v in st.items() if v.get("rb_probability") is not None}
    combined = {s: v for s, v in st.items() if v.get("combined_probability") is not None}
    notes = []
    if usable(both) and row.bb is not None:
        bb = row.bb
        if "不二子" in name:
            if row.source == "site777" and row.bb >= (row.rb or 0):
                bb = row.bb - row.rb
                notes.append("不二子BT: BB欄は全ボーナス合算のため BB−RB をBBとして使う")
            else:
                both = {}
                notes.append("不二子BT: BB欄の定義が取得元で確認できないためRBのみ")
        if usable(both):
            return "bb_rb", both, bb, notes + ["BBとRBを別々の証拠として推定(合算は使わない)"]
    if usable(only_rb):
        return "rb", only_rb, None, notes + ["RBのみで推定。差枚は設定尤度に使わない"]
    # A+ATはDBのBB/RB列の意味が機種ごとに違うため、合算だけの機種は推定しない(BT・ノーマルに限る)。
    if usable(combined) and row.bb is not None and spec.get("category") in {"BT", "ノーマル"}:
        return "combined", combined, row.bb, ["BB/RB別のスペックが無いため合算(BB+RB)で推定"]
    return None


@lru_cache(maxsize=32)
def _hall_specs(hall):
    return load_specs(hall=hall)


def estimate(row: SnapshotRow, *, specs=None, audit=None, hall_prior=None, spec_variant="default", at_context=None):
    """RBだけを設定の尤度に使う。AT scoreは同時刻ホール・機種の平均G比×平均差枚。"""
    if spec_variant != "default":
        raise ValueError("unknown spec_variant")  # バーサスの2値問題は2026-10-07に解消(判別ページ値が正)
    name = _model(row)
    if not name:
        return _none("機種名を照合できない")
    audit = load_audit() if audit is None else audit
    if audit.get((row.hall, name)) == "X":
        return _none("AT_RB_AUDIT verdict X: 当該ホールのRB・差枚から設定を推定しない")
    specs = _hall_specs(row.hall) if specs is None else specs
    spec = find_spec(name, specs)
    if spec is None:
        return _none("設定別スペックがない")
    if spec.get("category") == "AT":
        if at_context is None:
            return _none("ATのG比には同時刻ホール全台の観測が必要")
        if row.games is None or row.diff is None:
            return _none("ATの累計Gまたは差枚が欠損")
        score = at_context.get((row.hall, row.observed_at, name))
        if score is None:
            return _none("ATの同時刻平均G比・平均差枚を計算できない")
        return {
            "p_high": None,
            "confidence": 0.0,
            "discriminability": "none",
            "kind": "at_gratio_diff",
            "score": score,
            "setting_probabilities": None,
            "notes": ["機種平均G比×機種平均差枚。設定の事後確率ではない", "RBは設定証拠に使用しない"],
        }
    if not spec.get("judgeable"):
        return _none("RBによる判別対象外")
    if row.games is None or row.rb is None:
        return _none("累計GまたはRBが欠損")
    if row.games <= 0 or not 0 <= row.rb <= row.games:
        return _none("累計GまたはRBが不正")
    chosen = _select_evidence(row, name, spec)
    if chosen is None:
        return _none("高低両側の設定別ボーナス確率が揃っていない")
    mode, settings, bb_count, evidence_notes = chosen
    prior = _prior(settings, row.hall, hall_prior)
    keys = {
        "bb_rb": ("bb_probability", "rb_probability"),
        "rb": ("rb_probability",),
        "combined": ("combined_probability",),
    }[mode]
    if row.source == "site777" and mode in {"bb_rb", "rb"}:
        from scraper.site777.setting_estimator import _log_likelihood

        logs = {}
        for s, v in settings.items():
            probabilities = {"rb_probability": v["rb_probability"], "use_bb": mode == "bb_rb"}
            if mode == "bb_rb":
                probabilities["bb_probability"] = v["bb_probability"]
            logs[s] = _log_likelihood(row.games, bb_count if mode == "bb_rb" else 0, row.rb, probabilities)
        peak = max(logs.values())
        weights = {s: math.exp(v - peak) * prior[s] for s, v in logs.items()}
        total = sum(weights.values())
        probs = {s: v / total for s, v in sorted(weights.items())}
    else:
        used = {s: {k: v[k] for k in keys} for s, v in settings.items()}
        probs = posterior({"settings": used}, row.games, bb_count if mode != "rb" else None, row.rb, prior=prior)
    if not probs:
        return _none("尤度を計算できない")
    if row.games < SMALL_GAMES:
        # 早期の極端な当たりも確信に変えない。事前×尤度^(G/1000) のpower posterior。
        power = row.games / SMALL_GAMES
        shrink = {s: prior[s] * (probs[s] / prior[s]) ** power for s in probs if prior[s] > 0}
        mass = sum(shrink.values())
        probs = {s: shrink.get(s, 0.0) / mass for s in probs}
    separation = max(
        max(v[k] for s, v in settings.items() if s >= 5) / min(v[k] for s, v in settings.items() if s < 5) for k in keys
    )
    discriminatory = "low" if separation < LOW_RB_RATIO else "high"
    # 観測が事前を上回る情報量。負方向のエントロピー変化は0に切る。
    base = _entropy(prior.values())
    confidence = max(0.0, min(1.0, (base - _entropy(probs.values())) / base)) if base else 0.0
    notes = list(evidence_notes)
    if row.games < SMALL_GAMES:
        notes.append("1000G未満: 尤度をG/1000乗して事前へ縮小")
    elif row.games <= EARLY_GAMES:
        notes.append("途中経過の高RBは最終で平均に回帰しうる")
    if discriminatory == "low":
        notes.append("設定間のボーナス確率差が小さく判別不能に近い")
    return {
        "p_high": sum(p for s, p in probs.items() if s >= 5),
        "confidence": confidence,
        "discriminability": discriminatory,
        "kind": "rb_posterior",
        "score": None,
        "setting_probabilities": probs,
        "notes": notes,
    }


def at_scores(rows):
    """同じホール・観測時刻だけでG比と平均差枚を計算する。"""
    groups = defaultdict(list)
    for row in rows:
        groups[row.hall, row.observed_at].append(row)
    result = {}
    for (hall, stamp), members in groups.items():
        all_games = [r.games for r in members if r.games is not None and r.games >= 0]
        if not all_games or sum(all_games) == 0:
            continue
        hall_mean = sum(all_games) / len(all_games)
        by_model = defaultdict(list)
        for row in members:
            if row.games is not None and row.diff is not None and _model(row):
                by_model[_model(row)].append(row)
        for name, items in by_model.items():
            result[hall, stamp, name] = (
                sum(r.games for r in items) / len(items) / hall_mean * sum(r.diff for r in items) / len(items)
            )
    return result


def mark_new_machines(rows, db_dir=ROOT / "db"):
    """DBで確認できる機種の最初の結果日を導入日の代用にする。未確認はnull。"""
    cache = {}
    for row in rows:
        if row.is_new_machine is not None:
            continue
        key = (row.hall, _model(row))
        path = Path(db_dir) / f"{row.hall}.db"
        if key not in cache:
            cache[key] = None
            if key[1] and path.is_file() and path.stat().st_size:
                try:
                    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as con:
                        found = con.execute(
                            "SELECT MIN(date) FROM machine_detailed_results WHERE machine_name=?", (key[1],)
                        ).fetchone()[0]
                    cache[key] = found
                except sqlite3.Error:
                    pass
        if cache[key]:
            observed = datetime.fromisoformat(row.observed_at).date()
            first = datetime.strptime(cache[key], "%Y%m%d").date()
            row.is_new_machine = 0 <= (observed - first).days < NEW_MACHINE_DAYS
    return rows
