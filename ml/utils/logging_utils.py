import json
import os
from pathlib import Path
from datetime import datetime


def get_experiments_dir() -> Path:
    """実験ログ出力ディレクトリを取得"""
    exp_dir = Path(__file__).parent.parent / "experiments" / "results"
    exp_dir.mkdir(parents=True, exist_ok=True)
    return exp_dir


def save_experiment_log(
    exp_id: str,
    phase: int,
    hypothesis: str,
    groupby_strategy: str,
    task: str,
    ml_model: str,
    metrics: dict,
    interpretation: str,
    next_step: str = ""
):
    """
    実験結果をJSON形式でログに保存

    Args:
        exp_id: 実験ID（例：exp_001_groupby_tail_task_a）
        phase: フェーズ（1 or 2）
        hypothesis: 仮説説明
        groupby_strategy: グループ化戦略（tail, model_type, machine_number）
        task: タスク（a or b）
        ml_model: MLモデル名（logistic, xgboost等）
        metrics: 評価メトリクス辞書（auc, accuracy, brier_score等）
        interpretation: 結果の解釈
        next_step: 次のステップ
    """
    exp_dir = get_experiments_dir()
    timestamp = datetime.now().isoformat()

    log_data = {
        "experiment_id": exp_id,
        "timestamp": timestamp,
        "phase": phase,
        "hypothesis": hypothesis,
        "groupby_strategy": groupby_strategy,
        "task": task,
        "ml_model": ml_model,
        "metrics": metrics,
        "interpretation": interpretation,
        "next_step": next_step
    }

    # JSON ファイルに保存
    json_file = exp_dir / f"{exp_id}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    return json_file
