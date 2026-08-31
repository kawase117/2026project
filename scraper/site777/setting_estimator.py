"""累計G・BB・RBから設定を推定する。

スペック表は ml/experiments/jug_rb_setting_prediction/config.py の
JUGGLER_FAMILY_SPECS をそのまま使う。site777側でスペック値を持たない。

推定は二項尤度の最大化で行う。BBとRBを独立な二項として扱うのは既存の
stage2_daily_posterior.py と同じ近似で、確率が1/250〜1/440と小さいため
本来の多項分布との差は無視できる。

単一の最尤設定だけを出さないこと。スペック表からの合成試行では、8,000G
回しても最尤設定が真の設定にぴったり一致するのは3〜4割にとどまる
（6択の偶然は16.7%）。妥当な設定の幅と信用度を必ず添える。
"""

from __future__ import annotations

import importlib.util
import math
import unicodedata
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_CONFIG_PATH = PROJECT_ROOT / "ml" / "experiments" / "jug_rb_setting_prediction" / "config.py"

# 2,000G未満は誤警報が2〜3割に達するので推定対象にしない。
MIN_GAMES_FOR_SETTING = 2000
# 高設定側(5-6)と低設定側(1-4)の尤度比。何倍でどちらに寄っていると言い切るか。
#
# 最尤設定と2位の差を信用度にしてはいけない。1位と2位は必ず隣り合う設定になるため、
# 実データ78台では最大でも尤度比2.2倍にとどまり、全台が「低」に潰れた。
# 設定をピンポイントで当てるのは原理的に不可能で、判定できるのは高低どちら寄りかだけ。
LOG_HIGH_LOW_DECISIVE = math.log(10.0)
LOG_HIGH_LOW_MODERATE = math.log(3.0)
# 最尤設定の何分の1までを「否定できない設定」に含めるか。
LOG_BAND_WIDTH = math.log(8.0)
HIGH_SETTINGS = (5, 6)

# 合成試行で測った、真が設定1のときに最尤が設定5-6と出る割合。レポートに注記する。
FALSE_HIGH_RATE_AT_3000G = {
    "MYV": 0.114,
    "IMEX": 0.082,
    "GOGO3": 0.227,
    "HAPPY8": 0.129,
}


def load_family_specs(path: Path = SPEC_CONFIG_PATH) -> dict[str, Any]:
    """スペック表を読む。無ければ空dictを返し、設定推定だけを落とす。"""
    if not path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("_site777_jug_specs", path)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(getattr(module, "JUGGLER_FAMILY_SPECS", {}))


def _normalize(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).casefold()


def build_family_matcher(family_specs: dict[str, Any]) -> list[tuple[str, str]]:
    """(正規化キーワード, family_key) を長い順に返す。短い語の巻き込みを防ぐ。"""
    pairs = [
        (_normalize(spec.get("machine_keyword")), key)
        for key, spec in family_specs.items()
        if spec.get("machine_keyword")
    ]
    return sorted(pairs, key=lambda pair: -len(pair[0]))


def match_family(model_name: Any, matcher: list[tuple[str, str]]) -> str | None:
    name = _normalize(model_name)
    for keyword, family_key in matcher:
        if keyword and keyword in name:
            return family_key
    return None


def indistinguishable_settings(settings: dict[int, dict[str, float]]) -> list[list[int]]:
    """RB確率が同一の設定をまとめる。アイムEX系の設定5と6のように原理的に割れない組。"""
    groups: dict[float, list[int]] = {}
    for setting in sorted(settings):
        groups.setdefault(float(settings[setting]["rb_probability"]), []).append(setting)
    return [members for members in groups.values() if len(members) > 1]


def _log_likelihood(games: int, bb: int, rb: int, probabilities: dict[str, float]) -> float:
    # 二項係数は設定に依存しないので省く。順位と尤度比だけが必要。
    total = 0.0
    for count, key in ((bb, "bb_probability"), (rb, "rb_probability")):
        p = float(probabilities[key])
        total += count * math.log(p) + (games - count) * math.log1p(-p)
    return total


def estimate_setting(
    games: int,
    bb: int,
    rb: int,
    settings: dict[int, dict[str, float]],
) -> dict[str, Any] | None:
    """最尤設定・否定できない設定の幅・信用度を返す。母数不足なら None。"""
    if games < MIN_GAMES_FOR_SETTING or bb < 0 or rb < 0 or bb + rb > games:
        return None

    scores = {setting: _log_likelihood(games, bb, rb, spec) for setting, spec in settings.items()}
    ordered = sorted(scores, key=lambda setting: scores[setting], reverse=True)
    best = ordered[0]
    gap = scores[best] - scores[ordered[1]] if len(ordered) > 1 else math.inf
    band = sorted(setting for setting, score in scores.items() if scores[best] - score <= LOG_BAND_WIDTH)
    all_settings = sorted(scores)

    # 事前分布を仮定せず、観測が高設定側と低設定側のどちらをどれだけ支持するかだけを見る。
    high_scores = [scores[setting] for setting in scores if setting in HIGH_SETTINGS]
    low_scores = [scores[setting] for setting in scores if setting not in HIGH_SETTINGS]
    if high_scores and low_scores:
        log_ratio = max(high_scores) - max(low_scores)
        strength = abs(log_ratio)
        if strength >= LOG_HIGH_LOW_DECISIVE:
            confidence = "高"
        elif strength >= LOG_HIGH_LOW_MODERATE:
            confidence = "中"
        else:
            confidence = "低"
        lean = "高設定寄り" if log_ratio > 0 else "低設定寄り"
    else:
        log_ratio = None
        confidence = "低"
        lean = "判定不可"

    # 全設定が残った台は幅を書いても情報がない。絞れていない事実をそのまま出す。
    narrowed = len(band) < len(all_settings)
    if not narrowed:
        band_label = "絞れず"
    elif band[0] == band[-1]:
        band_label = str(band[0])
    else:
        band_label = f"{band[0]}〜{band[-1]}"

    weights = {setting: math.exp(score - scores[best]) for setting, score in scores.items()}
    total = sum(weights.values())
    return {
        "ml_setting": best,
        "setting_band_min": band[0],
        "setting_band_max": band[-1],
        "setting_band_label": band_label,
        "setting_band_narrowed": narrowed,
        "likelihood_gap": None if math.isinf(gap) else round(gap, 3),
        "high_low_log_ratio": None if log_ratio is None else round(log_ratio, 3),
        "high_low_ratio": None if log_ratio is None else round(math.exp(log_ratio), 2),
        "setting_lean": lean,
        "setting_confidence": confidence,
        # 参考値。事前分布を設定1〜6で一様と置いた場合の事後確率で、実際の高設定投入率は
        # これよりずっと低いため過大に出る。順位付けには high_low_ratio を使うこと。
        "p_high_setting_uniform_prior": round(sum(w for s, w in weights.items() if s >= 5) / total, 4),
        "expected_setting_uniform_prior": round(sum(s * w for s, w in weights.items()) / total, 2),
    }


SETTING_FIELDS = (
    "ml_setting",
    "setting_band_min",
    "setting_band_max",
    "setting_band_label",
    "setting_band_narrowed",
    "likelihood_gap",
    "high_low_log_ratio",
    "high_low_ratio",
    "setting_lean",
    "setting_confidence",
    "p_high_setting_uniform_prior",
    "expected_setting_uniform_prior",
)


def annotate_setting_estimates(machines: list[dict[str, Any]], family_specs: dict[str, Any]) -> dict[str, Any]:
    """machine dict に設定推定を書き込み、対象母数のサマリを返す。"""
    matcher = build_family_matcher(family_specs)
    estimated = 0
    below_threshold = 0
    families: dict[str, int] = {}

    for machine in machines:
        family_key = match_family(machine.get("model_name"), matcher) if matcher else None
        machine["setting_family_key"] = family_key
        machine["setting_family_name"] = family_specs[family_key]["family_name"] if family_key else None
        for field in SETTING_FIELDS:
            machine[field] = None
        if family_key is None:
            continue
        families[family_key] = families.get(family_key, 0) + 1
        result = estimate_setting(
            machine["games"],
            machine["bb_count"],
            machine["rb_count"],
            family_specs[family_key]["settings"],
        )
        if result is None:
            below_threshold += 1
            continue
        machine.update(result)
        estimated += 1

    return {
        "enabled": bool(family_specs),
        "spec_path": str(SPEC_CONFIG_PATH),
        "min_games": MIN_GAMES_FOR_SETTING,
        "family_machine_counts": families,
        "spec_covered_machines": sum(families.values()),
        "estimated_machines": estimated,
        "below_threshold_machines": below_threshold,
        "false_high_rate_at_3000g": {key: rate for key, rate in FALSE_HIGH_RATE_AT_3000G.items() if key in families},
        "indistinguishable": {
            key: indistinguishable_settings(family_specs[key]["settings"])
            for key in families
            if indistinguishable_settings(family_specs[key]["settings"])
        },
    }
