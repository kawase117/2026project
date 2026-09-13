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


# 機種別の全台系判定。1台ずつでは設定を絞れない回転数でも、機種の全台を合算すれば
# 判定できることがある。ただし合算平均が高いだけでは「全台が高い」と「1〜2台だけが
# 突出して高い（機種イチの撒き餌）」を区別できない。2026-09-13 の楽園蒲田では
# ネオアイムジャグラーEX 62台の合算RBが設定1比 p<0.0001 だったが、全台高設定は
# ほぼ否定され、最も尤もらしいのは62台中15台前後の部分投入だった。
# そこで「全台同一設定」を仮定した合算尤度比に加えて、高設定の台数 k の事後分布を見る。
ZENTAIKEI_MIN_MACHINES = 3
LOG_ZENTAIKEI_DECISIVE = LOG_HIGH_LOW_DECISIVE
ZENTAIKEI_FIELDS = (
    "n_machines",
    "total_games",
    "total_bb",
    "total_rb",
    "pooled_ml_setting",
    "all_high_vs_low_log_ratio",
    "all_high_vs_low_ratio",
    "k_map",
    "p_k_map",
    "p_all_high",
    "p_half_or_more_high",
    "p_none_high",
    "verdict",
)


def _logsumexp(values: list[float]) -> float:
    finite = [value for value in values if value != -math.inf]
    if not finite:
        return -math.inf
    peak = max(finite)
    return peak + math.log(sum(math.exp(value - peak) for value in finite))


def _log_mean_likelihood(
    games: int, bb: int, rb: int, settings: dict[int, dict[str, float]], members: list[int]
) -> float:
    """設定群の中で一様に平均した尤度（確率空間での平均）の対数。"""
    return _logsumexp([_log_likelihood(games, bb, rb, settings[member]) for member in members]) - math.log(len(members))


def judge_model_zentaikei(
    machines: list[dict[str, Any]], settings: dict[int, dict[str, float]]
) -> dict[str, Any] | None:
    """同一機種の台を合算して、全台系かどうかを判定する。台数不足なら None。

    2つの量を返す:
    - all_high_vs_low_ratio: 全台が同一設定と仮定した合算尤度で、設定5-6側と1-4側の比。
      ユーザーの「全台合算した機種平均が一定以上なら全」をそのまま尤度にしたもの。
    - 高設定台数 k の事後分布: 各台を高(5-6の平均)/低(残りの平均)のいずれかとし、
      k=0..n を一様事前にした事後確率。合算平均を1台が押し上げただけなら k は小さく出る。

    合算には 2,000G 未満の台も含める。回転数を稼ぐための合算なので足切りしない。
    """
    usable = [
        machine
        for machine in machines
        if (machine.get("games") or 0) > 0
        and (machine.get("bb_count") or 0) >= 0
        and (machine.get("rb_count") or 0) >= 0
        and (machine.get("bb_count") or 0) + (machine.get("rb_count") or 0) <= machine["games"]
    ]
    n = len(usable)
    high = [setting for setting in sorted(settings) if setting in HIGH_SETTINGS]
    low = [setting for setting in sorted(settings) if setting not in HIGH_SETTINGS]
    if n < ZENTAIKEI_MIN_MACHINES or not high or not low:
        return None

    total_games = sum(int(machine["games"]) for machine in usable)
    total_bb = sum(int(machine.get("bb_count") or 0) for machine in usable)
    total_rb = sum(int(machine.get("rb_count") or 0) for machine in usable)
    pooled = {setting: _log_likelihood(total_games, total_bb, total_rb, settings[setting]) for setting in settings}
    pooled_ml = max(pooled, key=lambda setting: pooled[setting])
    log_ratio = (
        _logsumexp([pooled[s] for s in high])
        - math.log(len(high))
        - (_logsumexp([pooled[s] for s in low]) - math.log(len(low)))
    )

    # dp[k] = k台が高設定である割り当て全体の尤度の和（対数）。
    dp = [0.0] + [-math.inf] * n
    for machine in usable:
        games, bb, rb = int(machine["games"]), int(machine.get("bb_count") or 0), int(machine.get("rb_count") or 0)
        log_high = _log_mean_likelihood(games, bb, rb, settings, high)
        log_low = _log_mean_likelihood(games, bb, rb, settings, low)
        nxt = [-math.inf] * (n + 1)
        for k, value in enumerate(dp):
            if value == -math.inf:
                continue
            nxt[k] = _logsumexp([nxt[k], value + log_low])
            if k + 1 <= n:
                nxt[k + 1] = _logsumexp([nxt[k + 1], value + log_high])
        dp = nxt
    # k の中では割り当てを等確率とし、k 自体を一様事前にする。
    log_k = [dp[k] - math.log(math.comb(n, k)) for k in range(n + 1)]
    norm = _logsumexp(log_k)
    posterior = [math.exp(value - norm) for value in log_k]
    k_map = max(range(n + 1), key=lambda k: posterior[k])
    # 最尤の k でも事後確率が一様（1/(n+1)）の2倍に届かないなら、事後分布はほぼ平らで
    # 何も言えていない。2026-09-13 の新ハナビ6台は最尤 k=0 だが P(k=0)=17%（一様14%）で、
    # これを「高設定なし寄り」と表示すると誤解を招いた。
    flat = posterior[k_map] < 2.0 / (n + 1)

    if k_map == n and log_ratio >= LOG_ZENTAIKEI_DECISIVE and posterior[n] >= 0.5:
        verdict = "全台系"
    elif flat:
        verdict = "判定保留（情報不足）"
    elif k_map == n:
        verdict = "全台系寄り（未確定）"
    elif k_map == 0:
        verdict = "高設定なし寄り"
    else:
        verdict = "部分投入寄り"

    return {
        "n_machines": n,
        "total_games": total_games,
        "total_bb": total_bb,
        "total_rb": total_rb,
        "pooled_ml_setting": pooled_ml,
        "all_high_vs_low_log_ratio": round(log_ratio, 3),
        # 大台数では対数が数百に達するので、表示用の倍率は上限を切る。
        "all_high_vs_low_ratio": round(math.exp(max(min(log_ratio, 700.0), -700.0)), 4),
        "k_map": k_map,
        "p_k_map": round(posterior[k_map], 4),
        "p_all_high": round(posterior[n], 4),
        "p_half_or_more_high": round(sum(posterior[(n + 1) // 2 :]), 4),
        "p_none_high": round(posterior[0], 4),
        "verdict": verdict,
    }


def judge_zentaikei_by_model(machines: list[dict[str, Any]], family_specs: dict[str, Any]) -> list[dict[str, Any]]:
    """annotate_setting_estimates 済みの台を機種名で束ね、機種ごとに全台系判定を付ける。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for machine in machines:
        family_key = machine.get("setting_family_key")
        if family_key and family_key in family_specs:
            groups.setdefault(machine.get("model_name") or "", []).append(machine)
    rows = []
    for model_name, group in groups.items():
        settings = family_specs[group[0]["setting_family_key"]]["settings"]
        result = judge_model_zentaikei(group, settings)
        if result is None:
            continue
        rows.append({"model_name": model_name, "setting_family_key": group[0]["setting_family_key"], **result})
    return sorted(rows, key=lambda row: -row["all_high_vs_low_log_ratio"])


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
