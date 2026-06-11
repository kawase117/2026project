"""
EDA Instinct Generator — Tier A パターンから instinct YAML ドラフトを生成
"""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

INSTINCT_DIR = Path(__file__).parent.parent / "document" / "instincts"


def draft_instinct(row: pd.Series,
                   group_cols: list,
                   hall_name: str,
                   context: str = "") -> str:
    """
    scan_dimension() の1行から instinct YAML ドラフト文字列を生成する。

    Parameters
    ----------
    row        : scan_dimension() の1行
    group_cols : グループ化に使った列リスト
    hall_name  : ホール名
    context    : 追記するドメイン知識（省略可）
    """
    pattern_desc = " × ".join(f"{c}={row[c]}" for c in group_cols)
    today = date.today().isoformat()

    def _safe(val):
        if isinstance(val, float) and np.isnan(val):
            return None
        if isinstance(val, np.integer):
            return int(val)
        if isinstance(val, np.floating):
            return round(float(val), 4)
        return val

    draft = {
        "id": f"draft-{hall_name}-{'_'.join(group_cols)}-{today}",
        "trigger": f"【要編集】{hall_name} で {pattern_desc} のパターンを評価するとき",
        "confidence": 0.70 if row["tier"] == "A" else 0.50,
        "domain": "hall-specific",
        "source": "auto-explorer",
        "project_id": "2026project",
        "project_name": "pachinko-analyzer",
        "status": "DRAFT — 人間レビュー必須",
        "hall": hall_name,
        "pattern": pattern_desc,
        "stats": {
            "tier":         row["tier"],
            "avg_diff":     _safe(row["avg_diff"]),
            "n":            _safe(row["n"]),
            "plus_rate":    _safe(row["plus_rate"]),
            "p_value":      _safe(row.get("p_value")),
            "epsilon_sq":   _safe(row.get("epsilon_sq")),
            "ci_95":        [_safe(row.get("ci_lo")), _safe(row.get("ci_hi"))],
            "spearman_rho": _safe(row.get("spearman_rho")),
        },
        "global_bias_check": "【要記入】グローバル平均との比較（混同していないか確認）",
        "notes":  context or "【要記入】なぜこのパターンが有意か、ドメイン解釈を記載",
        "action": "【要記入】具体的な運用ルールを記載",
    }

    return "---\n" + yaml.dump(draft, allow_unicode=True, sort_keys=False)


def export_tier_a_drafts(scan_result: pd.DataFrame,
                          group_cols: list,
                          hall_name: str,
                          output_path: str = None) -> str:
    """
    scan_dimension() 結果から Tier A 行の instinct ドラフトを一括生成・保存する。
    """
    tier_a = scan_result[scan_result["tier"] == "A"]
    if tier_a.empty:
        print("Tier A パターンが存在しません。")
        return ""

    drafts = [draft_instinct(row, group_cols, hall_name) for _, row in tier_a.iterrows()]
    content = "\n".join(drafts)

    if output_path is None:
        today = date.today().isoformat()
        dims  = "_".join(group_cols)
        fname = f"{today}-auto-draft-{hall_name}-{dims}.yaml"
        output_path = INSTINCT_DIR / fname

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✓ {len(tier_a)} 件の Tier A ドラフトを出力: {output_path}")
    return content


def export_summary_drafts(summarize_result: pd.DataFrame,
                           hall_name: str,
                           output_path: str = None) -> str:
    """
    summarize_scan() の結果（複数次元混在）から Tier A ドラフトを一括出力する。
    """
    tier_a = summarize_result[summarize_result["tier"] == "A"]
    if tier_a.empty:
        print("Tier A パターンが存在しません。")
        return ""

    drafts = []
    for _, row in tier_a.iterrows():
        dim_key    = row.get("dimension", "unknown")
        group_cols = dim_key.split(" × ")
        drafts.append(draft_instinct(row, group_cols, hall_name))

    content = "\n".join(drafts)

    if output_path is None:
        today = date.today().isoformat()
        fname = f"{today}-auto-draft-{hall_name}-full-scan.yaml"
        output_path = INSTINCT_DIR / fname

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✓ {len(tier_a)} 件の Tier A ドラフトを出力: {output_path}")
    return content
