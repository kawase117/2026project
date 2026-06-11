"""
instinct YAMLファイルに scope / hall フィールドを一括追加するスクリプト。

scope の分類：
  methodology    : リーク検出・統計手順・ML評価手法など普遍的な知識
  domain-general : パチスロ全般に適用できる原則
  hall-specific  : 特定ホールの定量的発見（hall フィールドで明示）

実行：
  python ml/last_digit/add_instinct_scope.py
  python ml/last_digit/add_instinct_scope.py --dry-run
"""

import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent.parent / "document" / "instincts"

# ファイル名ベースの分類ルール (パターン, scope, hall)
FILENAME_RULES = [
    # 明示的にホール名が入っているもの
    ("kamata7",                          "hall-specific",  "kamata7"),
    # 方法論系
    ("leakage",                          "methodology",    None),
    ("signal-existence",                 "methodology",    None),
    ("evaluation-feature",               "methodology",    None),
    ("prediction-evaluation-methodology","methodology",    None),
    ("codex-analysis-improvements",      "methodology",    None),
    ("gitignore",                        "methodology",    None),
    ("ml-exploration-coarse-to-fine",    "methodology",    None),
    ("machine-type-v2-redesign",         "methodology",    None),
    ("ceiling-effect-framework",         "methodology",    None),
    ("machine-master-flag-system",       "methodology",    None),
    ("data-leakage",                     "methodology",    None),
    ("within-expert-target-fix",         "methodology",    None),
    ("v2-withinexpert-is-ceiling",       "methodology",    None),
    ("ltr-feature-engineering",          "methodology",    None),
    ("ltr-feature-selection",            "methodology",    None),
    ("ltr-operational-kpi",              "methodology",    None),
    ("phase6b-ml",                       "methodology",    None),
    ("phase7",                           "methodology",    None),
    ("phase8",                           "methodology",    None),
    ("phase9",                           "methodology",    None),
    ("percentile-relative",              "methodology",    None),
    ("zorome-correction-validation",     "methodology",    None),
    ("excess-count-vs-hit",              "methodology",    None),
    ("unfired-nextday-verification",     "methodology",    None),
    ("evaluation-window-90d",            "methodology",    None),
    ("machine-type-v2-active-filter",    "methodology",    None),
    ("machine-type-v2-segment-diagnostics","methodology",  None),
    ("machine-type-ltr-segmentation",    "methodology",    None),
    ("combined-prediction-simulation",   "methodology",    None),
    ("cross-expert-agreement",           "methodology",    None),
    ("kisyuzen-evaluation",              "methodology",    None),
    ("kikata-winrate-target",            "methodology",    None),
    ("page16-page13-optimization",       "methodology",    None),
    ("tail-ranking-nonstationarity",     "methodology",    None),
    ("machine-type-ceiling-position",    "methodology",    None),
    ("catboost-gpu-wf",                  "methodology",    None),
    ("machine-type-ltr-insights",        "methodology",    None),
    ("machine-type-v2-active",           "methodology",    None),
    # セグメント戦略は蒲田7固有の定量結果
    ("segment-strategy",                 "hall-specific",  "kamata7"),
    # 今セッションの評価手順（普遍）
    ("evaluation-feature",               "methodology",    None),
]

# コンテンツキーワードで補助判定
HALL_KEYWORDS = [
    "蒲田7", "蒲田七", "kamata7", "2F_N", "3F_N", "2F_A", "3F_A",
    "69.3%", "9731", "-9,731", "lag=14", "digit=8",
    "金時京急", "みとや", "レイトギャップ", "ザ-シティ",
]
METHOD_KEYWORDS = [
    "リーク", "leakage", "walk-forward", "FDR", "p_raw",
    "Bonferroni", "Spearman", "hit@2", "precision@2", "AUC",
    "ablation", "holdout", "selection",
]


def classify_file(path: Path) -> tuple[str, str | None]:
    name = path.stem.lower()
    if name == "_cli_export":
        return "skip", None

    for pattern, scope, hall in FILENAME_RULES:
        if pattern in name:
            return scope, hall

    # コンテンツキーワードでフォールバック
    try:
        content = path.read_text(encoding="utf-8")
        hall_hits = sum(1 for kw in HALL_KEYWORDS if kw in content)
        method_hits = sum(1 for kw in METHOD_KEYWORDS if kw in content)
        if hall_hits > method_hits:
            return "hall-specific", "kamata7"
        if method_hits > 0:
            return "methodology", None
    except Exception:
        pass

    # デフォルト：蒲田7の分析が主体
    return "hall-specific", "kamata7"


def add_scope_to_block(block: str, scope: str, hall: str | None) -> str:
    if re.search(r"^scope:", block, re.MULTILINE):
        return block  # すでにある

    scope_line = f"scope: {scope}"
    hall_line = f"hall: {hall}" if hall else None

    def insert_after_confidence(m):
        lines = [m.group(0), scope_line]
        if hall_line:
            lines.append(hall_line)
        return "\n".join(lines)

    return re.sub(
        r"^confidence:.*$",
        insert_after_confidence,
        block,
        flags=re.MULTILINE,
    )


def process_file(path: Path, scope: str, hall: str | None, dry_run: bool = False):
    text = path.read_text(encoding="utf-8")
    blocks = text.split("---")
    new_blocks = []
    changed = False

    for block in blocks:
        if not block.strip():
            new_blocks.append(block)
            continue
        if not re.search(r"^id:", block, re.MULTILINE):
            new_blocks.append(block)
            continue
        new_block = add_scope_to_block(block, scope, hall)
        if new_block != block:
            changed = True
        new_blocks.append(new_block)

    if not changed:
        print(f"  [skip] {path.name}")
        return

    new_text = "---".join(new_blocks)
    if dry_run:
        print(f"  [dry]  {path.name}  scope={scope}, hall={hall}")
    else:
        path.write_text(new_text, encoding="utf-8")
        print(f"  [done] {path.name}  scope={scope}, hall={hall}")


def main():
    dry_run = "--dry-run" in sys.argv
    yaml_files = sorted(BASE.glob("*.yaml"))
    print(f"対象ファイル数: {len(yaml_files)}\n")

    for path in yaml_files:
        scope, hall = classify_file(path)
        if scope == "skip":
            print(f"  [skip] {path.name} (config)")
            continue
        process_file(path, scope, hall, dry_run=dry_run)

    print("\n完了")


if __name__ == "__main__":
    main()
