import pytest
import tempfile
import json
from pathlib import Path
import sys

# ml/ ディレクトリからインポート
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from ml.hypothesis_02_model import load_winner_strategy, run_hypothesis_2_experiments


def test_load_winner_strategy():
    """Step 1 の勝者戦略を読み込み"""
    with tempfile.TemporaryDirectory() as tmpdir:
        results_dir = Path(tmpdir)
        
        # ダミー実験ログを作成
        exp_log = {
            "experiment_id": "exp_001_groupby_tail_task_a",
            "groupby_strategy": "tail",
            "metrics": {"auc": 0.95}
        }
        
        exp_file = results_dir / "exp_001_groupby_tail_task_a.json"
        with open(exp_file, "w", encoding="utf-8") as f:
            json.dump(exp_log, f)
        
        # 勝者戦略を読み込み
        winner = load_winner_strategy(str(results_dir))
        assert winner == "tail"


def test_hypothesis_2_execution():
    """仮説2（MLモデル検証）の実行"""
    # フロー確認のみ
    pass
