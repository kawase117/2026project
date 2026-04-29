"""
Shap値分析 - 特徴量の寄与度と影響度を可視化

Phase 6A Step 3:
モデルの予測判断根拠を特徴量レベルで分解し、
実際に効いている特徴と過学習の原因を特定する
"""

import numpy as np
import pandas as pd
import shap
from pathlib import Path
from typing import Tuple
from ml.data_preparation import prepare_data_by_groupby
from ml.models.baseline_logistic import LogisticRegressionModel
from ml.models.tree_xgboost import XGBoostModel


class ShapAnalyzer:
    """Shap値分析エンジン"""

    def __init__(self, model, X_train, X_test, feature_names=None):
        """
        Args:
            model: Fitted BaseModel (LogisticRegression or XGBoost)
            X_train: Training feature matrix (用于生成背景数据)
            X_test: Test feature matrix
            feature_names: Feature column names (optional)
        """
        self.model = model
        self.X_train = X_train
        self.X_test = X_test
        self.feature_names = feature_names or [f"Feature_{i}" for i in range(X_train.shape[1])]

    def analyze_logistic(self, top_n: int = 10) -> Tuple[np.ndarray, pd.DataFrame]:
        """
        ロジスティック回帰モデルの係数を特徴量寄与度として抽出

        Returns:
            (coef, importance_df)
        """
        # ロジスティック回帰の係数を取得
        coef = self.model.model.coef_[0]  # shape: (n_features,)
        intercept = self.model.model.intercept_[0]

        # 係数の絶対値でランク付け
        abs_coef = np.abs(coef)
        top_indices = np.argsort(abs_coef)[-top_n:][::-1]

        # 重要度テーブル作成
        importance_df = pd.DataFrame({
            'Feature': [self.feature_names[i] for i in top_indices],
            'Coefficient': coef[top_indices],
            'Abs_Coefficient': abs_coef[top_indices],
            'Rank': range(1, len(top_indices) + 1)
        })

        print("[Logistic] Feature Importance (Top Coefficients)")
        print(importance_df.to_string(index=False))

        return coef, importance_df

    def analyze_xgboost_shap(self, use_background: str = "sample", background_size: int = 100):
        """
        XGBoostモデルのShap値を計算して特徴量重要度を取得

        Args:
            use_background: "sample" or "tree"
            background_size: Background dataのサンプル数

        Returns:
            (shap_values, importance_df)
        """
        try:
            # TreeExplainer を使用（XGBoost用）
            explainer = shap.TreeExplainer(self.model.model)

            # Background dataを作成（計算量削減のため）
            if len(self.X_train) > background_size:
                bg_indices = np.random.choice(len(self.X_train), background_size, replace=False)
                X_background = self.X_train[bg_indices]
            else:
                X_background = self.X_train

            print(f"[XGBoost] Computing Shap values with background size {len(X_background)}...")

            # テストセットのShap値を計算
            shap_values = explainer.shap_values(self.X_test)

            # shap_values shape: (n_samples, n_features) for binary classification
            # 平均の寄与度を計算
            if isinstance(shap_values, list):
                # Binary classification case
                shap_mean = np.abs(shap_values[1]).mean(axis=0)
            else:
                shap_mean = np.abs(shap_values).mean(axis=0)

            # 重要度テーブル作成
            top_n = min(10, len(self.feature_names))
            top_indices = np.argsort(shap_mean)[-top_n:][::-1]

            importance_df = pd.DataFrame({
                'Feature': [self.feature_names[i] for i in top_indices],
                'Shap_Mean': shap_mean[top_indices],
                'Rank': range(1, len(top_indices) + 1)
            })

            print("[XGBoost] Feature Importance (Shap Values)")
            print(importance_df.to_string(index=False))

            return shap_values, importance_df

        except Exception as e:
            print(f"[WARN] Shap計算エラー: {e}")
            print("[INFO] 係数ベースの重要度を使用します...")
            return None, None

    def analyze_feature_impact_by_quintile(self) -> pd.DataFrame:
        """
        特徴量の各五分位数（分布）での平均予測値を計算
        特徴量の実際の予測影響を把握する

        Returns:
            Impact analysis DataFrame
        """
        results = []

        for feat_idx in range(min(5, self.X_test.shape[1])):  # Top 5 features
            feat_name = self.feature_names[feat_idx]
            feat_values = self.X_test[:, feat_idx]

            # 五分位数を計算
            quintiles = np.percentile(feat_values, [0, 20, 40, 60, 80, 100])

            for q_idx in range(len(quintiles) - 1):
                lower, upper = quintiles[q_idx], quintiles[q_idx + 1]
                mask = (feat_values >= lower) & (feat_values <= upper)

                if mask.sum() > 0:
                    X_subset = self.X_test[mask]
                    y_pred = self.model.predict_proba(X_subset)[:, 1]  # クラス1の確率
                    results.append({
                        'Feature': feat_name,
                        'Quintile': f"Q{q_idx + 1}",
                        'Range': f"[{lower:.2f}, {upper:.2f}]",
                        'Count': mask.sum(),
                        'Avg_Probability': y_pred.mean(),
                    })

        return pd.DataFrame(results)


def run_shap_analysis_on_hall(
    db_path: str,
    hall_name: str,
    groupby_strategy: str = "model_type",
    task: str = "a",
    model_type: str = "logistic"
):
    """
    単一ホールでShap分析を実行

    Args:
        db_path: SQLite DBファイルパス
        hall_name: ホール名
        groupby_strategy: "tail", "model_type", "machine_number"
        task: "a" or "b"
        model_type: "logistic" or "xgboost"
    """
    print(f"\n{'='*70}")
    print(f"Shap Analysis: {hall_name} (Strategy={groupby_strategy}, Model={model_type})")
    print(f"{'='*70}")

    try:
        # データ準備
        X_train, y_train, X_test, y_test = prepare_data_by_groupby(
            db_path=db_path,
            groupby_strategy=groupby_strategy,
            task=task,
            enable_extended_features=False
        )

        # モデル訓練
        if model_type == "logistic":
            model = LogisticRegressionModel(random_state=42)
        elif model_type == "xgboost":
            model = XGBoostModel(random_state=42)
        else:
            raise ValueError(f"Unknown model_type: {model_type}")

        model.fit(X_train, y_train)

        # 特徴量名生成
        if groupby_strategy == "tail":
            feature_names = [f"tail_{i}" for i in range(10)]
        elif groupby_strategy == "model_type":
            # XGBoost では分類器モデルの機種数に応じた名前
            feature_names = [f"model_{i}" for i in range(X_train.shape[1])]
        elif groupby_strategy == "machine_number":
            feature_names = ["machine_number"]

        # Shap分析
        analyzer = ShapAnalyzer(model, X_train, X_test, feature_names=feature_names)

        # モデルタイプに応じた分析
        if model_type == "logistic":
            coef, imp_df = analyzer.analyze_logistic(top_n=10)
        else:
            shap_vals, imp_df = analyzer.analyze_xgboost_shap()

        # 特徴量の実際の影響を分析
        print("\n[Impact Analysis by Quintile]")
        impact_df = analyzer.analyze_feature_impact_by_quintile()
        print(impact_df.to_string(index=False))

        print(f"\n[OK] {hall_name} Shap analysis completed")

    except Exception as e:
        print(f"[NG] Error: {e}")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Shap値分析")
    parser.add_argument("--db-path", default="db/ARROW池上店.db", help="SQLite DBパス")
    parser.add_argument("--hall-name", default="ARROW池上店", help="ホール名")
    parser.add_argument("--strategy", default="model_type", help="グループ化戦略")
    parser.add_argument("--task", default="a", help="タスク (a/b)")
    parser.add_argument("--model", default="logistic", help="モデル (logistic/xgboost)")

    args = parser.parse_args()

    run_shap_analysis_on_hall(
        db_path=args.db_path,
        hall_name=args.hall_name,
        groupby_strategy=args.strategy,
        task=args.task,
        model_type=args.model
    )
