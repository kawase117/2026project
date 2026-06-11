"""
リークによって汚染されたinstinctを仕分けするスクリプト。

分類基準：
  ARCHIVE : MLモデル性能値（AUC/hit@2/precision）が主体 → contaminated/ へ移動
  WARN    : 実データ観察は有効、アクション項目がリーク前の文脈を参照 → 警告注記を追加
  KEEP    : 方法論・データ構造・リーク後の発見 → そのまま

実行：
  python ml/last_digit/triage_contaminated_instincts.py
  python ml/last_digit/triage_contaminated_instincts.py --dry-run
"""

import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE    = Path(__file__).parent.parent.parent / "document" / "instincts"
ARCHIVE = BASE / "contaminated"
ARCHIVE.mkdir(exist_ok=True)

# MLモデル性能値（AUC・hit@2・precision）が主体。数値はリーク込みで無効。
ARCHIVE_FILES = [
    "phase6b-ml-insights.yaml",
    "2026-05-09-phase7-ml-insights.yaml",
    "2026-05-09-phase8-10-insights.yaml",
    "2026-05-09-phase9-10-breakthroughs.yaml",
    "2026-05-25-catboost-gpu-wf-insights.yaml",
    "2026-05-25-ltr-feature-selection-bisect-insights.yaml",
    "2026-05-26-kamata7-ltr-multitier-strategy.yaml",
    "2026-05-27-ml-2f-3f-strategy.yaml",
    "2026-05-29-prediction-accuracy-analysis.yaml",
]

# 実データ観察（diff_coins集計等）は有効。アクション項目は要再検証。
WARN_FILES = [
    "2026-05-25-bt-digit-patterns.yaml",
    "2026-05-25-bt-machine-characteristics.yaml",
    "2026-05-25-atype-bt-opposite-cluster-half2.yaml",
    "2026-05-25-floor-atype-cluster-insights.yaml",
    "2026-05-25-kamata7-weekday-investment-pattern.yaml",
    "2026-05-25-digit3-hall-strategy-insights.yaml",
    "2026-05-25-digit7-weekday-pattern-insights.yaml",
    "2026-05-25-digit3-weekday-cross-insights.yaml",
    "2026-05-25-streak-and-machine-type-digit-insights.yaml",
    "2026-05-25-anomaly-analysis-insights.yaml",
    "2026-05-27-ltr-operational-kpi-insights.yaml",
    "2026-05-28-zorome-combined-strategy-insights.yaml",
    "2026-05-28-signal-quantile-result-insights.yaml",
    "2026-05-29-event-day-zorome-priority-insights.yaml",
    "2026-05-29-live-evaluation-patterns.yaml",
    "2026-05-30-backtest-evaluation-insights.yaml",
]

WARNING_HEADER = """\
# ⚠️  LEAKAGE WARNING (added 2026-06-01)
# このファイルのインサイトは2026-05-31のリーク修正前に作成された。
# 【有効】実データ観察（diff_coins集計・ゾロ目パターン・台配置等）
# 【無効】MLモデル性能値（AUC / hit@2 / precision 等の数値）
# アクション項目を実運用に使う前にリーク修正後のモデルで再検証すること。

"""


def add_warning(path: Path, dry_run: bool):
    text = path.read_text(encoding="utf-8")
    if "LEAKAGE WARNING" in text:
        print(f"  [skip]    {path.name} (already warned)")
        return
    new_text = WARNING_HEADER + text
    if dry_run:
        print(f"  [dry-warn] {path.name}")
    else:
        path.write_text(new_text, encoding="utf-8")
        print(f"  [warned]   {path.name}")


def archive_file(path: Path, dry_run: bool):
    dest = ARCHIVE / path.name
    if dry_run:
        print(f"  [dry-archive] {path.name}")
    else:
        shutil.move(str(path), str(dest))
        print(f"  [archived]    {path.name} → contaminated/")


def main():
    dry_run = "--dry-run" in sys.argv

    print("=== ARCHIVE（MLモデル性能値が主体） ===")
    for fname in ARCHIVE_FILES:
        p = BASE / fname
        if not p.exists():
            print(f"  [missing] {fname}")
            continue
        archive_file(p, dry_run)

    print("\n=== WARN（実データ有効・アクション要再検証） ===")
    for fname in WARN_FILES:
        p = BASE / fname
        if not p.exists():
            print(f"  [missing] {fname}")
            continue
        add_warning(p, dry_run)

    print("\n完了")


if __name__ == "__main__":
    main()
