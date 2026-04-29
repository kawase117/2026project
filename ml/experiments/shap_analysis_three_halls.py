"""
3ホール別Shap分析 — ホール間の戦略差を可視化

Phase 6A Step 3（修正版）:
マルハン蒲田1・7、みとや大森町の3ホールについて
個別にShap値分析を実行し、ホール固有の設定投入戦略を明らかにする
"""

import numpy as np
import pandas as pd
import sqlite3
from pathlib import Path
from typing import Dict, Tuple
from ml.data_preparation import prepare_data_by_groupby
from ml.models.baseline_logistic import LogisticRegressionModel


class HallComparativeShapAnalysis:
    """3ホール別Shap分析エンジン"""

    HALLS = {
        "マルハン蒲田1": "db/マルハンメガシティ2000-蒲田1.db",
        "マルハン蒲田7": "db/マルハンメガシティ2000-蒲田7.db",
        "みとや大森町": "db/みとや大森町店.db",
    }

    def __init__(self):
        self.results = {}
        self.feature_names_per_hall = {}

    def analyze_hall(
        self,
        hall_name: str,
        db_path: str,
        groupby_strategy: str = "model_type",
        task: str = "a",
        top_n: int = 10
    ) -> Tuple[np.ndarray, pd.DataFrame]:
        """
        単一ホールのShap分析を実行

        Returns:
            (coefficients, importance_df)
        """
        print(f"\n{'='*80}")
        print(f"Shap Analysis: {hall_name}")
        print(f"{'='*80}")

        try:
            # データ準備
            X_train, y_train, X_test, y_test = prepare_data_by_groupby(
                db_path=db_path,
                groupby_strategy=groupby_strategy,
                task=task,
                enable_extended_features=False
            )

            print(f"[Data] Train: {len(X_train)} samples, Features: {X_train.shape[1]}")
            print(f"[Data] Test:  {len(X_test)} samples")

            # ラベル分布確認
            pos_train = y_train.sum()
            pos_test = y_test.sum()
            print(f"[Label] Train: {pos_train}/{len(y_train)} positive ({100*pos_train/len(y_train):.1f}%)")
            print(f"[Label] Test:  {pos_test}/{len(y_test)} positive ({100*pos_test/len(y_test):.1f}%)")

            # モデル訓練
            model = LogisticRegressionModel(random_state=42)
            model.fit(X_train, y_train)

            # 係数抽出
            coef = model.model.coef_[0]

            # 特徴量名生成（機種別戦略の場合）
            if groupby_strategy == "model_type":
                feature_names = self._extract_model_names(db_path, X_train.shape[1])
            else:
                feature_names = [f"feat_{i}" for i in range(X_train.shape[1])]

            self.feature_names_per_hall[hall_name] = feature_names

            # TOP N 特徴量を抽出
            abs_coef = np.abs(coef)
            top_indices = np.argsort(abs_coef)[-top_n:][::-1]

            importance_df = pd.DataFrame({
                'Rank': range(1, len(top_indices) + 1),
                'Feature': [feature_names[i] for i in top_indices],
                'Coefficient': coef[top_indices],
                'Abs_Coefficient': abs_coef[top_indices],
                'Direction': ['Positive' if coef[i] > 0 else 'Negative' for i in top_indices]
            })

            print(f"\n[TOP {top_n} Features by Absolute Coefficient]")
            print(importance_df.to_string(index=False))

            # 精度メトリクス
            from sklearn.metrics import roc_auc_score
            y_pred_proba = model.predict_proba(X_test)[:, 1]
            auc = roc_auc_score(y_test, y_pred_proba)
            print(f"\n[AUC] Test AUC = {auc:.4f}")

            self.results[hall_name] = {
                'model': model,
                'coefficients': coef,
                'importance_df': importance_df,
                'auc': auc,
                'feature_names': feature_names,
                'X_train': X_train,
                'X_test': X_test,
                'y_train': y_train,
                'y_test': y_test
            }

            return coef, importance_df

        except FileNotFoundError:
            print(f"[ERROR] Database not found: {db_path}")
            return None, None
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def _extract_model_names(self, db_path: str, expected_count: int) -> list:
        """
        DBから機種名を抽出（model_type one-hot エンコード順）
        """
        try:
            conn = sqlite3.connect(db_path)
            query = "SELECT DISTINCT machine_name FROM machine_detailed_results ORDER BY machine_name"
            df = pd.read_sql_query(query, conn)
            conn.close()

            models = df['machine_name'].tolist()

            # Padding: expected_count に合わせる
            if len(models) < expected_count:
                models += [f'_padding_{i}' for i in range(expected_count - len(models))]
            elif len(models) > expected_count:
                models = models[:expected_count]

            return models
        except Exception as e:
            print(f"[WARN] Failed to extract model names: {e}")
            return [f"model_{i}" for i in range(expected_count)]

    def compare_halls(self) -> pd.DataFrame:
        """
        3ホール間での特徴量係数を比較

        Returns:
            Comparison DataFrame (特徴量ごとに3ホールの係数を並べる)
        """
        if len(self.results) < 2:
            print("[WARN] Need at least 2 halls for comparison")
            return None

        print(f"\n{'='*100}")
        print("COMPARATIVE ANALYSIS: 3-Hall Strategy Differences")
        print(f"{'='*100}")

        # 全特徴量の統合リスト（重複なし）
        all_features = set()
        for hall_name in self.results.keys():
            features = self.results[hall_name]['feature_names']
            all_features.update(features)
        all_features = sorted(list(all_features))

        # 比較テーブル作成
        comparison_rows = []
        for feat in all_features:
            row = {'Feature': feat}
            for hall_name in sorted(self.results.keys()):
                feature_names = self.results[hall_name]['feature_names']
                coef = self.results[hall_name]['coefficients']

                if feat in feature_names:
                    feat_idx = feature_names.index(feat)
                    row[f"{hall_name}_Coef"] = coef[feat_idx]
                else:
                    row[f"{hall_name}_Coef"] = 0.0

            comparison_rows.append(row)

        comparison_df = pd.DataFrame(comparison_rows)

        # TOP 15 異なる特徴量を抽出（3ホール間で係数が大きく異なるもの）
        comparison_df['Max_Abs_Coef'] = comparison_df[
            [col for col in comparison_df.columns if '_Coef' in col]
        ].abs().max(axis=1)

        comparison_df['Coef_Variance'] = comparison_df[
            [col for col in comparison_df.columns if '_Coef' in col]
        ].var(axis=1)

        # ホール間で差がある特徴量を優先
        top_diff = comparison_df.nlargest(15, 'Max_Abs_Coef')

        print("\n[TOP 15 Features with Largest Coefficients Across Halls]")
        print(top_diff[['Feature', 'マルハン蒲田1_Coef', 'マルハン蒲田7_Coef', 'みとや大森町_Coef']].to_string(index=False))

        # 分散が大きい特徴量（ホール間で戦略が異なる特徴量）
        high_variance = comparison_df[comparison_df['Coef_Variance'] > 0.05].nlargest(10, 'Coef_Variance')

        print("\n[Features with HIGH VARIANCE Across Halls (ホール間戦略差が大きい)]")
        if len(high_variance) > 0:
            print(high_variance[['Feature', 'マルハン蒲田1_Coef', 'マルハン蒲田7_Coef', 'みとや大森町_Coef', 'Coef_Variance']].to_string(index=False))
        else:
            print("(No features with significant variance found)")

        return comparison_df

    def summarize_hall_strategies(self):
        """
        各ホールの戦略を要約
        """
        print(f"\n{'='*100}")
        print("HALL STRATEGY SUMMARY")
        print(f"{'='*100}")

        for hall_name in sorted(self.results.keys()):
            print(f"\n[Hall] {hall_name}")

            result = self.results[hall_name]
            imp_df = result['importance_df']
            auc = result['auc']

            print(f"   Model AUC: {auc:.4f}")
            print(f"   Top positive coefficients (高設定の兆候):")
            pos_df = imp_df[imp_df['Direction'] == 'Positive'].head(5)
            for _, row in pos_df.iterrows():
                print(f"     - {row['Feature']}: {row['Coefficient']:+.4f}")

            print(f"   Top negative coefficients (低設定の兆候):")
            neg_df = imp_df[imp_df['Direction'] == 'Negative'].head(5)
            for _, row in neg_df.iterrows():
                print(f"     - {row['Feature']}: {row['Coefficient']:+.4f}")


def main():
    """Main execution"""
    analyzer = HallComparativeShapAnalysis()

    # 3ホール別に分析
    for hall_name, db_path in analyzer.HALLS.items():
        analyzer.analyze_hall(hall_name, db_path)

    # 比較分析
    analyzer.compare_halls()

    # 戦略サマリー
    analyzer.summarize_hall_strategies()

    print(f"\n{'='*100}")
    print("[OK] 3-Hall Comparative Shap Analysis Completed")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()
